# -*- coding: utf-8 -*-
"""넘김 HTTP 주소 없음 · 일정 흐름 켜는 조건 · 새로고침 10분 제한 · 배포 파일 점검."""
from __future__ import annotations

import pytest

KEY = "test-only-key-0000"


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import dashboard_api
    import storage_io
    monkeypatch.setattr(storage_io, "_s3", None)
    monkeypatch.setattr(storage_io, "_EXPORT_DIR", str(tmp_path))
    return TestClient(dashboard_api.app), dashboard_api, tmp_path       # startup(예열·일정) 은 돌리지 않음


REMOVED = [("get", "/api/oot/export/latest"), ("get", "/api/oot/export/0123456789ab/rows.jsonl.gz"),
           ("post", "/api/oot/export/run")]


def test_no_http_export_endpoints(api, monkeypatch):
    """넘김 파일을 HTTP 로 내려주는 주소는 없다 — 열쇠가 있어도·맞는 머리말을 보내도 열리지 않는다."""
    client, dashboard_api, _ = api
    monkeypatch.setenv("OOT_EXPORT_KEY", KEY)                # 예전 열쇠가 환경에 남아 있어도
    for m, p in REMOVED:
        r = getattr(client, m)(p, headers={"X-OOT-Export-Key": KEY, "Authorization": f"Bearer {KEY}"})
        assert r.status_code in (404, 405) and "export_id" not in r.text
    paths = [getattr(r, "path", "") for r in dashboard_api.app.routes]
    assert not [p for p in paths if "/api/oot/export" in p]


def test_export_key_is_gone_from_code():
    import dashboard_api
    assert not hasattr(dashboard_api, "_require_export_key")


@pytest.mark.parametrize("mode, off, key, on", [
    ("s3", None, None, True),            # axhub 에 올라간 앱
    ("s3", "1", None, False),            # 끄는 스위치가 무엇보다 앞
    ("disk", None, KEY, False),          # 디스크 모드는 열쇠가 있어도 켜지 않는다(열쇠는 더 이상 쓰이지 않음)
    ("disk", None, None, False),         # 디스크
    ("s3-broken", None, None, False),    # S3 설정은 있으나 연결 준비 실패
])
def test_startup_schedule_conditions(monkeypatch, capsys, mode, off, key, on):
    import types
    import dashboard_api
    import oot_export
    import storage_io
    started = []

    class FakeThread:                    # 실제 스레드는 띄우지 않는다
        def __init__(self, target, daemon):
            self.target, self.daemon = target, daemon

        def start(self):
            started.append((self.target, self.daemon))

    monkeypatch.setattr(dashboard_api, "threading", types.SimpleNamespace(Thread=FakeThread))
    monkeypatch.setattr(storage_io, "export_mode", lambda: mode)
    for name, val in (("OOT_EXPORT_OFF", off), ("OOT_EXPORT_KEY", key)):
        if val is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, val)
    dashboard_api._startup_export_schedule()
    assert started == ([(oot_export.scheduler_loop, True)] if on else [])
    out = capsys.readouterr().out
    assert out.startswith(f"넘김 파일 일정: {'켬' if on else '끔'} — ") and out.count("\n") == 1
    assert KEY not in out


def test_refresh_limited_to_once_per_10_minutes(api, monkeypatch):
    import kdp_core
    client, dashboard_api, _ = api
    calls = []
    monkeypatch.setattr(kdp_core, "clear_data_cache", lambda: calls.append(1) or 3)
    monkeypatch.setitem(dashboard_api._refresh_last, "t", None)
    first = client.post("/api/refresh").json()
    second = client.post("/api/refresh").json()
    assert first == {"ok": True, "cleared": 3, "skipped": False}
    assert second["ok"] is True and second["skipped"] is True and second["cleared"] == 0
    assert 0 < second["retryAfterSec"] <= 601 and calls == [1]
    monkeypatch.setitem(dashboard_api._refresh_last, "t", dashboard_api._refresh_last["t"] - 601)
    assert client.post("/api/refresh").json()["skipped"] is False


def test_axhub_manifest_has_no_export_key():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "axhub.yaml"), encoding="utf-8") as f:
        text = f.read()
    assert "OOT_EXPORT_KEY" not in text                      # 고정 열쇠는 없앴다
    assert "- name: OOT_EXPORT_OFF" in text.split("optional:")[1]
    with open(os.path.join(root, ".dockerignore"), encoding="utf-8") as f:
        ignored = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
    assert {".env", "recipients_db.json", "oot_alert_config.json", ".oot_alarm_state.json",
            "oot_export_*", "tests/", "offline_dbx.py", ".git/"} <= ignored
    with open(os.path.join(root, ".gitignore"), encoding="utf-8") as f:
        assert "oot_export_*" in {ln.strip() for ln in f}
