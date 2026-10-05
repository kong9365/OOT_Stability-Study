# -*- coding: utf-8 -*-
"""
dashboard_api.py — 광동 품질·시험 통합 대시보드 백엔드(FastAPI).

webapp/ 정적 프론트엔드를 서빙하고, OOT/안정성/알림 JSON API를 제공한다.
데이터·분석은 kdp_core, 알림 설정은 oot_mail 을 재사용한다.

실행:  python -m uvicorn dashboard_api:app --host 0.0.0.0 --port 8502
"""
from __future__ import annotations

import hmac
import json
import os
import re
import threading
import time
import urllib.parse
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import kdp_core as core
import oot_export
import oot_group
import oot_mail
import recipients_db
import storage_io

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEBAPP = os.path.join(_HERE, "webapp")
_ALARM_PREFS = os.path.join(_HERE, ".webapp_alarm.json")
_GROUPS = oot_group.GroupStore(os.path.join(_HERE, "item_groups.json"))

app = FastAPI(title="광동 품질·시험 통합 대시보드 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── OOT ──────────────────────────────────────────────────────────────────────
@app.get("/api/oot/products")
def api_oot_products(test_type: str = Query("완제품")):
    try:
        return {"testType": test_type, "testTypes": core.oot_test_types(),
                "products": core.oot_products(test_type)}
    except Exception as e:
        raise HTTPException(502, f"품목 목록 로드 실패: {e}")


@app.get("/api/oot/lots")
def api_oot_lots(code: str, test_type: str = Query("완제품"), year: Optional[str] = None):
    try:
        return core.oot_lot_summary(code, test_type, year=year)
    except Exception as e:
        raise HTTPException(502, f"LOT 데이터 로드 실패: {e}")


@app.get("/api/oot/excel")
def api_oot_excel(code: str, test_type: str = Query("완제품"), year: Optional[str] = None):
    """OOT 조회(연도 필터 반영) → 첨부 양식 엑셀(.xlsx) 다운로드."""
    try:
        data = core.oot_excel(code, test_type, year=year)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Excel 생성 실패: {e}")
    from fastapi import Response
    ytag = f"_{year}" if (year and year != "전체") else ""
    fn = f"OOT_리포트_{code}{ytag}.xlsx"
    quoted = urllib.parse.quote(fn)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"})


# ── 안정성 ────────────────────────────────────────────────────────────────────
@app.get("/api/stability/products")
def api_stab_products(test_type: str = Query("시판후 안정성시험(Ongoing Stability)")):
    try:
        return {"testType": test_type, "testTypes": core.stab_test_types(),
                "products": core.oot_products(test_type)}
    except Exception as e:
        raise HTTPException(502, f"품목 목록 로드 실패: {e}")


@app.get("/api/stability")
def api_stability(code: str,
                  test_type: str = Query("시판후 안정성시험(Ongoing Stability)"),
                  spec_low: float = 90.0, spec_high: float = 150.0,
                  method: str = "pooled", test_item: Optional[str] = None,
                  batch: Optional[str] = None):
    try:
        return core.stability_analysis(code, test_type, spec_low, spec_high, method, test_item, batch)
    except Exception as e:
        raise HTTPException(502, f"안정성 분석 실패: {e}")


@app.get("/api/stability/tables")
def api_stability_tables(code: str,
                         test_type: str = Query("시판후 안정성시험(Ongoing Stability)"),
                         spec_low: float = 90.0, spec_high: float = 150.0,
                         batch: Optional[str] = None):
    """전 시험항목 두 방식 비교표·요약·원자료."""
    try:
        return core.stability_tables(code, test_type, spec_low, spec_high, batch)
    except Exception as e:
        raise HTTPException(502, f"표 생성 실패: {e}")


@app.get("/api/stability/excel")
def api_stability_excel(code: str,
                        test_type: str = Query("시판후 안정성시험(Ongoing Stability)"),
                        spec_low: float = 90.0, spec_high: float = 150.0,
                        batch: Optional[str] = None):
    """안정성 분석결과 Excel(.xlsx) 다운로드."""
    try:
        data = core.stability_excel(code, test_type, spec_low, spec_high, batch)
    except Exception as e:
        raise HTTPException(502, f"Excel 생성 실패: {e}")
    from fastapi import Response
    fn = f"안정성_분석결과_{code}.xlsx"
    quoted = urllib.parse.quote(fn)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"})


# ── 동일품목군 (APQR 풀링 OOT) ────────────────────────────────────────────────
class GroupSaveBody(BaseModel):
    group_id: str = ""
    group_name: str = ""
    member_codes: list[str] = []


class GroupPooledBody(BaseModel):
    codes: list[str] = []
    test_type: str = "완제품"
    test_item: str = ""
    group_id: str = ""
    year: str = ""


class GroupIdBody(BaseModel):
    group_id: str = ""


def _group_dict(g) -> dict:
    from dataclasses import asdict
    return asdict(g)


@app.get("/api/group/items")
def api_group_items(test_type: str = Query("완제품"), q: str = Query(""),
                    codes: str = Query(""), year: Optional[str] = None):
    """카탈로그(+q 유사도 후보) + 시험종류 목록. codes 주면 해당 코드들의 시험항목 목록도(연도 반영)."""
    try:
        catalog = core.group_catalog(test_type)
        out = {"testType": test_type, "testTypes": core.oot_test_types(), "catalog": catalog}
        if q.strip():
            cands = oot_group.search_similar_items(q.strip(), catalog, top_n=12)
            out["candidates"] = [{"품목코드": c.품목코드, "품목명": c.품목명, "유사도": c.유사도} for c in cands]
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        if code_list:
            out["testItems"] = core.group_test_items(code_list, test_type, year=year)
            out["years"] = core.group_years(code_list, test_type)
        return out
    except Exception as e:
        raise HTTPException(502, f"품목 목록 로드 실패: {e}")


@app.get("/api/group/list")
def api_group_list():
    """저장된 동일품목군 목록."""
    return {"groups": [_group_dict(g) for g in _GROUPS.list_groups()]}


@app.post("/api/group")
def api_group_save(body: GroupSaveBody):
    """동일품목군 저장."""
    gid = (body.group_id or body.group_name or "").strip()
    if not gid:
        raise HTTPException(400, "그룹 이름(또는 ID)이 필요합니다.")
    codes = [str(c).strip() for c in body.member_codes if str(c).strip()]
    if not codes:
        raise HTTPException(400, "구성 품목코드가 필요합니다.")
    g = _GROUPS.save_group(gid, (body.group_name or gid).strip(), codes)
    return {"ok": True, "group": _group_dict(g),
            "groups": [_group_dict(x) for x in _GROUPS.list_groups()]}


@app.post("/api/group/delete")
def api_group_delete(body: GroupIdBody):
    """동일품목군 삭제."""
    ok = _GROUPS.delete_group((body.group_id or "").strip())
    return {"ok": ok, "groups": [_group_dict(g) for g in _GROUPS.list_groups()]}


@app.post("/api/group/pooled")
def api_group_pooled(body: GroupPooledBody):
    """선택 품목코드들을 풀링해 관리도·OOT를 산출(연도 필터 반영)."""
    codes = [str(c).strip() for c in body.codes if str(c).strip()]
    if not codes:
        raise HTTPException(400, "구성 품목코드가 필요합니다.")
    if not body.test_item.strip():
        raise HTTPException(400, "시험항목이 필요합니다.")
    try:
        return core.group_pooled(codes, body.test_type, body.test_item.strip(),
                                 group_id=body.group_id, year=(body.year or None))
    except ValueError as e:
        raise HTTPException(400, str(e))          # 유효 레코드 <2건 등
    except Exception as e:
        raise HTTPException(502, f"풀링 집계 실패: {e}")


@app.post("/api/group/pooled_all")
def api_group_pooled_all(body: GroupPooledBody):
    """선택 품목코드들의 **모든 시험항목**을 한 번에 풀링(APQR 전체 관점)."""
    codes = [str(c).strip() for c in body.codes if str(c).strip()]
    if not codes:
        raise HTTPException(400, "구성 품목코드가 필요합니다.")
    try:
        return core.group_pooled_all(codes, body.test_type, year=(body.year or None))
    except Exception as e:
        raise HTTPException(502, f"풀링 집계 실패: {e}")


@app.get("/api/group/excel")
def api_group_excel(codes: str = Query(""), test_type: str = Query("완제품"),
                    year: Optional[str] = None):
    """APQR 풀링(연도 필터 반영) → 첨부 양식 엑셀(.xlsx), 전 시험항목 시트 다운로드."""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        raise HTTPException(400, "구성 품목코드가 필요합니다.")
    try:
        data = core.group_excel(code_list, test_type, year=year)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Excel 생성 실패: {e}")
    from fastapi import Response
    ytag = f"_{year}" if (year and year != "전체") else ""
    fn = f"APQR_리포트{ytag}.xlsx"
    quoted = urllib.parse.quote(fn)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"})


# ── 알림 설정 ──────────────────────────────────────────────────────────────────
def _load_prefs() -> dict:
    return storage_io.read_json(_ALARM_PREFS, default={}) or {}


class AlarmConfig(BaseModel):
    policy: str = "관리이탈만"
    recipients: list[str] = []
    interval: str = "10분"
    night: bool = True
    schedule: Optional[dict] = None  # {"mode": "daily"|"interval", "daily_time": "HH:MM", "interval_min": int}


_DEFAULT_SCHEDULE = {"mode": "daily", "daily_time": "07:30", "interval_min": 10}


def _normalize_schedule(s: Optional[dict]) -> dict:
    """알람 스케줄 값 검증·정규화(oot_alarm.py 가 읽는 형식)."""
    s = dict(s or {})
    mode = "interval" if str(s.get("mode", "daily")).lower() == "interval" else "daily"
    t = str(s.get("daily_time") or _DEFAULT_SCHEDULE["daily_time"]).strip()
    try:
        hh, mm = [int(x) for x in t.split(":")[:2]]
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
        t = f"{hh:02d}:{mm:02d}"
    except ValueError:
        raise HTTPException(400, "실행 시각 형식 오류(HH:MM, 예: 07:30)")
    try:
        iv = int(s.get("interval_min") or _DEFAULT_SCHEDULE["interval_min"])
    except (TypeError, ValueError):
        raise HTTPException(400, "주기(분)는 숫자여야 합니다.")
    if not (1 <= iv <= 1440):
        raise HTTPException(400, "주기(분)는 1~1440 사이여야 합니다.")
    return {"mode": mode, "daily_time": t, "interval_min": iv}


def _schedule_label(s: dict) -> str:
    return f"매일 {s['daily_time']}" if s.get("mode") == "daily" else f"{s['interval_min']}분 주기"


@app.get("/api/alarm/config")
def api_alarm_get():
    cfg = oot_mail.load_config()
    prefs = _load_prefs()
    sched = {**_DEFAULT_SCHEDULE, **(cfg.get("schedule") or {})}
    return {
        "policy": cfg.get("policy", "관리이탈만"),
        "recipients": cfg.get("recipients", []),
        # interval: 실제 알람 스케줄(oot_alert_config.json 의 schedule)을 표시용 문자열로
        "interval": _schedule_label(sched),
        "schedule": sched,
        "night": prefs.get("night", True),
    }


@app.post("/api/alarm/config")
def api_alarm_set(body: AlarmConfig):
    # 정책만 oot_alert_config.json 에 저장. 수신자(recipients/recipient_groups)는
    # /api/recipients/groups 가 관리하므로 여기서 건드리지 않는다.
    cfg = oot_mail.load_config()
    cfg["policy"] = body.policy
    # 실행 스케줄은 알람(oot_alarm.py)이 읽는 oot_alert_config.json 의 schedule 에 저장
    if body.schedule is not None:
        cfg["schedule"] = _normalize_schedule(body.schedule)
    oot_mail.save_config(cfg)
    # 야간발송은 웹 환경설정(side json)에 저장
    storage_io.write_json(_ALARM_PREFS, {"night": body.night})
    sched = {**_DEFAULT_SCHEDULE, **(cfg.get("schedule") or {})}
    return {"ok": True, "schedule": sched, "interval": _schedule_label(sched),
            "note": "실행 스케줄은 실행 중인 알람에 1분 이내 자동 반영됩니다."}


_ALARM_LOG = os.path.join(_HERE, "oot_alarm.log")


def _classify_alarm_line(msg: str) -> tuple[str, str, int]:
    """oot_alarm.log 한 줄 → (종류, 시험종류, 건수).
    종류: sent 발송성공 / fail 발송실패 / skip 발송생략 / error 오류 / detect 신규감지 / check 신규없음 / system 기타"""
    import re
    m = re.search(r"\[([^\]]+)\]\s*(\d+)건\s*→\s*\d+명 발송 성공", msg)
    if m:
        return "sent", m.group(1), int(m.group(2))
    m = re.search(r"\[([^\]]+)\]\s*발송 실패", msg)
    if m:
        return "fail", m.group(1), 0
    m = re.search(r"\[([^\]]+)\]\s*수신 그룹 미지정\s*—\s*(\d+)건", msg)
    if m:
        return "skip", m.group(1), int(m.group(2))
    m = re.search(r"신규 OOT\s*(\d+)건 감지", msg)
    if m:
        return "detect", "", int(m.group(1))
    if "신규 OOT 없음" in msg:
        return "check", "", 0
    if any(k in msg for k in ("인증 실패", "점검 오류", "확보 실패", "확보 중 예외", "로드 실패")):
        return "error", "", 0
    # "데이터 비어있음(extract 갱신 중)" 등은 정상적인 건너뜀 → system
    return "system", "", 0


@app.get("/api/alarm/history")
def api_alarm_history(days: int = Query(30, ge=0, le=3650), limit: int = Query(3000, ge=100, le=20000)):
    """알림설정 화면 이력 패널용 — 메일 발송 이력(oot_alarm_sent.csv) + 알람 실행 로그(oot_alarm.log).
    days=0 이면 전체 기간. 로그는 최신순 limit 줄까지."""
    import csv as _csv
    import re
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.now() - _td(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days else ""

    sent: list[dict] = []
    path = getattr(oot_mail, "SENT_LOG_PATH", os.path.join(_HERE, "oot_alarm_sent.csv"))
    sent_text = storage_io.read_text(path, encoding="utf-8-sig")
    if sent_text:
        import io as _io
        for r in _csv.DictReader(_io.StringIO(sent_text)):
            t = (r.get("발송일시") or "").strip()
            if not t or (cutoff and t < cutoff):
                continue
            sent.append({
                "time": t, "id": r.get("알림ID", ""), "testType": r.get("시험종류", ""),
                "product": r.get("품목", ""), "code": r.get("품목코드", ""), "lot": r.get("제조번호", ""),
                "item": r.get("시험항목", ""), "value": r.get("결과값", ""), "mean": r.get("평균", ""),
                "sd": r.get("표준편차", ""), "cls": r.get("분류", ""),
                "recipients": [e.strip() for e in (r.get("수신자") or "").split(";") if e.strip()],
            })
    sent.sort(key=lambda x: x["time"], reverse=True)

    events: list[dict] = []
    # 요약 집계는 반환 줄 수(limit)와 무관하게 기간 전체로: counts[종류][시험종류] = 발생 횟수
    counts: dict[str, dict[str, int]] = {}
    total, tts_log, last_check = 0, set(), ""
    if os.path.exists(_ALARM_LOG):
        with open(_ALARM_LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        pat = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)$")
        for ln in reversed(lines):
            m = pat.match(ln.rstrip("\r\n"))
            if not m:
                continue
            t, msg = m.group(1), m.group(2).strip()
            if cutoff and t < cutoff:
                break  # 로그는 시간순 누적 → 역순 탐색 중 기간 밖이면 종료
            kind, tt, cnt = _classify_alarm_line(msg)
            total += 1
            counts.setdefault(kind, {})
            counts[kind][tt] = counts[kind].get(tt, 0) + 1
            if tt:
                tts_log.add(tt)
            if not last_check and kind in ("detect", "check"):
                last_check = t
            if len(events) < limit:
                events.append({"time": t, "kind": kind, "testType": tt, "count": cnt, "text": msg})

    tts = sorted({s["testType"] for s in sent if s["testType"]} | tts_log)
    return {"days": days, "sent": sent, "events": events, "eventsTotal": total,
            "eventsTruncated": total > len(events), "counts": counts, "testTypes": tts,
            "lastCheck": last_check, "lastSent": sent[0]["time"] if sent else ""}


class AuthBody(BaseModel):
    password: str = ""


class PwChange(BaseModel):
    current: str = ""
    new: str = ""


@app.post("/api/alarm/auth")
def api_alarm_auth(body: AuthBody):
    """알림설정 진입 비밀번호 확인."""
    return {"ok": oot_mail.check_password(body.password),
            "fromEnv": oot_mail.password_from_env()}


@app.post("/api/alarm/password")
def api_alarm_password(body: PwChange):
    """비밀번호 변경 — 현재 비번 확인 후 config에 새 해시 저장."""
    if oot_mail.password_from_env():
        return {"ok": False, "msg": "비밀번호가 .env(OOT_ALERT_PASSWORD)로 고정되어 화면 변경이 불가합니다."}
    if not oot_mail.check_password(body.current):
        return {"ok": False, "msg": "현재 비밀번호가 일치하지 않습니다."}
    if len(body.new.strip()) < 4:
        return {"ok": False, "msg": "새 비밀번호는 4자 이상이어야 합니다."}
    cfg = oot_mail.load_config()
    cfg["password_hash"] = oot_mail.hash_password(body.new.strip())
    oot_mail.save_config(cfg)
    return {"ok": True, "msg": "비밀번호가 변경되었습니다."}


def _all_group_emails() -> list[str]:
    """전 시험종류 그룹 이메일 합집합(중복 제거, 순서 보존)."""
    groups = oot_mail.load_config().get("recipient_groups") or {}
    seen, out = set(), []
    for emails in groups.values():
        for e in (emails or []):
            e = str(e).strip()
            if e and e.lower() not in seen:
                seen.add(e.lower())
                out.append(e)
    return out


@app.post("/api/alarm/test")
def api_alarm_test():
    """테스트 메일 1건 발송(연동 확인) — 전 그룹 수신자 합집합으로."""
    to = _all_group_emails()
    if not to:
        return {"ok": False, "msg": "수신 그룹에 등록된 수신자가 없습니다(시험종류별 그룹을 먼저 저장하세요)."}
    dummy = [{"시험종류": "완제품", "품목": "(테스트)", "품목코드": "00000", "제조번호": "TEST-LOT",
              "시험항목": "테스트 항목", "결과값": "999", "분류": "관리이탈 (±3σ 초과)",
              "평균": "100", "표준편차": "10"}]
    ok, msg = oot_mail.send_oot_alert(dummy, subject="[OOT 테스트] 알림 발송 확인",
                                      dashboard_url=os.getenv("OOT_DASHBOARD_URL", ""), recipients=to)
    return {"ok": ok, "msg": msg}


# ── 수신자 마스터 DB ───────────────────────────────────────────────────────────
class RecipientBody(BaseModel):
    name: str = ""
    email: str = ""


class EmailBody(BaseModel):
    email: str = ""


class GroupsBody(BaseModel):
    groups: dict = {}


@app.get("/api/recipients")
def api_recipients_list():
    """수신자 마스터 DB(이름+이메일) 목록."""
    return {"recipients": recipients_db.load_db()}


@app.post("/api/recipients")
def api_recipients_add(body: RecipientBody):
    """수동 추가/갱신 → DB 병합."""
    ok, msg, db = recipients_db.add_recipient(body.name, body.email)
    return {"ok": ok, "msg": msg, "recipients": db}


@app.post("/api/recipients/delete")
def api_recipients_delete(body: EmailBody):
    """DB에서 제거. 제거된 이메일은 모든 시험종류 그룹에서도 제외."""
    db = recipients_db.remove_recipient(body.email)
    cfg = oot_mail.load_config()
    groups = cfg.get("recipient_groups") or {}
    em = str(body.email).strip().lower()
    for tt in list(groups.keys()):
        groups[tt] = [e for e in (groups[tt] or []) if str(e).strip().lower() != em]
    cfg["recipient_groups"] = groups
    cfg["recipients"] = _union_of(groups)
    oot_mail.save_config(cfg)
    return {"ok": True, "recipients": db}


# ── 시험종류별 수신 그룹 ──────────────────────────────────────────────────────
def _union_of(groups: dict) -> list[str]:
    seen, out = set(), []
    for emails in (groups or {}).values():
        for e in (emails or []):
            e = str(e).strip()
            if e and e.lower() not in seen:
                seen.add(e.lower()); out.append(e)
    return out


@app.get("/api/recipients/groups")
def api_groups_get():
    """시험종류별 수신 그룹 + 시험종류 목록 + 마스터 DB."""
    cfg = oot_mail.load_config()
    return {"groups": cfg.get("recipient_groups") or {},
            "testTypes": core.oot_test_types(),
            "recipients": recipients_db.load_db()}


@app.post("/api/recipients/groups")
def api_groups_set(body: GroupsBody):
    """시험종류별 그룹 저장 + recipients(합집합) 동기화."""
    # DB에 존재하는 이메일만 허용(정합성)
    valid = {r["email"].strip().lower() for r in recipients_db.load_db()}
    clean = {}
    for tt, emails in (body.groups or {}).items():
        kept = [str(e).strip() for e in (emails or []) if str(e).strip().lower() in valid]
        if kept:
            clean[tt] = kept
    cfg = oot_mail.load_config()
    cfg["recipient_groups"] = clean
    cfg["recipients"] = _union_of(clean)
    oot_mail.save_config(cfg)
    return {"ok": True, "groups": clean}


_REFRESH_MIN_SEC = 600                      # 새로고침은 10분에 한 번(작은 웨어하우스 보호)
_refresh_lock = threading.Lock()
_refresh_last: dict = {"t": None}


@app.post("/api/refresh")
def api_refresh():
    """데이터 캐시 무효화('데이터 새로고침') — 다음 조회는 Databricks에서 새로 가져옴.
    10분 안에 다시 부르면 비우지 않고 skipped=true 로 답한다(화면 버튼은 그대로 동작)."""
    with _refresh_lock:
        now, last = time.monotonic(), _refresh_last["t"]
        if last is not None and now - last < _REFRESH_MIN_SEC:
            return {"ok": True, "cleared": 0, "skipped": True,
                    "reason": "10분 안에 다시 눌러 새로 받지 않고 임시 저장분을 씁니다.",
                    "retryAfterSec": int(_REFRESH_MIN_SEC - (now - last)) + 1}
        _refresh_last["t"] = now
    n = core.clear_data_cache()
    return {"ok": True, "cleared": n, "skipped": False}


# ── OOT 넘김 파일(우리 검토 도구가 받아 감) ──────────────────────────────────
# 머리말 X-OOT-Export-Key 를 전용 환경값 OOT_EXPORT_KEY 와 비교한다(API_KEY 는 쓰지 않음).
# 값이 없으면 503(닫힘), 틀리면 401. 비교는 시간차가 새지 않게, 오류 글에 열쇠를 넣지 않는다.
# 계산은 oot_export 가 자식 프로세스로 한다 — 여기서는 얇게 연결만.
_EXPORT_ID = re.compile(r"[0-9a-f]{12}")


def _require_export_key(x_oot_export_key: Optional[str] = Header(None)) -> None:
    want = os.environ.get("OOT_EXPORT_KEY", "")
    if not want:
        raise HTTPException(503, "넘김 주소가 아직 열리지 않았습니다(열쇠 미설정).")
    got = (x_oot_export_key or "").encode("utf-8")
    if not hmac.compare_digest(got, want.encode("utf-8")):
        raise HTTPException(401, "열쇠가 맞지 않습니다.")


@app.get("/api/oot/export/latest", dependencies=[Depends(_require_export_key)])
def api_oot_export_latest():
    """현재 머리표 + 마지막 시도 상태(last_attempt). 판이 아직 없으면 404 와 마지막 시도 상태."""
    try:
        meta, attempt = oot_export.read_latest()
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    if meta is None:
        return JSONResponse({"detail": "아직 넘김 파일이 없습니다.", "last_attempt": attempt}, status_code=404)
    return {**meta, "last_attempt": attempt}


@app.get("/api/oot/export/{export_id}/rows.jsonl.gz", dependencies=[Depends(_require_export_key)])
def api_oot_export_rows(export_id: str):
    """줄 파일(gzip JSON Lines). 판 id 는 12자리 16진수만."""
    if not _EXPORT_ID.fullmatch(export_id):
        raise HTTPException(404, "없는 판입니다.")
    try:
        data = oot_export.read_rows(export_id)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    if data is None:
        raise HTTPException(404, "없는 판입니다.")
    return Response(content=data, media_type="application/gzip")


@app.post("/api/oot/export/run", dependencies=[Depends(_require_export_key)])
def api_oot_export_run():
    """넘김 파일 만들기를 자식 프로세스로 띄운다. 이미 도는 중이면 state='running'."""
    try:
        return {"state": oot_export.start_child()}
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@app.on_event("startup")
def _startup_prewarm():
    """기동 시 완제품 품목목록을 백그라운드로 미리 캐시(첫 조회 대기 제거)."""
    threading.Thread(target=core.prewarm, daemon=True).start()


@app.on_event("startup")
def _startup_export_schedule():
    """넘김 파일 일정 흐름(03:45 KST 이후 하루 한 번).
    보관함이 S3(axhub 에 올라간 앱)이거나 열쇠(OOT_EXPORT_KEY, 디스크 모드 개발용)가 있으면 띄운다.
    끄는 스위치 OOT_EXPORT_OFF=1 이면 어느 경우든 띄우지 않는다."""
    mode = storage_io.export_mode()
    if os.environ.get("OOT_EXPORT_OFF") == "1":
        on, why = False, "끄는 스위치(OOT_EXPORT_OFF=1)가 켜져 있음"
    elif mode == "s3":
        on, why = True, "보관함(S3)에 연결됨"
    elif os.environ.get("OOT_EXPORT_KEY"):
        on, why = True, "열쇠가 있음(디스크 모드 개발용)"
    elif mode == "s3-broken":
        on, why = False, "보관함(S3) 설정은 있으나 연결 준비에 실패함"
    else:
        on, why = False, "보관함이 S3 가 아니고 열쇠도 없음"
    print(f"넘김 파일 일정: {'켬' if on else '끔'} — {why}", flush=True)
    if on:
        threading.Thread(target=oot_export.scheduler_loop, daemon=True).start()


@app.get("/api/health")
def api_health():
    return {"ok": True, "service": "kwangdong-dashboard"}


# ── 정적 프론트엔드 (반드시 API 라우트 뒤에 마운트) ─────────────────────────────
if os.path.isdir(_WEBAPP):
    # index.html은 캐시 금지 → 새 배포(app.js?v=…) 즉시 반영, 브라우저 하드새로고침 불필요.
    @app.get("/")
    def _index():
        return FileResponse(
            os.path.join(_WEBAPP, "index.html"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                     "Pragma": "no-cache", "Expires": "0"},
        )

    app.mount("/", StaticFiles(directory=_WEBAPP, html=True), name="webapp")
else:
    @app.get("/")
    def _no_webapp():
        return JSONResponse({"error": "webapp/ 폴더가 없습니다."}, status_code=500)
