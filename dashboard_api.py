# -*- coding: utf-8 -*-
"""
dashboard_api.py — 광동 품질·시험 통합 대시보드 백엔드(FastAPI).

webapp/ 정적 프론트엔드를 서빙하고, OOT/안정성/알림 JSON API를 제공한다.
데이터·분석은 kdp_core, 알림 설정은 oot_mail 을 재사용한다.

실행:  python -m uvicorn dashboard_api:app --host 0.0.0.0 --port 8600
"""
from __future__ import annotations

import json
import os
import urllib.parse
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import kdp_core as core
import oot_mail

_HERE = os.path.dirname(os.path.abspath(__file__))
_WEBAPP = os.path.join(_HERE, "webapp")
_ALARM_PREFS = os.path.join(_HERE, ".webapp_alarm.json")

app = FastAPI(title="광동 품질·시험 통합 대시보드 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── OOT ──────────────────────────────────────────────────────────────────────
@app.get("/api/oot/products")
def api_oot_products(test_type: str = Query("완제품")):
    try:
        return {"testType": test_type, "testTypes": core.OOT_TEST_TYPES,
                "products": core.oot_products(test_type)}
    except Exception as e:
        raise HTTPException(502, f"품목 목록 로드 실패: {e}")


@app.get("/api/oot/lots")
def api_oot_lots(code: str, test_type: str = Query("완제품")):
    try:
        return core.oot_lot_summary(code, test_type)
    except Exception as e:
        raise HTTPException(502, f"LOT 데이터 로드 실패: {e}")


# ── 안정성 ────────────────────────────────────────────────────────────────────
@app.get("/api/stability/products")
def api_stab_products(test_type: str = Query("시판후 안정성시험(Ongoing Stability)")):
    try:
        return {"testType": test_type, "testTypes": core.STAB_TEST_TYPES,
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


# ── 알림 설정 ──────────────────────────────────────────────────────────────────
def _load_prefs() -> dict:
    if os.path.exists(_ALARM_PREFS):
        try:
            with open(_ALARM_PREFS, encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}
    return {}


class AlarmConfig(BaseModel):
    policy: str = "관리이탈만"
    recipients: list[str] = []
    interval: str = "10분"
    night: bool = True


@app.get("/api/alarm/config")
def api_alarm_get():
    cfg = oot_mail.load_config()
    prefs = _load_prefs()
    return {
        "policy": cfg.get("policy", "관리이탈만"),
        "recipients": cfg.get("recipients", []),
        "interval": prefs.get("interval", f'{os.getenv("OOT_ALARM_INTERVAL_MIN", "10")}분'),
        "night": prefs.get("night", True),
    }


@app.post("/api/alarm/config")
def api_alarm_set(body: AlarmConfig):
    # 정책·수신자는 스케줄러가 쓰는 oot_alert_config.json 에 저장(기존 로직 재사용)
    cfg = oot_mail.load_config()
    cfg["policy"] = body.policy
    cfg["recipients"] = [r.strip() for r in body.recipients if r.strip()]
    oot_mail.save_config(cfg)
    # 주기·야간발송은 웹 환경설정(side json)에 저장
    with open(_ALARM_PREFS, "w", encoding="utf-8") as f:
        json.dump({"interval": body.interval, "night": body.night}, f, ensure_ascii=False, indent=2)
    return {"ok": True}


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


@app.post("/api/alarm/test")
def api_alarm_test():
    """테스트 메일 1건 발송(연동 확인)."""
    dummy = [{"시험종류": "완제품", "품목": "(테스트)", "품목코드": "00000", "제조번호": "TEST-LOT",
              "시험항목": "테스트 항목", "결과값": "999", "분류": "관리이탈 (±3σ 초과)",
              "평균": "100", "표준편차": "10"}]
    ok, msg = oot_mail.send_oot_alert(dummy, subject="[OOT 테스트] 알림 발송 확인",
                                      dashboard_url=os.getenv("OOT_DASHBOARD_URL", ""))
    return {"ok": ok, "msg": msg}


@app.get("/api/health")
def api_health():
    return {"ok": True, "service": "kwangdong-dashboard"}


# ── 정적 프론트엔드 (반드시 API 라우트 뒤에 마운트) ─────────────────────────────
if os.path.isdir(_WEBAPP):
    app.mount("/", StaticFiles(directory=_WEBAPP, html=True), name="webapp")
else:
    @app.get("/")
    def _no_webapp():
        return JSONResponse({"error": "webapp/ 폴더가 없습니다."}, status_code=500)
