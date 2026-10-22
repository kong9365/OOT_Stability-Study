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
    monkeypatch.setattr(axhub_mail, "_members_at", 0.0)
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

    monkeypatch.setattr(axhub_mail.urllib.request, "urlopen", fake_urlopen)
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
    assert ok and "접수 1명" in msg and "nobody@kd.test" in msg          # 못 찾은 수신자는 알린다
    req = calls[-1]
    assert req.full_url == "https://api.example.test/api/v1/app/mails"
    assert req.get_header("Authorization") == "Bearer app-token-test"
    body = json.loads(req.data)
    assert body["to"] == ["u-a"] and body["subject"] == "[OOT] t" and len(body["html"]) <= 2000


def test_no_resolvable_recipient_is_failure(mail):
    import oot_mail
    ok, msg = oot_mail.send_oot_alert(REC, cfg={}, recipients=["nobody@kd.test"])
    assert not ok and "nobody@kd.test" in msg


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
