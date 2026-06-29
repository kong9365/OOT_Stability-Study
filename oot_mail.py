# -*- coding: utf-8 -*-
"""
OOT 메일 알림 — 발송 로직은 기존 QMS_Integrated_Dashboard/qms_alert.py 의
send_email() 을 그대로 재사용한다. 수신자/SMTP 설정은 알림설정 메뉴에서
oot_alert_config.json 으로 관리(없으면 QMS_* 환경변수 폴백).
"""
from __future__ import annotations

import hashlib
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_QMS_DIR = os.path.normpath(os.path.join(_HERE, "..", "QMS_Integrated_Dashboard"))
CONFIG_PATH = os.path.join(_HERE, "oot_alert_config.json")

# 설정 로드: ① 이 프로젝트 .env(독립·우선) → ② QMS .env(보조 폴백).
#   OOT_ALERT_PASSWORD(진입 비밀번호), OOT_DASHBOARD_URL, QMS_SMTP_*/QMS_ALERT_TO 등.
#   override=False → 먼저 로드된 이 프로젝트 .env 값이 우선.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(_HERE, ".env"), override=False)
    _qms_env = os.path.join(_QMS_DIR, ".env")
    if os.path.exists(_qms_env):
        _load_dotenv(_qms_env, override=False)
except Exception:
    pass

# 기존 발송 로직(send_email) 재사용 — 경로 추가 후 import
if _QMS_DIR not in sys.path:
    sys.path.insert(0, _QMS_DIR)
try:
    import qms_alert as _qms  # send_email(subject, body, to_addrs, html=, smtp_*)
except Exception:  # pragma: no cover - 폴백(모듈 못 찾을 때)
    _qms = None


def hash_password(p: str) -> str:
    return hashlib.sha256(str(p).encode("utf-8")).hexdigest()


# 알림설정 진입 비밀번호 — 이 프로젝트 .env(OOT_ALERT_PASSWORD)에서 관리. 미설정 시 기본 131103.
_INITIAL_PW = os.environ.get("OOT_ALERT_PASSWORD", "").strip() or "131103"

DEFAULT_CONFIG: dict[str, Any] = {
    "recipients": [],          # 수신자 이메일 목록
    "policy": "관리이탈만",      # "관리이탈만" | "주의+관리이탈"
    "smtp_host": "",           # 비우면 QMS_SMTP_HOST 환경변수
    "smtp_port": 587,
    "smtp_user": "",           # 비우면 QMS_SMTP_USER
    "smtp_pass": "",           # 비우면 QMS_SMTP_PASS
    "enabled": True,
    "password_hash": hash_password(_INITIAL_PW),   # 평문 미저장(sha256)
}


def check_password(p: str, cfg: dict[str, Any] | None = None) -> bool:
    # .env의 OOT_ALERT_PASSWORD가 있으면 그것이 단일 소스(독립). 없으면 config 해시.
    env_pw = os.environ.get("OOT_ALERT_PASSWORD", "").strip()
    if env_pw:
        return str(p) == env_pw
    cfg = cfg or load_config()
    return hash_password(p) == cfg.get("password_hash", hash_password(_INITIAL_PW))


def password_from_env() -> bool:
    """진입 비밀번호가 .env(OOT_ALERT_PASSWORD)로 관리되는지 여부."""
    return bool(os.environ.get("OOT_ALERT_PASSWORD", "").strip())


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
        except Exception:
            pass
    # 환경변수 폴백
    if not cfg.get("recipients"):
        env_to = os.environ.get("QMS_ALERT_TO", "")
        cfg["recipients"] = [a.strip() for a in env_to.split(",") if a.strip()]
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    """기존 파일과 병합 저장 — 부분 저장 시 미포함 키(예: password_hash) 보존."""
    existing: dict[str, Any] = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                existing = json.load(f) or {}
        except Exception:
            existing = {}
    merged = dict(DEFAULT_CONFIG)
    merged.update(existing)
    merged.update({k: v for k, v in cfg.items() if k in DEFAULT_CONFIG})
    keep = {k: merged.get(k, DEFAULT_CONFIG[k]) for k in DEFAULT_CONFIG}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False, indent=2)


