# -*- coding: utf-8 -*-
"""넘김 파일(oot_export) — 같은 계산 · 꼴 · 해시 · 줄 수 · 판 보존 · 저장 자리 · 한 번에 하나 · 하루 한 번."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import oot_fake_rows as F

KST = timezone(timedelta(hours=9))
FRESH_TS = "2026-10-03T18:40:00.000Z"          # = 10-04 03:40 KST (03:37 뒤)
STALE_TS = "2026-10-02T04:15:48.155Z"


def fake_export_query(rows, stamp=FRESH_TS, count_bias=0):
    import oot_export

    def _q(sql, params=None, large=False):
        if sql == oot_export.FRESH_SQL:
            return [{"T": t, "M": stamp} for t in oot_export._TABLES]
        if sql == oot_export.COUNT_SQL:
            n = sum(1 for r in rows if r["BIZPROCESS_NM"] == params["tt"])
            return [{"N": n + count_bias}]
        if sql == oot_export.ROWS_SQL:
            assert large is True
            return [dict(r) for r in rows if r["BIZPROCESS_NM"] == params["tt"]]
        raise AssertionError("모르는 조회문")
    return _q


def at_kst(h, m, day=4):
    return datetime(2026, 10, day, h, m, tzinfo=KST).astimezone(timezone.utc)


def build(rows=None, now=None):
    import oot_export
    q = fake_export_query(rows or F.rule_rows())
    by = {r["T"]: r["M"] for r in q(oot_export.FRESH_SQL)}
    now = now or at_kst(3, 50)
    as_of, fresh = oot_export.freshness(by, now)
    return oot_export.build(q, by, as_of, fresh, now)


def parse(jsonl: bytes) -> list[dict]:
    return [json.loads(x) for x in jsonl.decode("utf-8").splitlines()]


def test_same_calculation_as_screen(fake_dbx):
    """(가) 넘김 줄의 상태 = 같은 자료로 화면(oot_lot_summary)이 낸 상태."""
    import kdp_core
    lines = parse(build()[0])
    fake_dbx(F.rule_rows())
    for code in (F.P1, F.P2):
        resp = kdp_core.oot_lot_summary(code, F.TT_FIN, None)
        screen = {(l["lot"], it["group"], it["name"], it["val"]): it["status"]
                  for l in resp["lots"] for it in l["items"] + l["normalItems"]}
        mine = {(x["lot_no"], x["group_nm"], x["testitem_nm"], round(float(x["value"]), 4)): x["status"]
                for x in lines if x["item_cd"] == code and x["test_type"] == F.TT_FIN
                and x["lot_blank"] == "N" and x["status"] in ("정상", "주의", "관리이탈", "경향이탈")}
        assert mine == screen
        assert len(screen) >= 48


def test_line_shape_and_order():
    import oot_export
    jsonl, gz, meta = build()
    lines = parse(jsonl)
    assert all(tuple(sorted(x)) == tuple(sorted(oot_export.LINE_FIELDS)) for x in lines)
    assert all(isinstance(v, str) for x in lines for v in x.values())
    assert [oot_export._row_key(x) for x in lines] == sorted(oot_export._row_key(x) for x in lines)
    assert all(list(json.loads(t)) == sorted(json.loads(t)) for t in jsonl.decode().splitlines()[:5])
    by_reason = {}
    for x in lines:
        by_reason.setdefault(x["excluded_reason"], []).append(x)
    assert {x["status"] for x in by_reason["거짓 0"] + by_reason["재시험 원값(잠정)"]} == {"계산 제외"}
    assert {x["in_calc"] for x in by_reason["거짓 0"]} == {"N"}
    assert {x["status"] for x in by_reason["서식 결과(결정 전)"]} == {"정성"}
    assert any(x["lot_blank"] == "Y" and x["in_calc"] == "Y" for x in lines)   # 빈 제조번호도 평균에 들어감
    assert any(x["rules"] for x in lines if x["status"] == "경향이탈")
    assert any(x["sd_floored"] == "Y" for x in lines)                         # 정수 붕해 — σ 하한
    assert not any(k in json.dumps(meta, ensure_ascii=False) for k in ("TESTER", "EMP", "@"))


def test_hash_and_deterministic():
    jsonl, gz, meta = build()
    jsonl2, gz2, meta2 = build()
    assert jsonl == jsonl2 and gz == gz2
    assert b"\r\n" not in jsonl
    assert meta["export_id"] == hashlib.sha256(jsonl).hexdigest()[:12]
    assert meta["rows_sha256"] == hashlib.sha256(jsonl).hexdigest()
    assert gzip.decompress(gz) == jsonl
    assert meta["gz_sha256"] == hashlib.sha256(gz).hexdigest()


def test_same_rows_in_any_order_give_same_version():
    """조회 줄 순서가 실행마다 달라도(Databricks·DuckDB 병렬 조회) 같은 자료면 같은 판 — 평균·σ 끝자리까지.
    실측 2026-10-05: 같은 오프라인 사본을 두 번 돌려 판 id 가 갈렸고(평균·σ·z 끝자리 8,913줄), 생지황즙 증발잔류물
    두 줄은 z 가 -2.0 ↔ -2.0000000000000355 로 갈려 앱 화면 상태가 정상 ↔ 주의 로 바뀌었다."""
    import random
    import numpy as np
    vals = [99.38, 100.1, 98.7, 101.3, 99.9, 100.7, 98.95, 100.45, 99.15, 101.05]
    sums = set()
    for seed in range(50):                       # 이 시험의 전제 — 이 값들은 더하는 순서마다 평균 끝자리가 갈린다
        v = list(vals)
        random.Random(seed).shuffle(v)
        sums.add(float(np.mean(v)))
    assert len(sums) > 1
    b = F._Builder()
    for i, v in enumerate(vals):
        b.add(code=F.P1, tt=F.TT_FIN, lot=f"23{i + 1:03d}", group="함량", item="순서 시험",
              std="표시량의 95.0 ~ 105.0%", num=str(v), **F._dates(i))
    base = build(b.rows)[0]
    for seed in range(5):
        shuffled = list(b.rows)
        random.Random(seed).shuffle(shuffled)
        assert build(shuffled)[0] == base, seed


def test_counts_and_meta():
    import oot_export
    rows = F.rule_rows()
    jsonl, gz, meta = build(rows)
    assert meta["row_count"] == len(parse(jsonl)) == meta["source_row_count"] == len(rows)
    assert meta["counts_by_test_type"][F.TT_FIN]["rows"] == sum(r["BIZPROCESS_NM"] == F.TT_FIN for r in rows)
    assert meta["counts_by_test_type"]["의약외품(완제품)"] == {"rows": 0, "source_rows": 0}
    assert len(meta["test_types"]) == 7 and len(oot_export.TEST_TYPES) == 7
    assert meta["excluded_counts"] == {"거짓 0": 2, "재시험 원값(잠정)": 2, "서식 결과(결정 전)": 1}
    assert meta["schema"] == "oot-export/1" and meta["freshness"] == {"ok": True, "reason": ""}
    assert meta["data_as_of"] == "2026-10-03T18:40:00Z"
    assert meta["app_only_counts"]["trend"] > 0


def test_count_mismatch_stops():
    import oot_export
    q = fake_export_query(F.rule_rows(), count_bias=1)
    with pytest.raises(RuntimeError, match="줄 수"):
        oot_export.build(q, {}, "", {"ok": True, "reason": ""}, at_kst(3, 50))


def test_code_sha_ignores_line_endings(tmp_path):
    import oot_export
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    for fn in oot_export.CODE_FILES:
        (a / fn).write_bytes(b"x = 1\ny = 2\n")
        (b / fn).write_bytes(b"x = 1\r\ny = 2\r\n")
    assert oot_export.code_sha256(str(a)) == oot_export.code_sha256(str(b))


def _version(i):
    rows = F.rule_rows()
    rows[0] = dict(rows[0], RULE_VALUE=F.dec(100 + i), RESULT_VALUE_NUMBER=F.dec(100 + i))
    return rows


def test_keep_seven_and_only_own_files(tmp_path):
    import oot_export
    store = oot_export._Folder(str(tmp_path))
    (tmp_path / "oot_alert_config.json").write_text("{}")        # 남의 파일 — 지우면 안 됨
    ids = []
    for i in range(9):
        jsonl, gz, meta = build(_version(i), now=at_kst(3, 50) + timedelta(days=i))
        assert oot_export.save_version(store, meta, gz) is True
        ids.append(meta["export_id"])
    left = sorted(p.name for p in tmp_path.iterdir())
    assert "oot_alert_config.json" in left
    assert sum(n.endswith(".jsonl.gz") for n in left) == 7
    assert not (tmp_path / f"oot_export_{ids[0]}.jsonl.gz").exists()
    assert json.loads((tmp_path / "oot_export_latest.json").read_text("utf-8"))["export_id"] == ids[-1]
    assert [e["export_id"] for e in json.loads((tmp_path / "oot_export_index.json").read_text("utf-8"))] == ids[2:]


def test_same_id_does_not_overwrite_meta(tmp_path):
    import oot_export
    store = oot_export._Folder(str(tmp_path))
    jsonl, gz, meta = build(now=at_kst(3, 50))
    assert oot_export.save_version(store, meta, gz) is True
    first = (tmp_path / f"oot_export_{meta['export_id']}.meta.json").read_bytes()
    jsonl2, gz2, meta2 = build(now=at_kst(3, 50) + timedelta(days=1))   # 같은 자료, 다른 날
    assert meta2["export_id"] == meta["export_id"]
    assert oot_export.save_version(store, meta2, gz2) is False
    assert (tmp_path / f"oot_export_{meta['export_id']}.meta.json").read_bytes() == first


def test_run_once_records_last_attempt(tmp_path):
    import oot_export
    store = oot_export._Folder(str(tmp_path))
    res = oot_export.run_once(store, fake_export_query(F.rule_rows()), now_fn=lambda: at_kst(3, 50))
    assert res["ok"] and res["new_version"] and len(res["export_id"]) == 12
    meta, attempt = oot_export.read_latest(store)
    assert meta["export_id"] == res["export_id"] and meta["storage"] == "folder"
    assert attempt == res
    # 적재가 안 된 채 04:45 를 넘기면 이전 판을 두고 까닭을 남긴다
    stale = oot_export.run_once(store, fake_export_query(_version(1), stamp=STALE_TS), wait_fresh=True,
                                now_fn=lambda: at_kst(4, 50), sleep_fn=lambda s: None)
    assert stale["ok"] is False and "04:45" in stale["reason"]
    meta2, attempt2 = oot_export.read_latest(store)
    assert meta2["export_id"] == res["export_id"] and attempt2 == stale


def test_wait_fresh_retries_until_loaded(tmp_path):
    import oot_export
    store = oot_export._Folder(str(tmp_path))
    clock = {"t": at_kst(3, 45)}
    stamps = [STALE_TS, STALE_TS, FRESH_TS]
    base = fake_export_query(F.rule_rows())

    def q(sql, params=None, large=False):
        if sql == oot_export.FRESH_SQL:
            s = stamps.pop(0) if len(stamps) > 1 else stamps[0]
            return [{"T": t, "M": s} for t in oot_export._TABLES]
        return base(sql, params, large)
    slept = []
    res = oot_export.run_once(store, q, wait_fresh=True, now_fn=lambda: clock["t"],
                              sleep_fn=lambda s: (slept.append(s), clock.update(t=clock["t"] + timedelta(seconds=s))))
    assert res["ok"] and slept == [900, 900]


def test_broken_s3_is_failure_not_disk(tmp_path, monkeypatch):
    import oot_export
    import storage_io
    monkeypatch.setattr(storage_io, "_ENDPOINT", "https://storage.invalid")
    monkeypatch.setattr(storage_io, "_BUCKET", "b")
    monkeypatch.setattr(storage_io, "_s3", None)
    monkeypatch.setattr(storage_io, "_EXPORT_DIR", str(tmp_path / "disk"))
    assert storage_io.export_mode() == "s3-broken"
    res = oot_export.run_once(oot_export._Store(), fake_export_query(F.rule_rows()),
                              now_fn=lambda: at_kst(3, 50))
    assert res["ok"] is False and "S3" in res["reason"]
    assert not (tmp_path / "disk").exists()


def test_storage_names_are_fenced(tmp_path, monkeypatch):
    import storage_io
    monkeypatch.setattr(storage_io, "_s3", None)
    monkeypatch.setattr(storage_io, "_EXPORT_DIR", str(tmp_path))
    storage_io.export_write("oot_export_0123456789ab.meta.json", b"{}")
    assert storage_io.export_read("oot_export_0123456789ab.meta.json") == b"{}"
    for bad in ("../oot_alert_config.json", "oot_alert_config.json", ".oot_alarm_state.json",
                "oot_export_0123456789AB.meta.json", "oot_export_0123456789ab.meta.json/../x", ""):
        with pytest.raises(ValueError):
            storage_io.export_read(bad)
        with pytest.raises(ValueError):
            storage_io.export_delete(bad)
    storage_io.export_delete("oot_export_0123456789ab.meta.json")
    assert storage_io.export_read("oot_export_0123456789ab.meta.json") is None
    assert storage_io._PREFIX == "oot-state/" and storage_io._EXPORT_PREFIX == "oot-export/"


class _FakeProc:
    def __init__(self, *a, **k):
        self.args = a[0]
        self.alive = True

    def poll(self):
        return None if self.alive else 0


def test_start_child_one_at_a_time(tmp_path, monkeypatch):
    import oot_export
    store = oot_export._Folder(str(tmp_path))
    procs = []
    monkeypatch.setattr(oot_export.subprocess, "Popen", lambda *a, **k: procs.append(_FakeProc(*a)) or procs[-1])
    monkeypatch.setattr(oot_export, "_child", None)
    assert oot_export.start_child(store=store) == "started"
    assert procs[0].args[-1].endswith("oot_export.py")
    assert oot_export.start_child(store=store) == "running"           # 같은 프로세스 안
    procs[0].alive = False
    assert oot_export.acquire_running(store, oot_export.now_utc()) is True   # 다른 실행이 표지를 잡음
    assert oot_export.start_child(store=store) == "running"           # 저장소 표지
    assert oot_export.acquire_running(store, oot_export.now_utc()) is False
    oot_export.release_running(store)
    assert oot_export.start_child(store=store) == "started"
    old = {"started_at": "2026-01-01T00:00:00Z", "pid": 1}
    store.write(oot_export.RUNNING, json.dumps(old).encode())
    procs[-1].alive = False
    assert oot_export.start_child(store=store) == "started"           # 3시간 넘은 표지는 무시


def test_scheduler_once_a_day(tmp_path):
    import oot_export
    store = oot_export._Folder(str(tmp_path))
    calls = []
    start = lambda args: (calls.append(args), "started")[1]           # noqa: E731
    assert oot_export.maybe_start_scheduled(store, at_kst(3, 30), start) == "not-yet"
    assert oot_export.maybe_start_scheduled(store, at_kst(3, 46), start) == "started"
    assert oot_export.maybe_start_scheduled(store, at_kst(9, 0), start) == "done-today"   # 재시작해도
    assert oot_export.maybe_start_scheduled(store, at_kst(3, 46, day=5), start) == "started"
    assert calls == [["--wait-fresh"], ["--wait-fresh"]]

