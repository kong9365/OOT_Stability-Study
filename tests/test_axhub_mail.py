# -*- coding: utf-8 -*-
"""플랫폼 메일(HTTPS) · 수신자 사전(이메일→사용자 ID) · 한국 시간 알람."""
from __future__ import annotations

import base64
import datetime as dt
import io
import json

import pytest


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def mail(tmp_path, monkeypatch):
    import axhub_mail
    import oot_mail
    import storage_io
    monkeypatch.setattr(storage_io, "_s3", None)
    monkeypatch.setattr(axhub_mail, "DIRECTORY_PATH", str(tmp_path / "user_directory.json"))
    monkeypatch.setattr(axhub_mail, "_dir_cache", None)
    monkeypatch.setattr(axhub_mail, "_dir_at", 0.0)
    monkeypatch.setattr(axhub_mail, "_members_at", 0.0)
    monkeypatch.setenv("AXHUB_RELAY_SIGNING_SECRET", "gate-test")
    monkeypatch.setattr(oot_mail, "SENT_LOG_PATH", str(tmp_path / "sent.csv"))
    monkeypatch.setenv("AXHUB_API_URL", "https://api.example.test/")
    monkeypatch.setenv("AXHUB_APP_TOKEN", "app-token-test")
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if req.full_url.endswith("/api/v1/app/mails"):
            n = len(json.loads(req.data)["to"])
            return _Resp(json.dumps({"data": {"queuedCount": n, "failedCount": 0, "results": []}}).encode())
        if "/members" in req.full_url:
            if "cursor=" not in req.full_url:
                body = {"items": [{"email": "A@kd.test", "userId": "u-a", "user": {"name": "가"}}],
                        "nextCursor": "c2"}
            else:
                body = {"items": [{"email": "b@kd.test", "userId": "u-b", "user": {}}], "nextCursor": None}
            return _Resp(json.dumps(body).encode())
        raise AssertionError(req.full_url)

    import types
    monkeypatch.setattr(axhub_mail, "_opener", types.SimpleNamespace(open=fake_urlopen))
    return axhub_mail, calls


REC = [{"시험종류": "완제품", "품목": "가", "품목코드": "1", "제조번호": "L1", "시험항목": "함량",
        "결과값": "80", "분류": "관리이탈 (±3σ 초과)", "평균": "100", "표준편차": "2"}]


def test_members_fill_directory_with_paging(mail):
    m, calls = mail
    n, note = m.refresh_from_members("user-jwt", force=True)
    assert n == 2 and "2명" in note
    assert all(c.get_header("Authorization") == "Bearer user-jwt" for c in calls)   # 관리자 로그인으로 조회
    assert m.resolve(["a@kd.test", "B@KD.TEST", "x@kd.test"]) == (["u-a", "u-b"], ["x@kd.test"])


def test_sso_headers_remembered(mail):
    axhub_mail, _ = mail
    h = {"x-axhub-user-id": "u-z", "x-axhub-user-email": base64.b64encode("Z@kd.test".encode()).decode()}
    axhub_mail.remember_from_headers(h)
    assert axhub_mail.resolve(["z@kd.test"])[0] == ["u-z"]


def test_platform_mail_used_instead_of_smtp(mail, monkeypatch):
    import oot_mail
    m, calls = mail
    m.refresh_from_members("user-jwt", force=True)
    monkeypatch.setattr(oot_mail, "_send_email_smtp", lambda **k: pytest.fail("SMTP 를 쓰면 안 됨"))
    monkeypatch.setattr(oot_mail, "_qms", None)
    ok, msg = oot_mail.send_oot_alert(REC, cfg={}, subject="[OOT] t", recipients=["a@kd.test", "nobody@kd.test"])
    assert ok and "접수 1명" in msg and "못 찾은 수신자 1명" in msg and "@" not in msg   # 개수만 알린다
    req = calls[-1]
    assert req.full_url == "https://api.example.test/api/v1/app/mails"
    assert req.get_header("Authorization") == "Bearer app-token-test"
    body = json.loads(req.data)
    assert body["to"] == ["u-a"] and body["subject"] == "[OOT] t" and len(body["html"]) <= 2000