def _smtp_kwargs(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "smtp_host": cfg.get("smtp_host") or os.environ.get("QMS_SMTP_HOST") or "smtp.gmail.com",
        "smtp_port": int(cfg.get("smtp_port") or os.environ.get("QMS_SMTP_PORT") or 587),
        "smtp_user": cfg.get("smtp_user") or os.environ.get("QMS_SMTP_USER") or "",
        "smtp_pass": cfg.get("smtp_pass") or os.environ.get("QMS_SMTP_PASS") or "",
    }


def _send_email_smtp(subject: str, body: str, to_addrs: list[str], html: bool = True,
                     smtp_host: str | None = None, smtp_port: int | None = None,
                     smtp_user: str | None = None, smtp_pass: str | None = None) -> bool:
    """SMTP 발송(내장) — QMS_Integrated_Dashboard/qms_alert.py 가 없는 환경(다른 노트북)에서도
    동작하도록 동일 로직을 자체 포함. STARTTLS."""
    host = smtp_host or os.environ.get("QMS_SMTP_HOST", "smtp.gmail.com")
    port = int(smtp_port or os.environ.get("QMS_SMTP_PORT", 587))
    user = smtp_user or os.environ.get("QMS_SMTP_USER", "")
    pwd = smtp_pass or os.environ.get("QMS_SMTP_PASS", "")
    if not user:
        raise ValueError("SMTP 발신 계정이 설정되지 않았습니다(QMS_SMTP_USER).")
    if not to_addrs:
        raise ValueError("수신자 주소가 없습니다.")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.ehlo()
        server.starttls()
        if pwd:
            server.login(user, pwd)
        server.sendmail(user, to_addrs, msg.as_string())
    return True


SENT_LOG_PATH = os.path.join(_HERE, "oot_alarm_sent.csv")   # 발송 이력(추적용)


def alert_id(rec: dict) -> str:
    """추적용 알림ID — (품목코드·제조번호·시험항목·분류) 안정 해시. 같은 OOT는 항상 같은 ID."""
    base = "|".join(str(rec.get(k, "")) for k in ("품목코드", "제조번호", "시험항목", "분류"))
    return "OOT-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:8].upper()


