# -*- coding: utf-8 -*-
"""
OOT 자동 알람 스케줄러 (독립 프로세스)

주기적으로 Databricks `광동제약_gmp_lims`(수정판 LIMS 결과)에서 **전 시험종류**를 조회해
품목·시험항목별 ±2σ 초과 후보 중 **신규** 관리이탈(정책에 따라 주의 포함)을 감지하고,
기존 QMS 메일 모듈(oot_mail → qms_alert.send_email)로 발송한다.
이미 발송한 건은 상태파일(.oot_alarm_state.json)로 중복 차단한다.

★ 첫 실행(상태파일 없음)은 현재 OOT 전체를 '기준선'으로만 기록하고 **발송하지 않는다**
  (과거 누적분 폭주 방지). 이후 새로 발생한 건만 발송한다.

★ 발송 기록 열쇠(2026-10-04): 대분류를 넣은 새 꼴(시험종류|품목코드|제조번호|대분류|시험항목|상태).
  예전 기록(대분류 없는 옛 꼴)은 새 코드 첫 실행에서 **한 번만** 옮긴다 — 표지 '#keys-v2'.
  옛 열쇠는 지우지 않고, 새로 기록하는 건마다 옛 꼴 열쇠도 함께 적어 예전 코드로 되돌려도
  메일이 몰리지 않게 한다. 옮기는 방식은 환경값 OOT_ALARM_KEY_MODE:
    migrate(기본, A)  : 지금 후보 중 옛 꼴 열쇠가 기록에 있는 것만 새 열쇠를 더함 → 진짜 새 건만 발송
    rebaseline(B)     : 지금 후보 전부를 기록에 더하고 그 실행에서는 보내지 않음(지우지 않음)

실행:
  python oot_alarm.py --once            # 1회 점검
  python oot_alarm.py --interval 10     # 10분 주기 무한 루프(상주)
  python oot_alarm.py --reset-state     # 발송 이력 초기화(다음 실행이 새 기준선)
"""
from __future__ import annotations

import argparse
import os
import sys
import re
import time

from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"), override=False)
sys.path.insert(0, _HERE)
import kdp_core as core  # noqa: E402
import storage_io  # noqa: E402
import oot_mail  # noqa: E402
import axhub_mail  # noqa: E402
import kst  # noqa: E402

STATE_PATH = os.path.join(_HERE, ".oot_alarm_state.json")
KEY_MARK = "#keys-v2"                    # 발송 기록 열쇠를 새 꼴로 옮겼다는 표지(옛 코드는 무시)
# 결과 원문 해석(result_parse, 2026-10-22)으로 예전엔 못 읽던 과거 결과가 처음 계산에 들어온다 —
# 그 첫 실행 한 번은 보내지 않고 기준선으로만 기록한다(과거 건 메일이 한꺼번에 몰리지 않게).
PARSE_MARK = "#parse-v1"
KEY_MODE = os.getenv("OOT_ALARM_KEY_MODE", "migrate").strip().lower()
LOG_PATH = os.path.join(_HERE, "oot_alarm.log")
DASH_URL = os.getenv("OOT_DASHBOARD_URL", "http://localhost:8502")

# 시험종류 — 전체 커버. vf_시험종류로 조회하며 각 행에 시험종류를 태깅(export에 시험종류 컬럼 없음).
OOT_TEST_TYPES = [
    "완제품", "원료시험", "반제품", "직접자재", "시험기기 및 기구", "기타시험",
    "장기 안정성시험(Long Term)", "가속 안정성시험(Acclerated)",
    "시판후 안정성시험(Ongoing Stability)", "4b장기 안정성시험(LT4b)",
]


_URL_RE = re.compile(r"https?://\S+")
HEARTBEAT_PATH = os.path.join(os.environ.get("TMPDIR", "/tmp"), "oot_alarm_heartbeat")


