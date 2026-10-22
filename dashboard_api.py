# -*- coding: utf-8 -*-
"""
dashboard_api.py — 광동 품질·시험 통합 대시보드 백엔드(FastAPI).

webapp/ 정적 프론트엔드를 서빙하고, OOT/안정성/알림 JSON API를 제공한다.
데이터·분석은 kdp_core, 알림 설정은 oot_mail 을 재사용한다.

실행:  python -m uvicorn dashboard_api:app --host 0.0.0.0 --port 8502
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import kdp_core as core  # databricks_client(인증서 주입)를 보관함·메일 모듈보다 먼저
import axhub_mail
import kst
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


@app.middleware("http")
async def _remember_user(request, call_next):
    """플랫폼 메일 수신자 사전 — 들어온 사람의 SSO 머리말(사용자 ID·이메일)을 기억한다(실패 무시)."""
    try:
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(axhub_mail.remember_from_headers, dict(request.headers))   # 보관함 입출력이 이벤트 루프를 막지 않게
    except Exception:
        pass
    return await call_next(request)


_URL_RE = re.compile(r"https?://\S+")        # 서명 주소 등 — 로그·응답에 남기지 않는다


@app.exception_handler(storage_io.StorageReadError)
async def _storage_read_error(request, exc):
    """보관함을 읽지 못하면 저장·발송을 멈추고 503 — 빈 값으로 보고 덮어쓰지 않는다."""
    return JSONResponse({"detail": "보관함을 읽지 못했습니다. 잠시 뒤 다시 시도하세요(저장하지 않았습니다)."},
                        status_code=503)


def _fail(e: Exception, msg: str):
    """502 — 응답에는 일반 문구만, 자세한 까닭은 서버 로그에(주소는 가림). 내부 SQL·표 이름이 새지 않게."""
    detail = _URL_RE.sub("[주소 생략]", str(e))[:500]
    print(f"[오류] {msg}: {type(e).__name__}: {detail}", flush=True)
    raise HTTPException(502, f"{msg}. 잠시 뒤 다시 시도하고, 계속되면 관리자에게 알려 주세요.")


def _refresh_directory(request, force: bool = False) -> str:
    """알림설정 화면을 연 관리자의 로그인으로 앱 멤버 목록을 읽어 수신자 사전을 채운다."""
    try:
        return axhub_mail.refresh_from_members(request.cookies.get("_hub_access", ""), force=force)[1]
    except Exception as e:  # noqa: BLE001
        return f"멤버 목록 확인 실패({type(e).__name__})"


def _mail_status(emails: list[str]) -> dict:
    """메일 발송 상태 — 개수만(이메일 주소는 응답에 넣지 않는다)."""
    ids, missing = axhub_mail.resolve(emails)
    return {"transport": axhub_mail.transport_name(), "resolved": len(ids), "unresolved": len(missing)}


# ── 알림설정 관리자 확인(서버측) ─────────────────────────────────────────────
# 화면의 비밀번호 잠금만으로는 API 가 보호되지 않는다. 수신자 명단(직원 이메일)·설정 변경·테스트 발송은
# 서버에서 확인한다: ① axhub 로그인 역할이 앱 소유자·회사 관리자(게이트가 넣는 X-AxHub-App-Role — 밖에서
# 보낸 값은 게이트가 덮어씀) 이거나 ② 비밀번호 확인으로 받은 관리자 토큰(X-OOT-Admin, 8시간)이 있을 때.
_ADMIN_ROLES = {"owner", "tenant_admin", "platform_admin"}
_ADMIN_TTL = 8 * 3600
_admin_tokens: dict[str, float] = {}
_auth_fails: dict[str, list[float]] = {}
_AUTH_WINDOW, _AUTH_MAX_FAILS = 600, 5          # 10분에 5번 틀리면 잠시 막음(대입 방지)


def _is_admin(request) -> bool:
    role = (request.headers.get("x-axhub-app-role") or "").strip().lower()
    if role in _ADMIN_ROLES and axhub_mail.behind_gate():     # 로컬 실행에서는 머리말을 믿지 않는다
        return True
    tok = request.headers.get("x-oot-admin") or ""
    exp = _admin_tokens.get(tok) if tok else None
    if exp and exp > time.time():
        return True
    if exp:
        _admin_tokens.pop(tok, None)
    return False


def _require_admin(request) -> None:
    if not _is_admin(request):
        raise HTTPException(403, "알림설정 관리자 확인이 필요합니다(알림설정에서 비밀번호를 입력하세요).")


def _auth_key(request) -> str:
    return (request.headers.get("x-axhub-user-id") or "").strip() or (request.client.host if request.client else "?")


def _auth_blocked(key: str) -> bool:
    now = time.time()
    recent = [t for t in _auth_fails.get(key, []) if now - t < _AUTH_WINDOW]
    _auth_fails[key] = recent
    return len(recent) >= _AUTH_MAX_FAILS


def _auth_failed(key: str) -> None:
    _auth_fails.setdefault(key, []).append(time.time())


def _issue_admin_token() -> str:
    now = time.time()
    for t, exp in list(_admin_tokens.items()):     # 만료분 정리
        if exp <= now:
            _admin_tokens.pop(t, None)
    tok = secrets.token_urlsafe(32)
    _admin_tokens[tok] = now + _ADMIN_TTL
    return tok


def _mask_email(e: str) -> str:
    """k***@ekdp.com — 관리자가 아닌 사람에게 보이는 발송 이력의 수신자 표시."""
    e = str(e or "").strip()
    if "@" not in e:
        return "***"
    local, dom = e.split("@", 1)
    return (local[:1] or "*") + "***@" + dom


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _mask_emails_in(text: str) -> str:
    """글 안의 이메일을 모두 가린다(예전 로그·SMTP 오류 글에 남은 주소)."""
    return _EMAIL_RE.sub(lambda m: _mask_email(m.group(0)), str(text or ""))


# ── OOT ──────────────────────────────────────────────────────────────────────
@app.get("/api/oot/products")
def api_oot_products(test_type: str = Query("완제품")):
    try:
        return {"testType": test_type, "testTypes": core.oot_test_types(),
                "products": core.oot_products(test_type)}
    except Exception as e:
        _fail(e, "품목 목록 로드 실패")


@app.get("/api/oot/lots")
def api_oot_lots(code: str, test_type: str = Query("완제품"), year: Optional[str] = None):
    try:
        return core.oot_lot_summary(code, test_type, year=year)
    except Exception as e:
        _fail(e, "LOT 데이터 로드 실패")


@app.get("/api/oot/excel")
def api_oot_excel(code: str, test_type: str = Query("완제품"), year: Optional[str] = None):
    """OOT 조회(연도 필터 반영) → 첨부 양식 엑셀(.xlsx) 다운로드."""
    try:
        data = core.oot_excel(code, test_type, year=year)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        _fail(e, "Excel 생성 실패")
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
        _fail(e, "품목 목록 로드 실패")


@app.get("/api/stability")
def api_stability(code: str,
                  test_type: str = Query("시판후 안정성시험(Ongoing Stability)"),
                  spec_low: float = 90.0, spec_high: float = 150.0,
                  method: str = "pooled", test_item: Optional[str] = None,
                  batch: Optional[str] = None):
    try:
        return core.stability_analysis(code, test_type, spec_low, spec_high, method, test_item, batch)
    except Exception as e:
        _fail(e, "안정성 분석 실패")


@app.get("/api/stability/tables")
def api_stability_tables(code: str,
                         test_type: str = Query("시판후 안정성시험(Ongoing Stability)"),
                         spec_low: float = 90.0, spec_high: float = 150.0,
                         batch: Optional[str] = None):
    """전 시험항목 두 방식 비교표·요약·원자료."""
    try:
        return core.stability_tables(code, test_type, spec_low, spec_high, batch)
    except Exception as e:
        _fail(e, "표 생성 실패")


@app.get("/api/stability/excel")
def api_stability_excel(code: str,
                        test_type: str = Query("시판후 안정성시험(Ongoing Stability)"),
                        spec_low: float = 90.0, spec_high: float = 150.0,
                        batch: Optional[str] = None):
    """안정성 분석결과 Excel(.xlsx) 다운로드."""
    try:
        data = core.stability_excel(code, test_type, spec_low, spec_high, batch)
    except Exception as e:
        _fail(e, "Excel 생성 실패")
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
        _fail(e, "품목 목록 로드 실패")


@app.get("/api/group/list")
def api_group_list():
    """저장된 동일품목군 목록."""
    return {"groups": [_group_dict(g) for g in _GROUPS.list_groups()]}


@app.post("/api/group")
def api_group_save(body: GroupSaveBody, request: Request):
    """동일품목군 저장 — 새로 만들기는 누구나, 기존 품목군 덮어쓰기는 관리자만."""
    gid = (body.group_id or body.group_name or "").strip()
    if not gid:
        raise HTTPException(400, "그룹 이름(또는 ID)이 필요합니다.")
    if len(gid) > 100 or len((body.group_name or "").strip()) > 100:
        raise HTTPException(400, "그룹 이름은 100자 이하여야 합니다.")
    codes = [str(c).strip() for c in body.member_codes if str(c).strip()]
    if not codes:
        raise HTTPException(400, "구성 품목코드가 필요합니다.")
    if len(codes) > 200 or any(len(c) > 30 for c in codes):
        raise HTTPException(400, "구성 품목코드는 200개 이하, 코드당 30자 이하여야 합니다.")
    if _GROUPS.load_group(gid) is not None:
        _require_admin(request)          # 남이 만든 품목군의 구성을 바꾸지 못하게
    elif len(_GROUPS.list_groups()) >= 500:
        raise HTTPException(400, "품목군은 500개까지 만들 수 있습니다.")
    g = _GROUPS.save_group(gid, (body.group_name or gid).strip(), codes)
    return {"ok": True, "group": _group_dict(g),
            "groups": [_group_dict(x) for x in _GROUPS.list_groups()]}


@app.post("/api/group/delete")
def api_group_delete(body: GroupIdBody, request: Request):
    """동일품목군 삭제 — 관리자만(저장은 누구나)."""
    _require_admin(request)
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
        _fail(e, "풀링 집계 실패")


@app.post("/api/group/pooled_all")
def api_group_pooled_all(body: GroupPooledBody):
    """선택 품목코드들의 **모든 시험항목**을 한 번에 풀링(APQR 전체 관점)."""
    codes = [str(c).strip() for c in body.codes if str(c).strip()]
    if not codes:
        raise HTTPException(400, "구성 품목코드가 필요합니다.")
    try:
        return core.group_pooled_all(codes, body.test_type, year=(body.year or None))
    except Exception as e:
        _fail(e, "풀링 집계 실패")


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
        _fail(e, "Excel 생성 실패")
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
def api_alarm_get(request: Request):
    admin = _is_admin(request)
    if admin:
        _refresh_directory(request)             # 10분에 한 번 — 수신자 사전 최신화
    cfg = oot_mail.load_config()
    prefs = _load_prefs()
    sched = {**_DEFAULT_SCHEDULE, **(cfg.get("schedule") or {})}
    return {
        "policy": cfg.get("policy", "관리이탈만"),
        "recipients": cfg.get("recipients", []) if admin else [],   # 직원 이메일은 관리자에게만
        # interval: 실제 알람 스케줄(oot_alert_config.json 의 schedule)을 표시용 문자열로
        "interval": _schedule_label(sched),
        "schedule": sched,
        "night": prefs.get("night", True),
        "mail": _mail_status(_all_group_emails()),
        "isAdmin": admin,                                  # 소유자·회사 관리자 역할이면 비밀번호 없이 진입
        "passwordSet": oot_mail.password_is_set(cfg),
    }


@app.post("/api/alarm/config")
def api_alarm_set(body: AlarmConfig, request: Request):
    _require_admin(request)
    # 정책만 oot_alert_config.json 에 저장. 수신자(recipients/recipient_groups)는
    # /api/recipients/groups 가 관리하므로 여기서 건드리지 않는다.
    cfg = oot_mail.load_config(strict=True)
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
def api_alarm_history(request: Request, days: int = Query(30, ge=0, le=3650),
                      limit: int = Query(3000, ge=100, le=20000)):
    """알림설정 화면 이력 패널용 — 메일 발송 이력(oot_alarm_sent.csv) + 알람 실행 로그(oot_alarm.log).
    days=0 이면 전체 기간. 로그는 최신순 limit 줄까지. 관리자가 아니면 수신자 이메일을 가린다."""
    admin = _is_admin(request)
    import csv as _csv
    import re
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (kst.now() - _td(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days else ""

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
                "recipients": [e if admin else _mask_email(e)          # 관리자가 아니면 가림
                               for e in (x.strip() for x in (r.get("수신자") or "").split(";")) if e],
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
                events.append({"time": t, "kind": kind, "testType": tt, "count": cnt,
                               "text": _URL_RE.sub("[주소 생략]",
                                                   msg if admin else _mask_emails_in(msg))})

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
def api_alarm_auth(body: AuthBody, request: Request):
    """알림설정 진입 비밀번호 확인 → 맞으면 관리자 토큰(8시간). 10분에 5번 틀리면 잠시 막는다."""
    key = _auth_key(request)
    if _auth_blocked(key):
        raise HTTPException(429, "비밀번호를 여러 번 틀렸습니다. 10분 뒤 다시 시도하세요.")
    if not oot_mail.password_is_set():
        return {"ok": False, "fromEnv": False,
                "msg": "비밀번호가 아직 정해지지 않았습니다. 앱 소유자가 알림설정에서 먼저 정해야 합니다."}
    if not oot_mail.check_password(body.password):
        _auth_failed(key)
        return {"ok": False, "fromEnv": oot_mail.password_from_env()}
    return {"ok": True, "fromEnv": oot_mail.password_from_env(), "token": _issue_admin_token()}


@app.post("/api/alarm/password")
def api_alarm_password(body: PwChange, request: Request):
    """비밀번호 변경 — 관리자 확인 + 현재 비번 확인 후 config에 새 해시 저장."""
    _require_admin(request)
    if oot_mail.password_from_env():
        return {"ok": False, "msg": "비밀번호가 .env(OOT_ALERT_PASSWORD)로 고정되어 화면 변경이 불가합니다."}
    key = _auth_key(request)
    if _auth_blocked(key):
        raise HTTPException(429, "비밀번호를 여러 번 틀렸습니다. 10분 뒤 다시 시도하세요.")
    # 아직 정해지지 않았으면(예전 기본값 포함) 관리자가 현재 비밀번호 없이 새로 정한다.
    if oot_mail.password_is_set() and not oot_mail.check_password(body.current):
        _auth_failed(key)
        return {"ok": False, "msg": "현재 비밀번호가 일치하지 않습니다."}
    new = body.new.strip()
    if len(new) < 8 or new.isdigit():
        return {"ok": False, "msg": "새 비밀번호는 8자 이상, 숫자만으로 만들 수 없습니다."}
    cfg = oot_mail.load_config(strict=True)
    cfg["password_hash"] = oot_mail.hash_password(new)
    _admin_tokens.clear()                     # 비밀번호가 바뀌면 이전에 발급한 토큰은 모두 무효
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
def api_alarm_test(request: Request):
    """테스트 메일 1건 발송(연동 확인) — 전 그룹 수신자 합집합으로. 관리자만."""
    _require_admin(request)
    note = _refresh_directory(request, force=True) if axhub_mail.available() else ""
    to = _all_group_emails()
    if not to:
        return {"ok": False, "msg": "수신 그룹에 등록된 수신자가 없습니다(시험종류별 그룹을 먼저 저장하세요)."}
    dummy = [{"시험종류": "완제품", "품목": "(테스트)", "품목코드": "00000", "제조번호": "TEST-LOT",
              "시험항목": "테스트 항목", "결과값": "999", "분류": "관리이탈 (±3σ 초과)",
              "평균": "100", "표준편차": "10"}]
    ok, msg = oot_mail.send_oot_alert(dummy, subject="[OOT 테스트] 알림 발송 확인",
                                      dashboard_url=os.getenv("OOT_DASHBOARD_URL", ""), recipients=to)
    msg = f"[{axhub_mail.transport_name()}] {msg}" + (f" ({note})" if note else "")
    return {"ok": ok, "msg": msg, "mail": _mail_status(to)}


# ── 수신자 마스터 DB ───────────────────────────────────────────────────────────
class RecipientBody(BaseModel):
    name: str = ""
    email: str = ""


class EmailBody(BaseModel):
    email: str = ""


class GroupsBody(BaseModel):
    groups: dict = {}


@app.get("/api/recipients")
def api_recipients_list(request: Request):
    """수신자 마스터 DB(이름+이메일) 목록. 관리자만."""
    _require_admin(request)
    return {"recipients": recipients_db.load_db()}


@app.post("/api/recipients")
def api_recipients_add(body: RecipientBody, request: Request):
    _require_admin(request)
    """수동 추가/갱신 → DB 병합."""
    ok, msg, db = recipients_db.add_recipient(body.name, body.email)
    return {"ok": ok, "msg": msg, "recipients": db}


@app.post("/api/recipients/delete")
def api_recipients_delete(body: EmailBody, request: Request):
    _require_admin(request)
    """DB에서 제거. 제거된 이메일은 모든 시험종류 그룹에서도 제외."""
    db = recipients_db.remove_recipient(body.email)
    cfg = oot_mail.load_config(strict=True)
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
def api_groups_get(request: Request):
    """시험종류별 수신 그룹 + 시험종류 목록 + 마스터 DB. 관리자만."""
    _require_admin(request)
    cfg = oot_mail.load_config()
    return {"groups": cfg.get("recipient_groups") or {},
            "testTypes": core.oot_test_types(),
            "recipients": recipients_db.load_db()}


@app.post("/api/recipients/groups")
def api_groups_set(body: GroupsBody, request: Request):
    """시험종류별 그룹 저장 + recipients(합집합) 동기화. 관리자만."""
    _require_admin(request)
    # DB에 존재하는 이메일만 허용(정합성)
    valid = {r["email"].strip().lower() for r in recipients_db.load_db()}
    clean = {}
    for tt, emails in (body.groups or {}).items():
        kept = [str(e).strip() for e in (emails or []) if str(e).strip().lower() in valid]
        if kept:
            clean[tt] = kept
    cfg = oot_mail.load_config(strict=True)
    cfg["recipient_groups"] = clean
    cfg["recipients"] = _union_of(clean)
    oot_mail.save_config(cfg)
    _refresh_directory(request)
    return {"ok": True, "groups": clean, "mail": _mail_status(_union_of(clean))}


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


# ── OOT 넘김 파일 ─────────────────────────────────────────────────────────────
# 넘김 파일은 이 앱이 보관함(oot-export/)에 만들어 둘 뿐, HTTP 로 내려주는 주소는 두지 않는다.
# (옛 /api/oot/export/* 와 고정 열쇠 OOT_EXPORT_KEY 는 쓰는 곳이 없고 사용자 인가·만료·요청 제한이
#  없어 2026-10-21 보안 점검 지적에 따라 없앴다.) 받는 앱은 보관함을 읽기 전용으로 직접 읽는다.
# 계산은 oot_export 가 자식 프로세스로 한다 — 일정 흐름(아래 startup)만 이 앱이 띄운다.


@app.on_event("startup")
def _startup_mail_mode():
    """메일 발송 길을 기동 로그에 한 줄(비밀값 없음) — 플랫폼 메일 값이 들어왔는지 확인용."""
    print(f"메일 발송 방식: {axhub_mail.transport_name()}", flush=True)


@app.on_event("startup")
def _startup_prewarm():
    """기동 시 완제품 품목목록을 백그라운드로 미리 캐시(첫 조회 대기 제거)."""
    threading.Thread(target=core.prewarm, daemon=True).start()


@app.on_event("startup")
def _startup_export_schedule():
    """넘김 파일 일정 흐름(03:45 KST 이후 하루 한 번).
    보관함이 S3(axhub 에 올라간 앱)일 때만 띄운다. 끄는 스위치 OOT_EXPORT_OFF=1 이면 띄우지 않는다."""
    mode = storage_io.export_mode()
    if os.environ.get("OOT_EXPORT_OFF") == "1":
        on, why = False, "끄는 스위치(OOT_EXPORT_OFF=1)가 켜져 있음"
    elif mode == "s3":
        on, why = True, "보관함(S3) 설정됨"
    elif mode == "s3-broken":
        on, why = False, "보관함(S3) 설정은 있으나 연결 준비에 실패함"
    else:
        on, why = False, "보관함이 S3 가 아님"
    print(f"넘김 파일 일정: {'켬' if on else '끔'} — {why}", flush=True)
    if on:
        threading.Thread(target=oot_export.scheduler_loop, daemon=True).start()


_STARTED = time.time()
_ALARM_STALE_SEC = 10 * 60      # 알람 프로세스의 별도 스레드가 30초마다 표시 — 10분 끊기면 프로세스가 죽은 것
_ALARM_GRACE_SEC = 180          # 기동 직후 유예


@app.get("/api/health")
def api_health():
    """웹 + 알람 생존. 알람 표시가 있는데 10분 넘게 갱신이 없으면 503 → 플랫폼이 컨테이너를 다시 띄운다.
    알람을 일부러 끈 환경(OOT_ALARM_OFF=1, 스테이징)·기동 직후·표시 파일이 아예 없는 경우(임시 폴더 쓰기 실패 등)는
    판단하지 않는다 — 알람 문제로 웹까지 재시작이 반복되지 않게."""
    if os.environ.get("OOT_ALARM_OFF", "").strip() != "1" and time.time() - _STARTED > _ALARM_GRACE_SEC:
        hb = os.path.join(os.environ.get("TMPDIR", "/tmp"), "oot_alarm_heartbeat")
        try:
            age = time.time() - float(open(hb, encoding="utf-8").read().strip() or 0)
        except Exception:
            age = None                   # 파일 없음·읽기 실패 → 판단 안 함
        if age is not None and age > _ALARM_STALE_SEC:
            return JSONResponse({"ok": False, "service": "kwangdong-dashboard",
                                 "alarm": "정지 또는 응답 없음"}, status_code=503)
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
