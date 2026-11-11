# -*- coding: utf-8 -*-
"""
OOT 자동 알람 스케줄러 (독립 프로세스)

주기적으로 Databricks `광동제약_gmp_lims`(수정판 LIMS 결과)에서 **전 시험종류**를 조회해
품목·시험항목별 ±2σ 초과 후보 중 **신규** 관리이탈(정책에 따라 주의 포함)을 감지하고,
기존 QMS 메일 모듈(oot_mail → qms_alert.send_email)로 발송한다.
이미 발송한 건은 상태파일(.oot_alarm_state.json)로 중복 차단한다.

★ 첫 실행(상태파일 없음)은 현재 OOT 전체를 '기준선'으로만 기록하고 **발송하지 않는다**
  (과거 누적분 폭주 방지). 이후 새로 발생한 건만 발송한다.

★ 언제 점검하나(2026-11-11): 정해진 시각에 오늘 적재분이 없으면 22:00까지 30분마다 다시 시도한다.
  PC 업로드로 새 자료가 올라오면 약 30초 안에 바로 점검한다. 메일은 LIMS 수정일이 최근 7일 안인 결과만 보낸다
  (점검을 며칠 못 했으면 마지막으로 끝까지 점검한 날 하루 전까지 넓혀 그 공백의 결과는 빠뜨리지 않는다).

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
from datetime import date, datetime, time as dtime, timedelta

from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"), override=False)
sys.path.insert(0, _HERE)
import kdp_core as core  # noqa: E402
import storage_io  # noqa: E402
import oot_mail  # noqa: E402
import axhub_mail  # noqa: E402
import kst  # noqa: E402
import lims_snapshot  # noqa: E402
import oot_export  # noqa: E402

STATE_PATH = os.path.join(_HERE, ".oot_alarm_state.json")
SEEN_PATH = os.path.join(_HERE, ".oot_alarm_data_seen.json")   # 알람이 마지막으로 본 PC 업로드 자료 기준 시각
RECENT_DAYS = 7          # LIMS 수정일이 이 안인 결과만 메일(옛 결과가 모집단 변화로 재판정된 건은 뺀다)
RETRY_SEC = 30 * 60      # 정해진 시각에 자료가 낡았으면 이 간격으로 다시 시도
RETRY_UNTIL = dtime(22, 0)
MAX_SEND_FAILS = 3       # 같은 날 발송 실패 상한(실패로 보여도 실제로는 도착했을 수 있어 끝없이 다시 보내지 않는다)
BOOT_DELAY_SEC = 120     # 기동 직후에는 웹 준비와 메모리가 겹치지 않게 업로드 확인을 미룬다
KEY_MARK = "#keys-v2"                    # 발송 기록 열쇠를 새 꼴로 옮겼다는 표지(옛 코드는 무시)
# 결과 원문 해석(result_parse, 2026-10-22)으로 예전엔 못 읽던 과거 결과가 처음 계산에 들어온다 —
# 그 첫 실행 한 번은 보내지 않고 기준선으로만 기록한다(과거 건 메일이 한꺼번에 몰리지 않게).
PARSE_MARK = "#parse-v1"
LAST_OK_MARK = "#last-ok:"                # 끝까지 점검한 마지막 날(발송 기록 안의 표지)
HELD_MARK = "#held:"                      # 발송 실패 상한으로 미뤄 둔 열쇠(보내면 지운다)
STAB_MARK = "#keys-v3-stab"               # 안정성 열쇠에 시점(의뢰번호)을 넣었다는 표지(한 번만 옮김)
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
        _log(f"network_gate 로드 실패 — 인터넷 확보 생략(발송 계속 시도): {type(e).__name__}")
        return True

    cfg_path = os.getenv("NET_GATE_CONFIG") or _GATE_CONFIG
    if not os.path.exists(cfg_path) and not os.getenv("NET_LOGIN_ID"):
        _log(f"포털 설정 파일 없음({os.path.basename(cfg_path)}) — 인터넷이 막혀 있으면 자동 로그인 불가")

    try:
        ok = network_gate.ensure_internet(config_file=cfg_path)
        _log(f"인터넷 확보 {'성공' if ok else '실패'} (설정: {os.path.basename(cfg_path)})")
        return ok
    except Exception as e:
        _log(f"인터넷 확보 중 예외(무시하고 발송 시도): {type(e).__name__}")
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


_mailed: set = set()     # 이 프로세스가 보낸 열쇠 — 기록 저장이 실패해도 같은 메일을 다시 보내지 않는다
_fails: dict = {}        # (날짜, 시험종류) -> 그날 발송 실패 횟수
# 기록에 '끝까지 점검한 날' 표지가 아직 없을 때(이 표지를 처음 쓰는 배포)의 마지막 점검일. 운영 알람이
# Databricks 403 으로 멈춘 날을 확인하지 못해, 넘김이 멈춘 10-26 전날로 넉넉히 잡는다 — 그 사이 결과를 빠뜨리지 않게.
BOOTSTRAP_LAST_OK = date(2026, 10, 25)


def _last_ok(state: set):
    """끝까지 점검한 마지막 날. 없거나 깨졌으면 None."""
    days = []
    for k in state:
        if k.startswith(LAST_OK_MARK):
            try:
                days.append(date.fromisoformat(k[len(LAST_OK_MARK):]))
            except ValueError:
                pass
    return max(days, default=None)


def _mail_cutoff(state: set) -> str:
    """메일 대상 수정일의 하한. 점검을 며칠 못 했으면 그 공백의 결과가 빠지지 않게 그만큼 넓힌다."""
    cutoff = kst.now().date() - timedelta(days=RECENT_DAYS)
    last = _last_ok(state) or BOOTSTRAP_LAST_OK
    cutoff = min(cutoff, last - timedelta(days=1))
    return cutoff.isoformat()


def _migrate_stability(state: set, cur: dict, v2_of: dict, cutoff: str) -> None:
    """안정성 열쇠에 시점을 넣은 뒤 첫 실행 — 이미 보낸 시점이 다시 메일로 나가지 않게 한 번만 옮긴다.

    예전 열쇠(시점 없음)가 기록에 있으면, 그 로트·항목에서 처음 메일로 나간 시점은 알 수 없지만 가장 먼저
    수정된 시점일 것이다(뒤 시점은 그 열쇠에 막혀 보내지 못했다). 그래서 가장 이른 시점과 기준일보다 오래된
    시점만 본 것으로 적고, 기준일 뒤에 수정된 나머지 시점은 그대로 두어 이번 실행에서 메일로 나가게 한다.

    한계(2026-11-11 운영 자료로 확인): 처음 메일로 나간 시점이 지금 후보에서 빠졌거나, 한 번에 여러 시점이
    처음 들어왔으면 이 추정이 틀릴 수 있다. 운영 자료에서는 해당 12묶음이 모두 시점 하나뿐이었고 발송 이력과
    맞았다(1건은 보낸 값과 같고, 11건은 기준일 전). 이 판보다 앞선 판으로 되돌렸다가 다시 올릴 때는 상태 파일에서
    STAB_MARK 를 지워 옮김을 다시 돌려야 한다(그 사이 예전 판이 보낸 시점이 다시 나가지 않게).
    """
    by_v2: dict = {}
    held = set()
    for k, v2 in v2_of.items():
        if k == v2 or k not in cur:
            continue
        if v2 in state:
            by_v2.setdefault(v2, []).append(k)
        elif HELD_MARK + v2 in state:    # 못 보내 미뤄 둔 예전 열쇠 — 그 시점들도 기준일과 상관없이 대상으로 남긴다
            held.add(HELD_MARK + k)
    add = set()
    for keys in by_v2.values():
        keys.sort(key=lambda k: (cur[k]["수정일"], k))
        add.add(keys[0])
        add.update(k for k in keys[1:] if cur[k]["수정일"] < cutoff)
    left = sum(len(v) for v in by_v2.values()) - len(add)
    state.update(add | held)
    state.add(STAB_MARK)
    _save_quietly(state)                 # 못 적어도 다음 실행이 같은 결과로 다시 옮긴다(보낸 건은 메모리가 막음)
    _log(f"안정성 열쇠에 시점을 넣음 — 이미 본 시점 {len(add)}건 기록, 그 뒤 시점 {left}건은 이번에 새 건으로 봄")


def _save_quietly(state: set) -> None:
    try:
        save_state(state)
    except Exception as e:  # noqa: BLE001 — 값이 실릴 수 있어 종류만
        _log(f"발송 기록을 저장하지 못함({type(e).__name__}) — 이 프로세스가 기억해 같은 메일을 다시 보내지 않음")


def _hold(state: set, keys) -> None:
    """발송 실패 상한으로 오늘 못 보낸 건을 표시한다 — 실패가 며칠 이어져도 7일 기준에 걸려 빠지지 않게."""
    add = {HELD_MARK + k for k in keys} - state
    if add:
        state.update(add)
        _save_quietly(state)


def _finish(state: set) -> bool:
    """끝까지 점검한 날을 기록한다(하루 한 번)."""
    mark = f"{LAST_OK_MARK}{kst.now().date().isoformat()}"
    if mark not in state:
        state.difference_update({k for k in state if k.startswith(LAST_OK_MARK)})
        state.add(mark)
        _save_quietly(state)
    return True


def _send_blocked(tt: str) -> bool:
    """이 시험종류의 오늘 발송 실패가 상한에 닿았는지(다른 시험종류는 막지 않는다)."""
    return _fails.get((kst.now().date(), tt), 0) >= MAX_SEND_FAILS


def _note_send_failure(tt: str) -> bool:
    """발송 실패를 시험종류마다 센다. True 면 다시 시도, False 면 그 시험종류는 오늘 그만(내일 다시 대상)."""
    global _fails
    today = kst.now().date()
    _fails = {k: v for k, v in _fails.items() if k[0] == today}
    n = _fails[(today, tt)] = _fails.get((today, tt), 0) + 1
    if n >= MAX_SEND_FAILS:
        _log(f"  [{tt}] 오늘 발송 실패 {n}번 — 내일 다시 시도합니다")
        return False
    return True


def check_once() -> bool:
    """한 번 점검한다. 끝나면 True, 설정·자료·기록을 못 읽었거나 발송이 실패해 다시 시도해야 하면 False."""
    _beat()
    try:
        cfg = oot_mail.load_config(strict=True)
    except Exception as e:
        _log(f"알림 설정을 읽지 못해 이번 점검을 건너뜀({type(e).__name__}) — 다음 주기 재시도")
        return False
    if not cfg.get("enabled", True):
        _log("알람 비활성화(enabled=false) — 건너뜀")
        return True
    targets = {"관리이탈"} if cfg.get("policy", "관리이탈만") == "관리이탈만" else {"관리이탈", "주의"}

    # Databricks에서 전 시험종류를 한 번에 조회(±2σ 초과 후보, 평균·표준편차 포함).
    try:
        candidates = core.fetch_oot_rows_for_types(_alarm_types())
    except Exception as e:
        _log(f"LIMS 조회 실패: {type(e).__name__}")
        return False
    _beat()

    cur = {}
    old_of = {}                          # 새 열쇠 -> 옛 꼴 열쇠(대분류 없음, a4ef25c)
    v2_of = {}                           # 안정성 시점 열쇠 -> 시점 없는 열쇠(ee28910 까지의 꼴)
    for r in candidates:
        status = _oot_status(r.get("OOT_구간분류_히트맵"))
        if status not in targets:
            continue
        tt = r.get("시험종류", "")
        v2 = "|".join([tt, r.get("품목코드", ""), r.get("제조번호", ""), r.get("대분류", ""),
                       r.get("시험항목", ""), status])
        req = str(r.get("의뢰번호") or "")
        # 안정성은 같은 로트·항목이 시점(의뢰)마다 다시 시험된다 — 시점을 열쇠에 넣어야 다음 시점의 OOT 도 새 건이다.
        key = f"{v2}|{req}" if req else v2
        v2_of[key] = v2
        old_of[key] = "|".join([tt, r.get("품목코드", ""), r.get("제조번호", ""), r.get("시험항목", ""),
                                status])
        if key in cur and r.get("수정일", "") < cur[key]["수정일"]:
            continue                     # 같은 열쇠면 가장 최근에 수정된 결과를 메일에 싣는다
        cur[key] = {"시험종류": tt, "품목": r.get("품목", ""), "품목코드": r.get("품목코드", ""),
                    "제조번호": r.get("제조번호", ""), "대분류": r.get("대분류", ""),
                    "시험항목": r.get("시험항목", ""), "의뢰번호": req,
                    "결과값": r.get("LOT결과_0제외", ""), "분류": r.get("OOT_구간분류_히트맵", ""),
                    "평균": r.get("확인_평균", ""), "표준편차": r.get("확인_표준편차", ""),
                    "수정일": r.get("수정일", "")}

    try:
        state = load_state()
    except Exception as e:
        _log(f"발송 기록을 읽지 못해 이번 점검을 건너뜀({type(e).__name__}) — 다음 주기 재시도")
        return False
    if state is not None:
        state |= _mailed
    # 되돌려도 메일이 몰리지 않게 기록할 때는 옛 꼴 둘(대분류 없음 · 시점 없음)을 함께 적는다.
    def _forms(keys):
        keys = set(keys)
        return keys | {old_of[k] for k in keys} | {v2_of[k] for k in keys}

    if state is None:                    # 처음 실행
        save_state(_forms(cur) | {KEY_MARK, PARSE_MARK, STAB_MARK})
        _log(f"초기 기준선 설정: 현재 OOT {len(cur)}건 기록(발송 안함). 이후 신규분만 발송. "
             f"[대상={'/'.join(sorted(targets))}]")
        return True

    if KEY_MARK not in state:            # 새 코드 첫 실행 — 한 번만
        _migrate_keys(state, cur, old_of)
        state.add(PARSE_MARK)
        save_state(state)
    elif PARSE_MARK not in state:        # 값 해석 확장 뒤 첫 실행 — 한 번만, 보내지 않음
        state.update(_forms(cur))
        state.add(PARSE_MARK)
        state.add(STAB_MARK)             # 지금 후보를 모두 기준선으로 적었으니 시점 옮김도 끝난 것
        save_state(state)
        _log(f"결과 원문 해석 확장 — 현재 OOT {len(cur)}건을 기준선으로 기록(이번에는 발송 안 함). "
             "다음 실행부터 신규분만 발송. 기록한 건(앞 20): "
             + ", ".join(sorted(f"{v['품목코드']}/{v['제조번호']}/{v['시험항목']}" for v in cur.values())[:20]))
        return True
    if STAB_MARK not in state:           # 안정성 시점 열쇠 첫 실행 — 한 번만
        _migrate_stability(state, cur, v2_of, _mail_cutoff(state))
    new_keys = [k for k in cur if k not in state]
    # 옛 결과가 새 결과 때문에 평균·σ가 움직여 재판정된 건은 메일에서 뺀다. 기록하지 않으므로
    # 그 결과를 LIMS 에서 고치거나 재시험해 수정일이 새로워지면 다시 메일 대상이 된다. 화면에는 그대로 보인다.
    # 발송 실패 상한으로 미뤄 둔 건(HELD_MARK)은 기준일과 상관없이 다시 대상이다.
    cutoff = _mail_cutoff(state)
    past = [k for k in new_keys if cur[k]["수정일"] < cutoff and HELD_MARK + k not in state]
    if past:
        new_keys = [k for k in new_keys if k not in set(past)]
        _log(f"과거 결과 재판정 {len(past)}건은 메일에서 제외(LIMS 수정일 {cutoff} 이전)")
    if not new_keys:
        _log(f"신규 OOT 없음 (현재 {len(cur)} · 이력 {len(state)} · 대상 {'/'.join(sorted(targets))})")
        return _finish(state)

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
        state.update(_forms(skipped_keys))              # 되돌려도 다시 보내지 않게 옛 꼴도 기록
        save_state(state)

    # 보낼 대상이 하나도 없으면 인터넷 확보(포털 로그인)조차 하지 않고 종료 — 헛도는 인터넷 켜기 방지
    if not sendable:
        _log(f"  발송할 수신 그룹 없음 — 인터넷 확보/발송 생략 (기준선 {len(skipped_keys)}건 기록).")
        return _finish(state)

    for tt in [t for t in sendable if _send_blocked(t)]:
        _log(f"  [{tt}] 오늘 발송 실패 상한에 닿아 보내지 않음 — 내일 다시 시도")
        _hold(state, sendable.pop(tt))
    if not sendable:
        return _finish(state)

    _ensure_internet_before_send()  # 실제 발송 대상이 있을 때만 인터넷 확보(사내망 캡티브 포털 자동 통과)
    sent_keys: list[str] = []
    retry = False
    src = lims_snapshot.status()
    src_note = f" · PC 업로드 자료 기준 {str(src.get('data_as_of', ''))[:16].replace('T', ' ')}" if src["source"] == "snapshot" else ""
    for tt, keys in sendable.items():
        grp = _grp(tt)
        recs = [cur[k] for k in keys]
        subj = f"[OOT 알람] {tt} 신규 {len(recs)}건 ({kst.now():%Y-%m-%d %H:%M}){src_note}"
        ok, msg = oot_mail.send_oot_alert(recs, cfg=cfg, subject=subj,
                                          dashboard_url=DASH_URL, recipients=grp)
        if ok:
            sent_keys.extend(keys)
            _log(f"  ✅ [{tt}] {len(recs)}건 → {len(grp)}명 발송 성공")
        else:
            _log(f"  ⚠️ [{tt}] 발송 실패: {msg} (이력 미갱신 — 다음 주기 재시도)")
            if _note_send_failure(tt):
                retry = True
            else:
                _hold(state, keys)

    if sent_keys:
        done = _forms(sent_keys)                                    # 되돌려도 다시 보내지 않게 옛 꼴도 기록
        _mailed.update(done)
        state.update(done)
        state.difference_update(HELD_MARK + k for k in sent_keys)
        _save_quietly(state)
        _log(f"발송 성공 {len(sent_keys)}건 · 이력 {len(state)}건으로 갱신")
    # 상한에 닿아 오늘 그만둔 시험종류만 남았으면 오늘 점검은 끝난 것으로 본다(다음 날 기준일이 계속 넓어지지 않게).
    return False if retry else _finish(state)


def _data_fresh() -> bool:
    """오늘 적재분이 있는지(Databricks 또는 PC 업로드 자료). 못 읽으면 예외."""
    by_table = {str(r["T"]): r["M"] for r in core.dbx.query(oot_export.FRESH_SQL)}
    _as_of, fresh = oot_export.freshness(by_table, oot_export.now_utc())
    if not fresh["ok"]:
        _log(f"자료가 낡음 — {fresh['reason']}")
    return fresh["ok"]


def _load_seen():
    """마지막으로 본 업로드 기준 시각. (읽었는지, 값)"""
    try:
        d = storage_io.read_json_strict(SEEN_PATH)
        return True, (d or {}).get("data_as_of")
    except Exception as e:  # noqa: BLE001
        _log(f"업로드 확인 기록을 읽지 못함({type(e).__name__})")
        return False, None


def _save_seen(as_of: str) -> None:
    try:
        storage_io.write_json(SEEN_PATH, {"data_as_of": as_of})
    except Exception as e:  # noqa: BLE001 — 저장 실패는 재시작 뒤 한 번 더 점검할 뿐이다
        _log(f"업로드 확인 기록을 저장하지 못함({type(e).__name__})")


def _new_upload_as_of(seen):
    """알람이 아직 안 본 새 업로드의 자료 기준 시각. 없으면 None."""
    meta = lims_snapshot.latest_meta()
    if not meta:
        return None
    as_of = meta["data_as_of"]
    if seen:
        try:
            if datetime.fromisoformat(as_of) <= datetime.fromisoformat(seen):
                return None
        except (TypeError, ValueError):
            pass
    return as_of


def _attempt() -> bool:
    """자료가 오늘 것이면 점검한다. 점검을 끝내면 True. 끝나면 사본 연결을 놓는다."""
    try:
        if not _data_fresh():
            return False
        return bool(check_once())
    finally:
        lims_snapshot.release()


def _check_upload() -> bool:
    """새 업로드를 처리한다. True 면 본 것으로 기록(낡은 자료는 메일 없이 넘어감), False 면 잠시 뒤 다시."""
    try:
        return (not _data_fresh()) or bool(check_once())
    except Exception as e:  # noqa: BLE001 — 값이 실릴 수 있어 종류만
        _log(f"업로드 점검 오류: {type(e).__name__}")
        return False
    finally:
        lims_snapshot.release()


def _next_after_attempt(done: bool, dt: str, now_ts: float) -> float:
    """매일 실행의 다음 시각: 끝났으면 내일, 못 끝냈으면 22:00까지 30분 뒤."""
    if not done:
        nxt = kst.now() + timedelta(seconds=RETRY_SEC)
        if nxt.date() == kst.now().date() and nxt.time() <= RETRY_UNTIL:
            _log(f"{nxt:%H:%M} 에 다시 시도합니다(22:00까지)")
            return now_ts + RETRY_SEC
        _log("22:00까지 새 자료가 없어 오늘 점검을 마칩니다")
    return now_ts + _seconds_until_daily(dt)


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
            sched = (oot_mail.load_config(strict=True) or {}).get("schedule", {}) or {}
        except Exception:
            if last_sig is not None:     # 한 번 못 읽었다고 기본 일정으로 바꾸면 그날 재시도가 사라진다
                return last_sig
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

    last_sig = None
    mode, dt, iv = _load_schedule()
    _log(f"OOT 자동 알람 시작 · {_desc(mode, dt, iv)}(한국 시간) · 메일: {axhub_mail.transport_name()} (Ctrl+C 종료)")
    last_run, next_run = None, 0.0
    seen_loaded, seen = False, None
    upload_at = time.time() + BOOT_DELAY_SEC
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
            done = False
            try:
                done = _attempt()
            except Exception as e:
                _log(f"점검 오류: {type(e).__name__}")
            last_run = time.time()
            next_run = _next_after_attempt(done, dt, last_run) if mode == "daily" else (last_run + iv * 60)
            if mode == "daily":
                secs = next_run - last_run
                _log(f"다음 실행까지 {int(secs // 3600)}시간 {int((secs % 3600) // 60)}분 대기 ({_desc(mode, dt, iv)})")
        elif now >= upload_at:           # 약 30초마다 — 새 업로드가 있으면 바로 점검
            try:
                if not seen_loaded:
                    seen_loaded, seen = _load_seen()
                as_of = _new_upload_as_of(seen) if seen_loaded else None
                if as_of:
                    _log(f"새 업로드 감지(자료 기준 {as_of[:16].replace('T', ' ')}) — 바로 점검")
                    if _check_upload():
                        seen = as_of
                        _save_seen(as_of)
                    else:                # 실패해도 매일 재시도와 같은 간격·같은 상한으로만 다시 본다
                        upload_at = _next_after_attempt(False, dt, time.time())
            except Exception as e:  # noqa: BLE001 — 알람 프로세스를 죽이지 않는다
                _log(f"업로드 확인 오류: {type(e).__name__}")
                upload_at = _next_after_attempt(False, dt, time.time())
        _beat()
        time.sleep(max(1, min(30, next_run - time.time())))


if __name__ == "__main__":
    main()