def log_sent(records: list[dict], to_addrs: list[str]) -> None:
    """발송된 건을 oot_alarm_sent.csv 에 누적 기록(감사·추적)."""
    import csv as _csv
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_new = not os.path.exists(SENT_LOG_PATH)
    with open(SENT_LOG_PATH, "a", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        if is_new:
            w.writerow(["발송일시", "알림ID", "시험종류", "품목", "품목코드", "제조번호",
                        "시험항목", "결과값", "평균", "표준편차", "분류", "수신자"])
        for r in records:
            w.writerow([now, alert_id(r), r.get("시험종류", ""), r.get("품목", ""),
                        r.get("품목코드", ""), r.get("제조번호", ""), r.get("시험항목", ""),
                        r.get("결과값", ""), r.get("평균", ""), r.get("표준편차", ""),
                        r.get("분류", ""), "; ".join(to_addrs)])


def build_oot_email_html(records: list[dict], dashboard_url: str = "", tableau_url: str = "") -> str:
    """신규 OOT 행 목록 → HTML 메일 본문. 시험종류 맨 앞, 알림ID(추적용) 맨 뒤."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = ""
    for r in records[:80]:
        st = str(r.get("분류", ""))
        is_out = ("관리이탈" in st or "초과" in st)
        color = "#b91c1c" if is_out else "#b45309"
        bg = "#fef2f2" if is_out else "#fffbeb"
        aid = alert_id(r)
        rows += f"""
        <tr style="background:{bg}">
          <td style="padding:8px 10px;border-bottom:1px solid #eee;font-weight:700">{r.get('시험종류','-')}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee">{r.get('품목','-')}<br>
              <span style="font:11px monospace;color:#888">{r.get('품목코드','')}</span></td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;font-family:monospace">{r.get('제조번호','-')}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee">{r.get('시험항목','-')}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;font-family:monospace;font-weight:700;color:{color}">{r.get('결과값','-')}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;font-family:monospace;color:#555">μ {r.get('평균','-')} / σ {r.get('표준편차','-')}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;color:{color};font-weight:600">{st}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #eee;font-family:monospace;color:#888">{aid}</td>
        </tr>"""
    links = ""
    if dashboard_url:
        links += f'<a href="{dashboard_url}" style="color:#2350a0">대시보드에서 확인</a> &nbsp;'
    if tableau_url:
        links += f'<a href="{tableau_url}/#/home" style="color:#2350a0">Tableau에서 확인</a>'
    return f"""<html><body style="font-family:Pretendard,sans-serif;color:#1a2230">
    <div style="background:#13213a;color:#fff;padding:16px 22px;border-radius:10px 10px 0 0">
      <h2 style="margin:0;font-size:1.05rem">⚠️ OOT 알람 — 신규 {len(records)}건</h2>
      <p style="margin:4px 0 0;font-size:.82rem;opacity:.8">{now} · 광동제약 품질·시험</p>
    </div>
    <div style="padding:14px 4px">
      <table style="border-collapse:collapse;width:100%;font-size:.85rem">
        <thead><tr style="background:#f3f4f8">
          <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #13213a">시험종류</th>
          <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #13213a">품목</th>
          <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #13213a">제조번호</th>
          <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #13213a">시험항목</th>
          <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #13213a">결과값</th>
          <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #13213a">μ / σ</th>
          <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #13213a">분류</th>
          <th style="padding:8px 10px;text-align:left;border-bottom:2px solid #13213a">알림ID</th>
        </tr></thead><tbody>{rows}</tbody>
      </table>
      <p style="margin-top:14px;font-size:.85rem">{links}</p>
      <p style="margin-top:6px;font-size:.76rem;color:#888">각 건은 <b>알림ID</b>로 추적됩니다. 발송 이력: oot_alarm_sent.csv · 로그: oot_alarm.log</p>
    </div>
    <div style="background:#f3f4f8;padding:10px 22px;font-size:.76rem;color:#666;border-radius:0 0 10px 10px">
      OOT 빠른 조회 · 광동제약 품질·시험 플랫폼
    </div></body></html>"""


def send_oot_alert(records: list[dict], cfg: dict[str, Any] | None = None,
                   subject: str | None = None, dashboard_url: str = "",
                   tableau_url: str = "") -> tuple[bool, str]:
    """OOT 알람 메일 발송. (성공여부, 메시지) 반환."""
    cfg = cfg or load_config()
    to = [a.strip() for a in (cfg.get("recipients") or []) if a.strip()]
    if not to:
        return False, "수신자가 설정되지 않았습니다(알림설정에서 등록)."
    sk = _smtp_kwargs(cfg)
    if not sk["smtp_user"]:
        return False, "SMTP 발신 계정 미설정(QMS_SMTP_USER 또는 알림설정)."
    subj = subject or f"[OOT 알람] 신규 {len(records)}건 ({datetime.now():%Y-%m-%d %H:%M})"
    body = build_oot_email_html(records, dashboard_url, tableau_url)
    # QMS 모듈이 있으면 그것을, 없으면 내장 SMTP 함수로 발송(다른 노트북 자체완결)
    _sender = _qms.send_email if _qms is not None else _send_email_smtp
    try:
        ok = _sender(subject=subj, body=body, to_addrs=to, html=True, **sk)
        if ok:
            try:
                log_sent(records, to)   # 추적용 발송 이력 기록
            except Exception:
                pass
        return bool(ok), ("발송 성공" if ok else "발송 실패")
    except Exception as e:
        return False, f"발송 오류: {e}"