def _beat() -> None:
    """살아 있음 표시(컨테이너 안 임시 파일) — /api/health 가 오래 갱신 안 되면 알람이 죽은 것으로 본다."""
    try:
        with open(HEARTBEAT_PATH, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except Exception:
        pass


def _log(msg: str) -> None:
    msg = _URL_RE.sub("[주소 생략]", str(msg))      # 서명 주소 등은 로그·이력 화면에 남기지 않는다
    line = f"[{kst.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# 사내 캡티브 포털(인터넷 로그인) 설정 — OOT 폴더 자체 파일(다른 프로젝트 폴더에 의존하지 않음)
_GATE_CONFIG = os.path.join(_HERE, "network_gate.json")


def _ensure_internet_before_send() -> bool:
    """발송 직전 인터넷을 확보한다(사내망에서 인터넷을 쓰려면 캡티브 포털 로그인 필요).
    - 이미 인터넷이 되면 브라우저 없이 즉시 통과.
    - 막혀 있으면 network_gate가 포털에 자동 로그인(#uid/#pwd/#oBtnLogin) 후 재확인.
    설정/자격증명 우선순위: env NET_LOGIN_ID/NET_PASSWORD(.env) > NET_GATE_CONFIG(env)가 가리키는 파일
      > 이 폴더의 network_gate.json.
    실패해도 예외로 죽지 않고 발송을 시도한다(실패 시 다음 주기 재시도).
    """
    if axhub_mail.available():
        return True                      # axhub 운영: HTTPS 플랫폼 메일 — 사내망 포털 확인 불필요
    try:
        import network_gate  # 같은 폴더에 복사됨
    except Exception as e:
        _log(f"network_gate 로드 실패 — 인터넷 확보 생략(발송 계속 시도): {e}")
        return True

    cfg_path = os.getenv("NET_GATE_CONFIG") or _GATE_CONFIG
    if not os.path.exists(cfg_path) and not os.getenv("NET_LOGIN_ID"):
        _log(f"포털 설정 파일 없음({os.path.basename(cfg_path)}) — 인터넷이 막혀 있으면 자동 로그인 불가")

    try:
        ok = network_gate.ensure_internet(config_file=cfg_path)
        _log(f"인터넷 확보 {'성공' if ok else '실패'} (설정: {os.path.basename(cfg_path)})")
        return ok
    except Exception as e:
        _log(f"인터넷 확보 중 예외(무시하고 발송 시도): {e}")
        return True


def _oot_status(s) -> str:
    s = str(s or "")
    if "주의" in s:
        return "주의"
    if "관리이탈" in s or "초과" in s:
        return "관리이탈"
    if "정상" in s:
        return "정상"
    return "데이터부족"


def load_state():
    """발송 기록(본 OOT 열쇠). 파일이 없으면 None, 읽기 오류면 예외(빈 기록으로 보고 메일을 다시 보내지 않게)."""
    keys = storage_io.read_json_strict(STATE_PATH)
    return set(keys) if keys is not None else None


def _alarm_types() -> list:
    """감시 대상 — 화면과 같은 전체 시험종류(2026-10-22). 목록 조회 실패 시 고정 목록."""
    try:
        types = core.oot_test_types()
        return list(types) if types else list(OOT_TEST_TYPES)
    except Exception:
        return list(OOT_TEST_TYPES)


def save_state(keys) -> None:
    storage_io.write_json(STATE_PATH, sorted(keys))


def _migrate_keys(state: set, cur: dict, old_of: dict) -> None:
    """발송 기록 열쇠를 새 꼴로 한 번만 옮긴다(옛 열쇠는 그대로 둠). 방식은 KEY_MODE — 모듈 주석 참고."""
    if KEY_MODE == "rebaseline":
        add = set(cur) | {old_of[k] for k in cur}
        how = "기준선 다시 잡기(이번에는 보내지 않음)"
    else:
        add = {k for k in cur if old_of[k] in state}
        how = "열쇠 옮김(예전에 본 건만)"
    state.update(add)
    state.add(KEY_MARK)
    save_state(state)
    _log(f"발송 기록 열쇠 옮김 — {how}: 새 열쇠 {len(add)}건 더함 · 옛 열쇠는 그대로 둠")


def check_once() -> None:
    _beat()
    try:
        cfg = oot_mail.load_config(strict=True)
    except Exception as e:
        _log(f"알림 설정을 읽지 못해 이번 점검을 건너뜀({type(e).__name__}) — 다음 주기 재시도")
        return
    if not cfg.get("enabled", True):
        _log("알람 비활성화(enabled=false) — 건너뜀")
        return
    targets = {"관리이탈"} if cfg.get("policy", "관리이탈만") == "관리이탈만" else {"관리이탈", "주의"}

    # Databricks에서 전 시험종류를 한 번에 조회(±2σ 초과 후보, 평균·표준편차 포함).
    try:
        candidates = core.fetch_oot_rows_for_types(_alarm_types())
    except Exception as e:
        _log(f"Databricks 조회 실패: {type(e).__name__}: {e}")
        return
    _beat()

    cur = {}
    old_of = {}                          # 새 열쇠 -> 옛 꼴 열쇠(대분류 없음, a4ef25c)
    for r in candidates:
        status = _oot_status(r.get("OOT_구간분류_히트맵"))
        if status not in targets:
            continue
        tt = r.get("시험종류", "")
        key = "|".join([tt, r.get("품목코드", ""), r.get("제조번호", ""), r.get("대분류", ""),
                        r.get("시험항목", ""), status])
        old_of[key] = "|".join([tt, r.get("품목코드", ""), r.get("제조번호", ""), r.get("시험항목", ""),
                                status])
        cur[key] = {"시험종류": tt, "품목": r.get("품목", ""), "품목코드": r.get("품목코드", ""),
                    "제조번호": r.get("제조번호", ""), "대분류": r.get("대분류", ""),
                    "시험항목": r.get("시험항목", ""),
                    "결과값": r.get("LOT결과_0제외", ""), "분류": r.get("OOT_구간분류_히트맵", ""),
                    "평균": r.get("확인_평균", ""), "표준편차": r.get("확인_표준편차", "")}

    try:
        state = load_state()
    except Exception as e:
        _log(f"발송 기록을 읽지 못해 이번 점검을 건너뜀({type(e).__name__}) — 다음 주기 재시도")
        return
    if state is None:                    # 처음 실행
        save_state(set(cur) | set(old_of.values()) | {KEY_MARK, PARSE_MARK})
        _log(f"초기 기준선 설정: 현재 OOT {len(cur)}건 기록(발송 안함). 이후 신규분만 발송. "
             f"[대상={'/'.join(sorted(targets))}]")
        return

    if KEY_MARK not in state:            # 새 코드 첫 실행 — 한 번만
        _migrate_keys(state, cur, old_of)
        state.add(PARSE_MARK)
        save_state(state)
    elif PARSE_MARK not in state:        # 값 해석 확장 뒤 첫 실행 — 한 번만, 보내지 않음
        state.update(set(cur) | set(old_of.values()))
        state.add(PARSE_MARK)
        save_state(state)
        _log(f"결과 원문 해석 확장 — 현재 OOT {len(cur)}건을 기준선으로 기록(이번에는 발송 안 함). "
             "다음 실행부터 신규분만 발송. 기록한 건(앞 20): "
             + ", ".join(sorted(f"{v['품목코드']}/{v['제조번호']}/{v['시험항목']}" for v in cur.values())[:20]))
        return
    new_keys = [k for k in cur if k not in state]
    if not new_keys:
        _log(f"신규 OOT 없음 (현재 {len(cur)} · 이력 {len(state)} · 대상 {'/'.join(sorted(targets))})")
        return

    _log(f"신규 OOT {len(new_keys)}건 감지 → 시험종류별 그룹 발송 시도")
    groups = cfg.get("recipient_groups") or {}
    # 신규 키를 시험종류별로 그룹핑(각 레코드의 '시험종류' 기준)
    by_tt: dict[str, list[str]] = {}
    for k in new_keys:
        by_tt.setdefault(cur[k].get("시험종류", ""), []).append(k)

    # 수신 그룹이 지정된 시험종류만 실제 발송 대상. 미지정은 먼저 로그로 남기고 제외.
    def _grp(tt: str) -> list[str]:
        return [e.strip() for e in (groups.get(tt) or []) if e and e.strip()]
    sendable = {tt: keys for tt, keys in by_tt.items() if _grp(tt)}
    skipped_keys: list[str] = []
    for tt, keys in by_tt.items():
        if tt not in sendable:
            _log(f"  [{tt}] 수신 그룹 미지정 — {len(keys)}건 발송 생략(기준선 처리)")
            skipped_keys.extend(keys)

    # 수신자 미지정 시험종류는 기준선 처리: 본 것으로 기록해 다음 주기 재감지·로그반복을 막는다.
    # (추후 해당 종류에 수신자를 지정하면, 그 시점 이후 '신규' 건부터 발송됨)
    if skipped_keys:
        state.update(skipped_keys)
        state.update(old_of[k] for k in skipped_keys)   # 되돌려도 다시 보내지 않게 옛 꼴도 기록
        save_state(state)

    # 보낼 대상이 하나도 없으면 인터넷 확보(포털 로그인)조차 하지 않고 종료 — 헛도는 인터넷 켜기 방지
    if not sendable:
        _log(f"  발송할 수신 그룹 없음 — 인터넷 확보/발송 생략 (기준선 {len(skipped_keys)}건 기록).")
        return

    _ensure_internet_before_send()  # 실제 발송 대상이 있을 때만 인터넷 확보(사내망 캡티브 포털 자동 통과)
    sent_keys: list[str] = []
    for tt, keys in sendable.items():
        grp = _grp(tt)
        recs = [cur[k] for k in keys]
        subj = f"[OOT 알람] {tt} 신규 {len(recs)}건 ({kst.now():%Y-%m-%d %H:%M})"
        ok, msg = oot_mail.send_oot_alert(recs, cfg=cfg, subject=subj,
                                          dashboard_url=DASH_URL, recipients=grp)
        if ok:
            sent_keys.extend(keys)
            _log(f"  ✅ [{tt}] {len(recs)}건 → {len(grp)}명 발송 성공")
        else:
            _log(f"  ⚠️ [{tt}] 발송 실패: {msg} (이력 미갱신 — 다음 주기 재시도)")

    if sent_keys:
        state.update(sent_keys)
        state.update(old_of[k] for k in sent_keys)      # 되돌려도 다시 보내지 않게 옛 꼴도 기록
        save_state(state)
        _log(f"발송 성공 {len(sent_keys)}건 · 이력 {len(state)}건으로 갱신")


def _seconds_until_daily(hhmm: str) -> float:
    """다음 hhmm(HH:MM, 한국 시간)까지 남은 초. 형식 오류면 07:30으로 폴백."""
    from datetime import timedelta
    try:
        hh, mm = [int(x) for x in str(hhmm).strip().split(":")]
    except Exception:
        hh, mm = 7, 30
    now = kst.now()          # 컨테이너 시계(UTC)가 아니라 한국 시간 기준
    tgt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if tgt <= now:
        tgt += timedelta(days=1)
    return (tgt - now).total_seconds()


def main():
    ap = argparse.ArgumentParser(description="OOT 자동 알람 스케줄러")
    ap.add_argument("--once", action="store_true", help="1회 점검 후 종료")
    ap.add_argument("--interval", type=int, default=None, metavar="MIN",
                    help="주기(분) 수동 지정 — interval 모드 (예: --interval 10)")
    ap.add_argument("--daily", type=str, default=None, metavar="HH:MM",
                    help="매일 지정 시각 실행 — daily 모드 (예: --daily 07:30)")
    ap.add_argument("--reset-state", action="store_true", help="발송 이력 초기화")
    a = ap.parse_args()

    # 끄는 스위치 — 스테이징은 운영과 보관함(발송 기록·설정)을 같이 써서, 알람이 두 곳에서 돌면 같은 건을
    # 두 번 보내거나 기록을 서로 덮을 수 있다. 스테이징에만 OOT_ALARM_OFF=1 을 둔다(axhub env set-staging-value).
    if os.getenv("OOT_ALARM_OFF", "").strip() == "1":
        _log("OOT 자동 알람 끔 — 끄는 스위치 OOT_ALARM_OFF=1")
        return

    if a.reset_state:
        storage_io.remove(STATE_PATH)
        _log("발송 이력 초기화 완료 (다음 실행이 새 기준선)")
        return
    if a.once:
        check_once()
        return

    def _beat_loop():                    # 프로세스가 살아 있는 동안 30초마다 — 조회가 길어도 갱신된다
        while True:
            _beat()
            time.sleep(30)
    import threading
    threading.Thread(target=_beat_loop, daemon=True).start()

    def _load_schedule():
        """스케줄 결정 — 우선순위: CLI 인자 > 설정파일(schedule) > 기본값(매일 07:30).
        매 루프마다 다시 읽으므로 알림설정 화면에서 바꾼 값이 재시작 없이 1분 내 반영된다."""
        try:
            sched = (oot_mail.load_config() or {}).get("schedule", {}) or {}
        except Exception:
            sched = {}
        try:
            iv = int(sched.get("interval_min", 10) or 10)
        except (TypeError, ValueError):
            iv = 10
        dt = str(sched.get("daily_time", "07:30") or "07:30")
        mode = str(sched.get("mode", "daily") or "daily").lower()
        if a.daily:
            mode, dt = "daily", a.daily
        elif a.interval is not None:
            mode, iv = "interval", a.interval
        return ("interval" if mode == "interval" else "daily"), dt, max(1, iv)

    def _desc(mode, dt, iv):
        return f"매일 {dt} 실행" if mode == "daily" else f"{iv}분 주기"

    mode, dt, iv = _load_schedule()
    _log(f"OOT 자동 알람 시작 · {_desc(mode, dt, iv)}(한국 시간) · 메일: {axhub_mail.transport_name()} (Ctrl+C 종료)")
    last_sig, last_run, next_run = None, None, 0.0
    while True:
        mode, dt, iv = _load_schedule()
        sig = (mode, dt, iv)
        now = time.time()
        if sig != last_sig:  # 최초 또는 설정 변경 → 다음 실행 시각 재계산
            if last_sig is not None:
                _log(f"스케줄 변경 감지 → {_desc(mode, dt, iv)}")
            if mode == "daily":
                next_run = now + _seconds_until_daily(dt)
            else:  # interval: 처음이면 즉시, 이후엔 마지막 실행 기준
                next_run = now if last_run is None else last_run + iv * 60
            secs = max(0, next_run - now)
            _log(f"다음 실행까지 {int(secs // 3600)}시간 {int((secs % 3600) // 60)}분 대기 ({_desc(mode, dt, iv)})")
            last_sig = sig
        if now >= next_run:
            try:
                check_once()
            except Exception as e:
                _log(f"점검 오류: {e}")
            last_run = time.time()
            next_run = (last_run + _seconds_until_daily(dt)) if mode == "daily" else (last_run + iv * 60)
            if mode == "daily":
                secs = next_run - last_run
                _log(f"다음 실행까지 {int(secs // 3600)}시간 {int((secs % 3600) // 60)}분 대기 ({_desc(mode, dt, iv)})")
        _beat()
        time.sleep(max(1, min(30, next_run - time.time())))


if __name__ == "__main__":
    main()