def test_no_resolvable_recipient_is_failure(mail):
    import oot_mail
    ok, msg = oot_mail.send_oot_alert(REC, cfg={}, recipients=["nobody@kd.test"])
    assert not ok and "@" not in msg


def test_compact_html_fits_limit():
    import oot_mail
    recs = [dict(REC[0], 제조번호=f"L{i}") for i in range(60)]
    html = oot_mail.build_oot_email_html_compact(recs, "https://oot.example")
    assert len(html) <= 2000 and "외 " in html and "대시보드에서 확인" in html


def test_smtp_kept_without_platform_env(monkeypatch):
    import axhub_mail
    monkeypatch.delenv("AXHUB_APP_TOKEN", raising=False)
    assert not axhub_mail.available() and axhub_mail.transport_name() == "SMTP(로컬)"


def test_alarm_time_is_kst(monkeypatch):
    import kst
    import oot_alarm
    monkeypatch.setattr(kst, "now", lambda: dt.datetime(2026, 10, 22, 7, 0, 0))
    assert oot_alarm._seconds_until_daily("07:31") == 31 * 60
    monkeypatch.setattr(kst, "now", lambda: dt.datetime(2026, 10, 22, 7, 40, 0))
    assert oot_alarm._seconds_until_daily("07:31") == (24 * 60 - 9) * 60


def test_kst_is_utc_plus_9():
    import kst
    utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    assert abs((kst.now() - utc) - dt.timedelta(hours=9)) < dt.timedelta(seconds=5)


