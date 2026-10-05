# -*- coding: utf-8 -*-
"""넘김 주소 셋(열쇠 503/401/200 · 판 id 검사 · 화면 파일 연결보다 앞) · 일정 흐름 켜는 조건 · 새로고침 10분 제한."""
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


PATHS = [("get", "/api/oot/export/latest"), ("get", "/api/oot/export/0123456789ab/rows.jsonl.gz"),
         ("post", "/api/oot/export/run")]


def test_closed_without_key(api, monkeypatch):
    client, _, _ = api
    monkeypatch.delenv("OOT_EXPORT_KEY", raising=False)
    monkeypatch.setenv("API_KEY", KEY)                       # 옛 이름은 열쇠로 쓰지 않는다(M6)
    for m, p in PATHS:
        r = getattr(client, m)(p, headers={"X-OOT-Export-Key": KEY})
        assert r.status_code == 503


def test_wrong_key_401_without_leaking(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setenv("OOT_EXPORT_KEY", KEY)
    for m, p in PATHS:
        for h in ({}, {"X-OOT-Export-Key": "nope"}, {"X-API-Key": KEY}, {"Authorization": f"Bearer {KEY}"}):
            r = getattr(client, m)(p, headers=h)
            assert r.status_code == 401 and KEY not in r.text


def test_right_key_serves_latest_and_rows(api, monkeypatch):
    import oot_export
    client, _, tmp = api
    monkeypatch.setenv("OOT_EXPORT_KEY", KEY)
    h = {"X-OOT-Export-Key": KEY}
    r = client.get("/api/oot/export/latest", headers=h)
    assert r.status_code == 404 and r.json()["last_attempt"] is None
    store = oot_export._Store()
    meta = {"schema": "oot-export/1", "export_id": "0123456789ab", "built_at": "2026-10-04T00:00:00Z"}
    assert oot_export.save_version(store, meta, b"GZ") is True
    oot_export.write_state(store, last_attempt={"ok": True, "reason": ""})
    r = client.get("/api/oot/export/latest", headers=h)
    assert r.status_code == 200 and r.json()["export_id"] == "0123456789ab"
    assert r.json()["last_attempt"] == {"ok": True, "reason": ""}
    r = client.get("/api/oot/export/0123456789ab/rows.jsonl.gz", headers=h)
    assert r.status_code == 200 and r.content == b"GZ"
    for bad in ("0123456789AB", "0123456789a", "..%2F..%2Fx", "oot_alert_config", "ffffffffffff"):
        assert client.get(f"/api/oot/export/{bad}/rows.jsonl.gz", headers=h).status_code == 404


def test_run_reports_state(api, monkeypatch):
    import oot_export
    client, _, _ = api
    monkeypatch.setenv("OOT_EXPORT_KEY", KEY)
    monkeypatch.setattr(oot_export, "start_child", lambda: "running")
    r = client.post("/api/oot/export/run", headers={"X-OOT-Export-Key": KEY})
    assert r.status_code == 200 and r.json() == {"state": "running"}


@pytest.mark.parametrize("mode, off, key, on", [
    ("s3", None, None, True),            # axhub 에 올라간 앱 — 열쇠 없이 켬
    ("s3", "1", KEY, False),             # 끄는 스위치가 무엇보다 앞
    ("disk", None, KEY, True),           # 종전 동작(디스크 모드 개발용)
    ("disk", None, None, False),         # 디스크 · 열쇠 없음
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


def test_export_routes_before_static_mount(api):
    from starlette.routing import Mount
    _, dashboard_api, _ = api
    paths = [getattr(r, "path", None) for r in dashboard_api.app.routes]
    mount_at = next(i for i, r in enumerate(dashboard_api.app.routes) if isinstance(r, Mount))
    for p in ("/api/oot/export/latest", "/api/oot/export/{export_id}/rows.jsonl.gz", "/api/oot/export/run"):
        assert paths.index(p) < mount_at


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


def test_axhub_manifest_declares_dedicated_key():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "axhub.yaml"), encoding="utf-8") as f:
        text = f.read()
    assert "- name: OOT_EXPORT_KEY" in text.split("optional:")[1]
    assert "- name: OOT_EXPORT_OFF" in text.split("optional:")[1]
    with open(os.path.join(root, ".dockerignore"), encoding="utf-8") as f:
        ignored = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
    assert {".env", "recipients_db.json", "oot_alert_config.json", ".oot_alarm_state.json",
            "oot_export_*", "tests/", "offline_dbx.py", ".git/"} <= ignored
    with open(os.path.join(root, ".gitignore"), encoding="utf-8") as f:
        assert "oot_export_*" in {ln.strip() for ln in f}
