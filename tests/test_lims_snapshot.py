# -*- coding: utf-8 -*-
"""PC 업로드 사본 — 403 일 때만 쓰고, 다른 오류는 숨기지 않고, 조회문이 파일에 닿지 못하는지 본다."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

duckdb = pytest.importorskip("duckdb")

import databricks_client as dbx  # noqa: E402
import lims_snapshot as snap  # noqa: E402
import storage_io  # noqa: E402

_query = dbx.query      # conftest 가 시험 중 dbx.query 를 막으므로 진짜 함수를 잡아 둔다
SQL = "SELECT ITEM_CD FROM `광동제약_gmp_lims`.bronze.lims_dbo_cm_item_info WHERE PLANT_CD = :p"


def _http_error(code: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = code
    return requests.HTTPError(response=resp)


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    path = str(tmp_path / "s.duckdb")
    c = duckdb.connect(path)
    c.execute("CREATE TABLE lims_dbo_cm_item_info (PLANT_CD VARCHAR, ITEM_CD VARCHAR)")
    c.execute("INSERT INTO lims_dbo_cm_item_info VALUES ('005', 'A1')")
    c.close()
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    con = snap._connect(path)
    monkeypatch.setattr(snap, "_connection", lambda: con)
    monkeypatch.setattr(snap, "_blocked_until", 0.0)
    monkeypatch.setattr(snap, "_answered_from_snapshot", False)
    monkeypatch.setattr(snap, "_disabled", False)
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(snap, "_meta", {"id": "abc", "built_at": now, "data_as_of": now})
    return con


def _raise(code):
    def f(*a, **k):
        raise _http_error(code)
    return f


def test_translate():
    out = snap.translate(SQL + " AND x::int = 1")
    assert "bronze" not in out and "$p" in out and "::int" in out


def test_403_answers_from_snapshot_and_blocks(snapshot, monkeypatch):
    monkeypatch.setattr(dbx, "_databricks_query", _raise(403))
    assert _query(SQL, {"p": "005"}) == [{"ITEM_CD": "A1"}]
    assert snap.in_use()
    assert snap.status()["source"] == "snapshot"


def test_query_iter_403_answers_from_snapshot(snapshot, monkeypatch):
    def blocked(*a, **k):       # 진짜 함수처럼 첫 행을 꺼낼 때 터지는 생성기
        raise _http_error(403)
        yield
    monkeypatch.setattr(dbx, "_databricks_iter", blocked)
    assert list(dbx.query_iter(SQL, {"p": "005"})) == [{"ITEM_CD": "A1"}]


@pytest.mark.parametrize("code", [400, 401, 404, 500])
def test_other_http_errors_are_not_hidden(snapshot, monkeypatch, code):
    monkeypatch.setattr(dbx, "_databricks_query", _raise(code))
    with pytest.raises(requests.HTTPError):
        _query(SQL, {"p": "005"})
    assert not snap.in_use()


def test_sql_error_is_not_hidden(snapshot, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("statement FAILED")
    monkeypatch.setattr(dbx, "_databricks_query", boom)
    with pytest.raises(RuntimeError):
        _query(SQL, {"p": "005"})
    assert not snap.in_use()


def test_403_without_snapshot_raises(monkeypatch):
    def none():
        raise snap.SnapshotUnavailable("없음")
    monkeypatch.setattr(snap, "_connection", none)
    monkeypatch.setattr(snap, "_blocked_until", 0.0)
    monkeypatch.setattr(dbx, "_databricks_query", _raise(403))
    with pytest.raises(requests.HTTPError):
        _query(SQL, {"p": "005"})


def test_disabled_process_does_not_use_snapshot(snapshot, monkeypatch):
    monkeypatch.setattr(snap, "_disabled", True)
    monkeypatch.setattr(dbx, "_databricks_query", _raise(403))
    with pytest.raises(requests.HTTPError):
        _query(SQL, {"p": "005"})
    assert not snap.in_use()


def test_alarm_disables_snapshot_by_default(monkeypatch):
    import sys
    import oot_alarm
    called = []
    monkeypatch.delenv("OOT_ALARM_OFF", raising=False)
    monkeypatch.setattr(snap, "disable", lambda: called.append(1))
    monkeypatch.setattr(oot_alarm.storage_io, "remove", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["oot_alarm.py", "--reset-state"])
    oot_alarm.main()
    assert called


def test_export_disables_snapshot(monkeypatch):
    import oot_export
    called = []
    monkeypatch.setattr(snap, "disable", lambda: called.append(1))
    assert oot_export.main(["--offline", "x"]) == 2      # --out 없이 바로 끝나는 길
    assert called


def _aged(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_expired_snapshot_refused(monkeypatch):
    monkeypatch.setattr(snap, "_con", object())
    monkeypatch.setattr(snap, "_checked", 9e12)
    monkeypatch.setattr(snap, "_disabled", False)
    monkeypatch.setattr(snap, "_meta", {"id": "a", "data_as_of": _aged(8)})
    monkeypatch.setattr(snap, "_blocked_until", 0.0)
    assert snap.activate() is False
    monkeypatch.setattr(snap, "_blocked_until", 9e12)
    assert not snap.in_use()


def test_missing_as_of_counts_as_expired():
    assert snap._expired({"id": "a"}) and snap._expired({"data_as_of": "2026-11-11T10:00:00"})


def test_stale_flag_and_as_of_date(snapshot, monkeypatch):
    t = datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc)      # 한국으로는 11-11 01:00
    monkeypatch.setattr(snap, "_meta", {"id": "a", "built_at": "", "data_as_of": t.isoformat()})
    monkeypatch.setattr(snap, "_answered_from_snapshot", True)
    assert snap.as_of_date().isoformat() == "2026-11-11"
    monkeypatch.setattr(snap, "_meta", {"id": "a", "data_as_of": _aged(2)})
    assert snap.status()["stale"] is True
    monkeypatch.setattr(snap, "_meta", {"id": "a", "data_as_of": _aged(0)})
    assert snap.status()["stale"] is False


def test_cache_tag_separates_sources(snapshot, monkeypatch):
    assert snap.cache_tag() == ""
    monkeypatch.setattr(snap, "_blocked_until", 9e12)
    assert snap.cache_tag() == "snap:abc|"


def test_each_connection_has_own_spill_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    path = str(tmp_path / "s.duckdb")
    duckdb.connect(path).close()
    a = snap._connect(path)
    spills = list((tmp_path / "lims_snapshot").glob("spill-*"))
    assert len(spills) == 1
    a.close()
    b = snap._connect(path)
    b.close()
    made = [p for p in (tmp_path / "lims_snapshot").iterdir()]
    assert all(p.name.startswith("spill-") for p in made)


def test_failed_first_load_backs_off(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("x")
    monkeypatch.setattr(snap, "_con", None)
    monkeypatch.setattr(snap, "_failed_at", 0.0)
    monkeypatch.setattr(snap, "_refresh", boom)
    for _ in range(3):
        with pytest.raises(snap.SnapshotUnavailable):
            snap._connection()
    assert len(calls) == 1


def test_size_mismatch_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    def fake_download(_name, dest):
        with open(dest, "wb") as f:
            f.write(b"123456789")
    monkeypatch.setattr(storage_io, "snapshot_download", fake_download)
    with pytest.raises(snap.SnapshotUnavailable):
        snap._fetch({"id": "0123456789ab", "gz_sha256": "0" * 64, "gz_bytes": 8})


def test_excel_name_marks_snapshot(snapshot, monkeypatch):
    import dashboard_api
    assert dashboard_api._source_suffix() == ""
    monkeypatch.setattr(snap, "_answered_from_snapshot", True)
    monkeypatch.setattr(snap, "_meta", {"id": "a", "built_at": "", "data_as_of": "2026-11-11T12:09:11+09:00"})
    assert dashboard_api._source_suffix() == "_PC업로드자료_20261111"


def test_cache_stores_by_actual_answer(snapshot, monkeypatch):
    """조회 도중 차단 시간이 끝나도 사본 결과는 사본 열쇠로 담긴다."""
    import kdp_core
    monkeypatch.setattr(kdp_core, "_save_cache_disk", lambda: None)
    monkeypatch.setattr(kdp_core, "_DATA_CACHE", {})

    def fetch(_params):
        snap.query(SQL, {"p": "005"})
        return "SNAPSHOT_ROWS"
    monkeypatch.setattr(kdp_core, "_fetch_csv", fetch)
    kdp_core._view_csv({"a": "1"})
    assert list(kdp_core._DATA_CACHE) == ["v4|snap:abc|a=1"]
    snap.mark_databricks()


def test_query_queue_has_time_limit(snapshot, monkeypatch):
    import threading
    monkeypatch.setattr(snap, "_run", threading.Semaphore(0))
    monkeypatch.setattr(snap, "RUN_WAIT_SEC", 0.01)
    with pytest.raises(snap.SnapshotUnavailable):
        snap.query(SQL, {"p": "005"})


def test_axhub_yaml_is_valid():
    import os
    yaml = pytest.importorskip("yaml")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "axhub.yaml"), encoding="utf-8") as f:
        assert yaml.safe_load(f)["env"]["optional"]


def test_returns_to_databricks_after_block(snapshot, monkeypatch):
    monkeypatch.setattr(dbx, "_databricks_query", _raise(403))
    _query(SQL, {"p": "005"})
    monkeypatch.setattr(snap, "_blocked_until", 0.0)      # 차단 시간이 지남
    monkeypatch.setattr(dbx, "_databricks_query", lambda *a, **k: [{"ITEM_CD": "DB"}])
    assert _query(SQL, {"p": "005"}) == [{"ITEM_CD": "DB"}]
    assert snap.status() == {"source": "databricks"}


def test_snapshot_sql_cannot_reach_files(snapshot, tmp_path):
    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(duckdb.Error):
        snap.query(f"SELECT * FROM read_csv('{secret.as_posix()}')")
    with pytest.raises(duckdb.Error):
        snap.query("SET enable_external_access=true")


def test_snapshot_is_read_only(snapshot):
    with pytest.raises(duckdb.Error):
        snap.query("DELETE FROM lims_dbo_cm_item_info")


@pytest.mark.parametrize("name", ["../oot-state/recipients_db.json", "recipients_db.json", "lims_latest.json/../x",
                                  "lims_ABC.duckdb.gz", ""])
def test_storage_rejects_other_names(name):
    with pytest.raises(ValueError):
        storage_io.snapshot_read(name)


def test_hash_mismatch_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    def fake_download(_name, dest):
        with open(dest, "wb") as f:
            f.write(b"tampered")
    monkeypatch.setattr(storage_io, "snapshot_download", fake_download)
    with pytest.raises(snap.SnapshotUnavailable):
        snap._fetch({"id": "0123456789ab", "gz_sha256": "0" * 64, "gz_bytes": 8})
    assert not list((tmp_path / "lims_snapshot").glob("*.duckdb"))


def test_column_names_exclude_people():
    """칸 이름 검사다. 자유 입력 칸(REQUEST_REMARK)의 내용까지 보증하지는 않는다."""
    for cols in snap.COLUMNS.values():
        for c in cols:
            assert not any(w in c.upper() for w in ("USER", "EMP", "NAME", "EMAIL", "TESTER", "PHONE"))


def test_data_source_api_has_no_personal_data(snapshot):
    from fastapi.testclient import TestClient
    import dashboard_api
    r = TestClient(dashboard_api.app).get("/api/data-source")
    assert r.status_code == 200 and "@" not in r.text and "\\" not in r.text