def test_truststore_injected_before_boto3_whatever_import_order():
    """storage_io 를 먼저 불러와도 인증서 주입이 boto3 보다 앞선다(뒤면 S3 호출이 재귀 오류)."""
    import os
    import subprocess
    import sys
    pytest.importorskip("truststore")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "STORAGE_ENDPOINT": "https://storage.example.test", "STORAGE_BUCKET": "b",
           "STORAGE_ACCESS_KEY": "k", "STORAGE_SECRET_KEY": "s", "PYTHONIOENCODING": "utf-8"}
    code = ("import sys, axhub_mail, storage_io, ssl, truststore\n"
            "assert storage_io._s3 is not None\n"
            "assert ssl.SSLContext is truststore.SSLContext\n"
            "print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr[-600:]


# ── 알림설정·수신자 API 서버측 관리자 확인 · 응답에 이메일 없음 ────────────────────────
@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import axhub_mail
    import dashboard_api
    import oot_mail
    import recipients_db
    import storage_io
    monkeypatch.setattr(storage_io, "_s3", None)
    monkeypatch.setattr(oot_mail, "CONFIG_PATH", str(tmp_path / "cfg.json"))
    monkeypatch.setattr(oot_mail, "SENT_LOG_PATH", str(tmp_path / "sent.csv"))
    monkeypatch.setattr(recipients_db, "DB_PATH", str(tmp_path / "db.json"))
    monkeypatch.setattr(axhub_mail, "DIRECTORY_PATH", str(tmp_path / "dir.json"))
    monkeypatch.setattr(axhub_mail, "_dir_cache", None)
    monkeypatch.setattr(axhub_mail, "_dir_at", 0.0)
    monkeypatch.setenv("AXHUB_RELAY_SIGNING_SECRET", "gate-test")     # axhub 게이트 뒤라고 가정
    monkeypatch.delenv("OOT_ALERT_PASSWORD", raising=False)
    monkeypatch.delenv("AXHUB_APP_TOKEN", raising=False)
    monkeypatch.setattr(dashboard_api, "_admin_tokens", {})
    monkeypatch.setattr(dashboard_api, "_auth_fails", {})
    oot_mail.save_config({"recipient_groups": {"완제품": ["kim@kd.test"]}, "recipients": ["kim@kd.test"],
                          "password_hash": oot_mail.hash_password("pw-1234")})
    (tmp_path / "sent.csv").write_text(
        "발송일시,알림ID,시험종류,품목,품목코드,제조번호,시험항목,결과값,평균,표준편차,분류,수신자\n"
        "2026-10-22 07:31:00,OOT-1,완제품,가,1,L1,함량,80,100,2,관리이탈,kim@kd.test\n", encoding="utf-8-sig")
    return TestClient(dashboard_api.app)


ADMIN_ONLY = [("get", "/api/recipients", None), ("get", "/api/recipients/groups", None),
              ("post", "/api/recipients", {"name": "x", "email": "x@kd.test"}),
              ("post", "/api/recipients/delete", {"email": "kim@kd.test"}),
              ("post", "/api/recipients/groups", {"groups": {}}),
              ("post", "/api/alarm/config", {"policy": "관리이탈만"}),
              ("post", "/api/alarm/test", {})]


def test_admin_only_endpoints_refuse_without_admin(api):
    for m, p, body in ADMIN_ONLY:
        r = api.get(p) if m == "get" else api.post(p, json=body)
        assert r.status_code == 403, p
        assert "@kd.test" not in r.text


def test_public_responses_carry_no_emails(api):
    c = api.get("/api/alarm/config").json()
    assert c["recipients"] == [] and isinstance(c["mail"]["unresolved"], int)
    assert "kim@kd.test" not in json.dumps(c, ensure_ascii=False)
    h = api.get("/api/alarm/history?days=0").json()
    assert h["sent"][0]["recipients"] == ["k***@kd.test"]          # 관리자가 아니면 가림


def test_password_issues_token_and_unlocks(api):
    assert api.post("/api/alarm/auth", json={"password": "nope"}).json()["ok"] is False
    r = api.post("/api/alarm/auth", json={"password": "pw-1234"}).json()
    assert r["ok"] and len(r["token"]) >= 32
    h = {"X-OOT-Admin": r["token"]}
    assert api.get("/api/recipients", headers=h).status_code == 200
    assert api.get("/api/alarm/config", headers=h).json()["recipients"] == ["kim@kd.test"]
    assert api.get("/api/alarm/history?days=0", headers=h).json()["sent"][0]["recipients"] == ["kim@kd.test"]
    assert api.get("/api/recipients", headers={"X-OOT-Admin": "forged"}).status_code == 403


def test_owner_role_is_admin(api):
    assert api.get("/api/recipients", headers={"X-AxHub-App-Role": "owner"}).status_code == 200
    assert api.get("/api/recipients", headers={"X-AxHub-App-Role": "app_member"}).status_code == 403


def test_password_bruteforce_is_limited(api):
    for _ in range(5):
        assert api.post("/api/alarm/auth", json={"password": "bad"}).status_code == 200
    assert api.post("/api/alarm/auth", json={"password": "pw-1234"}).status_code == 429


def test_send_result_message_has_no_email(mail):
    import oot_mail
    ok, msg = oot_mail.send_oot_alert(REC, cfg={}, recipients=["nobody@kd.test"])
    assert not ok and "@" not in msg and "1명" in msg


def test_legacy_default_password_rejected_and_owner_sets_new(api, monkeypatch):
    import hashlib
    import oot_mail
    cfg = oot_mail.load_config()
    cfg["password_hash"] = hashlib.sha256(b"131103").hexdigest()       # 예전 코드 기본값
    oot_mail.save_config(cfg)
    r = api.post("/api/alarm/auth", json={"password": "131103"}).json()
    assert r["ok"] is False and "정해지지" in r["msg"]
    c = api.get("/api/alarm/config", headers={"X-AxHub-App-Role": "owner"}).json()
    assert c["isAdmin"] is True and c["passwordSet"] is False
    own = {"X-AxHub-App-Role": "owner"}
    assert api.post("/api/alarm/password", json={"current": "", "new": "12345678"}, headers=own).json()["ok"] is False
    assert api.post("/api/alarm/password", json={"current": "", "new": "qc-oot-2026!"}, headers=own).json()["ok"]
    assert api.post("/api/alarm/auth", json={"password": "qc-oot-2026!"}).json()["ok"] is True
    assert api.post("/api/alarm/password", json={"current": "", "new": "x"}).status_code == 403   # 관리자 아님


def test_no_hardcoded_default_password_in_code():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ("oot_mail.py", "dashboard_api.py"):
        assert "131103" not in open(os.path.join(root, fn), encoding="utf-8").read()



# ── 독립 검토 지적 회귀 시험 ──────────────────────────────────────────────────
def test_role_header_not_trusted_without_gate(api, monkeypatch):
    monkeypatch.delenv("AXHUB_RELAY_SIGNING_SECRET", raising=False)       # 로컬 실행(게이트 없음)
    assert api.get("/api/recipients", headers={"X-AxHub-App-Role": "owner"}).status_code == 403


def test_directory_not_wiped_on_read_error(mail, monkeypatch):
    import storage_io
    m, _ = mail
    m.refresh_from_members("user-jwt", force=True)                       # 2명 저장됨
    orig = storage_io.read_json_strict
    def boom(*a, **k):
        raise storage_io.StorageReadError("x")
    monkeypatch.setattr(storage_io, "read_json_strict", boom)
    monkeypatch.setattr(m, "_dir_at", 0.0)
    assert m._put([("new@kd.test", "u-n", "")]) == 0                      # 읽기 오류면 저장하지 않음
    monkeypatch.setattr(storage_io, "read_json_strict", orig)
    data = json.load(open(m.DIRECTORY_PATH, encoding="utf-8"))
    assert set(data) == {"a@kd.test", "b@kd.test"}


def test_directory_reloaded_for_other_process(mail):
    m, _ = mail
    assert m.resolve(["late@kd.test"])[0] == []
    with open(m.DIRECTORY_PATH, "w", encoding="utf-8") as f:              # 다른 프로세스가 더함
        json.dump({"late@kd.test": {"id": "u-late", "name": ""}}, f)
    m._dir_at = 0.0                                                       # 1분 지남
    assert m.resolve(["late@kd.test"])[0] == ["u-late"]


def test_save_config_refuses_on_read_error(monkeypatch, tmp_path):
    import oot_mail
    import storage_io
    monkeypatch.setattr(storage_io, "_s3", None)
    monkeypatch.setattr(oot_mail, "CONFIG_PATH", str(tmp_path / "c.json"))
    def boom(*a, **k):
        raise storage_io.StorageReadError("x")
    monkeypatch.setattr(storage_io, "read_json_strict", boom)
    with pytest.raises(storage_io.StorageReadError):
        oot_mail.save_config({"policy": "관리이탈만"})
    assert not (tmp_path / "c.json").exists()


def test_no_redirect_and_https_only(monkeypatch):
    import axhub_mail
    assert any(isinstance(h, axhub_mail._NoRedirect) for h in axhub_mail._opener.handlers)
    monkeypatch.setenv("AXHUB_API_URL", "http://plain.example")
    monkeypatch.setenv("AXHUB_APP_TOKEN", "t")
    assert axhub_mail.api_url() == "" and not axhub_mail.available()


def test_history_text_masked_for_non_admin(api, monkeypatch, tmp_path):
    import dashboard_api
    log = tmp_path / "alarm.log"
    log.write_text("[2026-10-22 07:31:00]   ⚠️ [완제품] 발송 실패: 발송 오류: refused kim@kd.test" + chr(10), encoding="utf-8")
    monkeypatch.setattr(dashboard_api, "_ALARM_LOG", str(log))
    t = api.get("/api/alarm/history?days=0").json()["events"][0]["text"]
    assert "kim@kd.test" not in t and "k***@kd.test" in t


def test_password_change_revokes_tokens(api):
    tok = api.post("/api/alarm/auth", json={"password": "pw-1234"}).json()["token"]
    h = {"X-OOT-Admin": tok}
    assert api.post("/api/alarm/password", json={"current": "pw-1234", "new": "new-pass-99"}, headers=h).json()["ok"]
    assert api.get("/api/recipients", headers=h).status_code == 403
