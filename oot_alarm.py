# -*- coding: utf-8 -*-
"""
OOT 자동 알람 스케줄러 (독립 프로세스)

주기적으로 Tableau OOT_추출용 **전체(시험종류 등 필터 없음)** 를 조회해 **신규** 관리이탈
(정책에 따라 주의 포함)을 감지하고, 기존 QMS 메일 모듈(oot_mail → qms_alert.send_email)로 발송한다.
이미 발송한 건은 상태파일(.oot_alarm_state.json)로 중복 차단한다.

★ 첫 실행(상태파일 없음)은 현재 OOT 전체를 '기준선'으로만 기록하고 **발송하지 않는다**
  (과거 누적분 폭주 방지). 이후 새로 발생한 건만 발송한다.

실행:
  python oot_alarm.py --once            # 1회 점검
  python oot_alarm.py --interval 10     # 10분 주기 무한 루프(상주)
  python oot_alarm.py --reset-state     # 발송 이력 초기화(다음 실행이 새 기준선)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import date, datetime

import httpx
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"), override=False)
sys.path.insert(0, _HERE)
import oot_mail  # noqa: E402

SERVER = os.getenv("TABLEAU_SERVER", "http://tableau.ekdp.com")
VER = os.getenv("TABLEAU_API_VERSION", "3.21")
BASE = f"{SERVER}/api/{VER}"
PAT_NAME = os.getenv("TABLEAU_PAT_NAME", "MISO")
PAT_SECRET = os.getenv("TABLEAU_PAT_SECRET", "")
WORKBOOK = "OOT 대시보드"
VIEW = "OOT_추출용"
STATE_PATH = os.path.join(_HERE, ".oot_alarm_state.json")
PAT_STATE_PATH = os.path.join(_HERE, ".pat_alarm_state.json")
LOG_PATH = os.path.join(_HERE, "oot_alarm.log")
DASH_URL = os.getenv("OOT_DASHBOARD_URL", "http://localhost:8502")
PAT_WARN_DAYS = int(os.getenv("TABLEAU_PAT_WARN_DAYS", "20"))

# 시험종류 — 전체 커버. vf_시험종류로 조회하며 각 행에 시험종류를 태깅(export에 시험종류 컬럼 없음).
OOT_TEST_TYPES = [
    "완제품", "원료시험", "반제품", "직접자재", "시험기기 및 기구", "기타시험",
    "장기 안정성시험(Long Term)", "가속 안정성시험(Acclerated)",
    "시판후 안정성시험(Ongoing Stability)", "4b장기 안정성시험(LT4b)",
]


def _log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
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


def _num(x) -> float:
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return float("nan")


def _signin(c):
    if not PAT_SECRET:
        raise RuntimeError("TABLEAU_PAT_SECRET 미설정(.env)")
    r = c.post(f"{BASE}/auth/signin", json={"credentials": {
        "personalAccessTokenName": PAT_NAME, "personalAccessTokenSecret": PAT_SECRET,
        "site": {"contentUrl": ""}}},
        headers={"Accept": "application/json", "Content-Type": "application/json"})
    r.raise_for_status()
    cr = r.json()["credentials"]
    return cr["token"], cr["site"]["id"]


def _view_id(c, tok, site):
    H = {"X-Tableau-Auth": tok, "Accept": "application/json"}
    wbm = {w["id"]: w["name"] for w in c.get(f"{BASE}/sites/{site}/workbooks",
           headers=H, params={"pageSize": "1000"}).json()["workbooks"]["workbook"]}
    for v in c.get(f"{BASE}/sites/{site}/views", headers=H,
                   params={"pageSize": "1000"}).json()["views"]["view"]:
        if v["name"] == VIEW and wbm.get(v.get("workbook", {}).get("id", "")) == WORKBOOK:
            return v["id"]
    return None


def load_state() -> set:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_state(keys) -> None:
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, ensure_ascii=False)


def check_pat_expiry(cfg: dict) -> None:
    """PAT 만료일 점검 — 잔여 ≤ 임계(기본 20일)이면 PAT 수신자에게 메일.
    10분 주기 스팸 방지를 위해 같은 만료일 기준 **하루 1회**만 발송(.pat_alarm_state.json)."""
    expiry = str(cfg.get("pat_expiry") or os.getenv("TABLEAU_PAT_EXPIRY", "")).strip()
    if not expiry:
        return                                   # 만료일 미설정 — 점검 생략
    try:
        exp = datetime.strptime(expiry[:10], "%Y-%m-%d").date()
    except ValueError:
        _log(f"PAT 만료일 형식 오류: {expiry!r}")
        return
    days_left = (exp - date.today()).days
    if days_left > PAT_WARN_DAYS:
        return                                   # 아직 여유 — 알림 없음
    recips = [e.strip() for e in (cfg.get("pat_recipients") or []) if e and e.strip()]
    if not recips:
        _log(f"PAT 만료 D-{days_left}({exp}) — PAT 수신자 미지정, 발송 생략")
        return
    # 같은 만료일 기준 오늘 이미 보냈으면 생략(일 1회)
    today = date.today().isoformat()
    st = {}
    if os.path.exists(PAT_STATE_PATH):
        try:
            with open(PAT_STATE_PATH, encoding="utf-8") as f:
                st = json.load(f) or {}
        except Exception:
            st = {}
    if st.get("last_sent") == today and st.get("expiry") == exp.isoformat():
        _log(f"PAT 만료 D-{days_left}({exp}) — 오늘 이미 발송, 생략")
        return
    ok, msg = oot_mail.send_pat_alert(PAT_NAME, exp.isoformat(), days_left,
                                      cfg=cfg, recipients=recips, tableau_url=SERVER)
    if ok:
        with open(PAT_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"last_sent": today, "expiry": exp.isoformat(), "days_left": days_left},
                      f, ensure_ascii=False)
        _log(f"✅ PAT 만료 알림 발송: D-{days_left}({exp}) → {len(recips)}명")
    else:
        _log(f"⚠️ PAT 만료 알림 실패: {msg} (다음 주기 재시도)")


def check_once() -> None:
    cfg = oot_mail.load_config()
    try:
        check_pat_expiry(cfg)                    # PAT 만료 점검(Tableau 무관 — 항상 수행)
    except Exception as e:
        _log(f"PAT 만료 점검 오류: {e}")
    if not cfg.get("enabled", True):
        _log("알람 비활성화(enabled=false) — 건너뜀")
        return
    targets = {"관리이탈"} if cfg.get("policy", "관리이탈만") == "관리이탈만" else {"관리이탈", "주의"}

    c = httpx.Client(timeout=180.0, verify=False)
    try:
        tok, site = _signin(c)
        vid = _view_id(c, tok, site)
        if not vid:
            _log("OOT_추출용 뷰를 찾지 못함")
            return
    except Exception as e:
        _log(f"Tableau 인증 실패: {e}")
        return

    # 시험종류별로 조회 → 각 행에 시험종류 태깅(전체 시험종류 커버). 현재 OOT(정량·대상분류).
    cur = {}
    total = 0
    for tt in OOT_TEST_TYPES:
        try:
            text = c.get(f"{BASE}/sites/{site}/views/{vid}/data",
                         headers={"X-Tableau-Auth": tok}, params={"vf_시험종류": tt}).text
        except Exception as e:
            _log(f"[{tt}] 조회 실패: {e}")
            continue
        for r in csv.DictReader(io.StringIO(text)):
            total += 1
            status = _oot_status(r.get("OOT_구간분류_히트맵"))
            if status not in targets:
                continue
            if not (_num(r.get("확인_표준편차")) > 0):   # 정성/데이터부족 제외
                continue
            key = "|".join([tt, r.get("품목코드", ""), r.get("제조번호", ""),
                            r.get("시험항목", ""), status])
            cur[key] = {"시험종류": tt, "품목": r.get("품목", ""), "품목코드": r.get("품목코드", ""),
                        "제조번호": r.get("제조번호", ""), "시험항목": r.get("시험항목", ""),
                        "결과값": r.get("LOT결과_0제외", ""), "분류": r.get("OOT_구간분류_히트맵", ""),
                        "평균": r.get("확인_평균", ""), "표준편차": r.get("확인_표준편차", "")}
    if total == 0:
        _log("데이터 비어있음(extract 갱신 중일 수 있음) — 건너뜀")
        return

    first_run = not os.path.exists(STATE_PATH)
    if first_run:
        save_state(set(cur))
        _log(f"초기 기준선 설정: 현재 OOT {len(cur)}건 기록(발송 안함). 이후 신규분만 발송. "
             f"[대상={'/'.join(sorted(targets))}]")
        return

    state = load_state()
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
        subj = f"[OOT 알람] {tt} 신규 {len(recs)}건 ({datetime.now():%Y-%m-%d %H:%M})"
        ok, msg = oot_mail.send_oot_alert(recs, cfg=cfg, subject=subj,
                                          dashboard_url=DASH_URL, tableau_url=SERVER, recipients=grp)
        if ok:
            sent_keys.extend(keys)
            _log(f"  ✅ [{tt}] {len(recs)}건 → {len(grp)}명 발송 성공")
        else:
            _log(f"  ⚠️ [{tt}] 발송 실패: {msg} (이력 미갱신 — 다음 주기 재시도)")

    if sent_keys:
        state.update(sent_keys)
        save_state(state)
        _log(f"발송 성공 {len(sent_keys)}건 · 이력 {len(state)}건으로 갱신")


def _seconds_until_daily(hhmm: str) -> float:
    """다음 hhmm(HH:MM)까지 남은 초. 형식 오류면 07:30으로 폴백."""
    from datetime import timedelta
    try:
        hh, mm = [int(x) for x in str(hhmm).strip().split(":")]
    except Exception:
        hh, mm = 7, 30
    now = datetime.now()
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

    if a.reset_state:
        if os.path.exists(STATE_PATH):
            os.remove(STATE_PATH)
        _log("발송 이력 초기화 완료 (다음 실행이 새 기준선)")
        return
    if a.once:
        check_once()
        return

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
    _log(f"OOT 자동 알람 시작 · {_desc(mode, dt, iv)} (Ctrl+C 종료)")
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
        time.sleep(max(1, min(30, next_run - time.time())))


if __name__ == "__main__":
    main()
