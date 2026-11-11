# -*- coding: utf-8 -*-
"""메모리 초과 재시작(11-09·11-10 새벽, 자동 일시정지) 재발 막기 — 넘김 흘려 읽기 · 화면 캐시 비우기."""
from __future__ import annotations

import gzip
import json

import pytest

import oot_fake_rows as F
from test_oot_export import FRESH_TS, at_kst, fake_export_query


# 이전 판(68ad383, 흘려 읽기 전) 코드로 같은 가짜 자료를 넘겼을 때의 줄 파일 해시 — 두 경로가 함께 바뀌어도 잡는다.
GOLDEN_ROWS_SHA = "aa81ebdbc3957ff5c29b5e0cc8cf0e1392d28720d22b8da5a56b1d06e7ce488d"


def _stream_of(q, shuffle_seed=None):
    import random
    import oot_export

    def _iter(sql, params=None):
        assert sql == oot_export.ROWS_SQL
        got = list(q(sql, params, large=True))
        if shuffle_seed is not None:                 # ORDER BY ITEM_CD 는 품목코드 안 줄 순서를 보장하지 않는다
            random.Random(shuffle_seed).shuffle(got)
        return iter(sorted(got, key=lambda r: str(r["ITEM_CD"])))   # 조회문의 ORDER BY ITEM_CD
    return _iter


def _build_with(q, stream: bool, shuffle_seed=None):
    import oot_export
    by = {r["T"]: r["M"] for r in q(oot_export.FRESH_SQL)}
    as_of, fresh = oot_export.freshness(by, at_kst(3, 50))
    return oot_export.build(q, by, as_of, fresh, at_kst(3, 50), keep_jsonl=True,
                            rows_iter=_stream_of(q, shuffle_seed) if stream else None)


def test_streamed_build_equals_grouped_build():
    """품목코드순으로 흘려 읽어도(품목코드 안 줄 순서가 섞여도) 묶어 읽기와 같은 파일·같은 머리표가 나오고,
    이전 판 코드의 줄 파일 해시와도 같다."""
    q = fake_export_query(F.rule_rows(), FRESH_TS)
    a = _build_with(q, stream=False)
    assert a[2]["rows_sha256"] == GOLDEN_ROWS_SHA
    for seed in (None, 1, 2):
        b = _build_with(q, stream=True, shuffle_seed=seed)
        assert a[0] == b[0] and a[1] == b[1]
        assert {k: v for k, v in a[2].items() if k != "built_at"} == \
            {k: v for k, v in b[2].items() if k != "built_at"}


def test_run_once_streams_rows_in_production(monkeypatch, tmp_path):
    """운영 경로(query 를 넘기지 않음)는 줄 조회를 query_iter 로 흘려 읽고, 전체를 받는 query(ROWS_SQL) 는 부르지 않는다."""
    import databricks_client as dbx
    import oot_export
    q = fake_export_query(F.rule_rows(), FRESH_TS)
    used = []

    def _query(sql, params=None, **kw):
        assert sql != oot_export.ROWS_SQL, "운영 경로가 전체 줄을 한 번에 받았습니다"
        return q(sql, params, **kw)

    def _iter(sql, params=None):
        used.append(params["tt"])
        return _stream_of(q)(sql, params)
    monkeypatch.setattr(dbx, "query", _query)
    monkeypatch.setattr(dbx, "query_iter", _iter)
    out = oot_export.run_once(oot_export._Folder(str(tmp_path)), now_fn=lambda: at_kst(3, 50))
    assert out["ok"], out
    assert sorted(used) == sorted(oot_export.TEST_TYPES)


def test_stream_stops_when_row_count_differs():
    """흘려 받은 줄 수가 센 줄 수와 다르면 판을 만들지 않는다."""
    import oot_export
    q = fake_export_query(F.rule_rows(), FRESH_TS)

    def _short(sql, params=None):
        return iter(list(_stream_of(q)(sql, params))[:-1])
    by = {r["T"]: r["M"] for r in q(oot_export.FRESH_SQL)}
    as_of, fresh = oot_export.freshness(by, at_kst(3, 50))
    with pytest.raises(RuntimeError, match="줄 수"):
        oot_export.build(q, by, as_of, fresh, at_kst(3, 50), rows_iter=_short)


def test_key_bytes_orders_like_row_key():
    """정렬 머리 바이트의 순서가 원래 열쇠 튜플 순서와 같다(숫자·글·자릿수가 다른 숫자·앞자리 0)."""
    import itertools
    import oot_export
    vals = ["7", "007", "10", "9", "123456789012345678901234", "", "A", "a", "가", "1a", "Z9"]
    lines = [{"request_id": a, "order_id": b, "testitem_id": c}
             for a, b, c in itertools.product(vals, ["1", "x"], ["2", ""])]
    for x, y in itertools.combinations(lines, 2):
        kx, ky = oot_export._row_key(x), oot_export._row_key(y)
        bx, by_ = oot_export._key_bytes(x), oot_export._key_bytes(y)
        assert (kx < ky) == (bx < by_) and (kx == ky) == (bx == by_), (x, y)
        assert oot_export._key_len(bx + b"{}") == len(bx)


def test_default_build_does_not_keep_jsonl(monkeypatch):
    """운영 경로는 풀린 줄 파일(수십 MB)을 따로 들고 있지 않는다 — 압축본만. 압축을 풀면 해시가 맞는다."""
    import hashlib
    import oot_export
    q = fake_export_query(F.rule_rows(), FRESH_TS)
    by = {r["T"]: r["M"] for r in q(oot_export.FRESH_SQL)}
    as_of, fresh = oot_export.freshness(by, at_kst(3, 50))
    jsonl, gz, meta = oot_export.build(q, by, as_of, fresh, at_kst(3, 50))
    assert jsonl is None
    raw = gzip.decompress(gz)
    assert hashlib.sha256(raw).hexdigest() == meta["rows_sha256"]
    assert len(raw.decode("utf-8").splitlines()) == meta["row_count"]
    json.loads(raw.decode("utf-8").splitlines()[0])


def test_stream_stops_when_code_order_breaks():
    """흘려 읽다가 끝난 품목코드가 다시 나오면 판을 만들지 않고 멈춘다(조용히 틀린 계산을 내지 않음)."""
    import oot_export
    rows = [r for r in F.rule_rows() if r["BIZPROCESS_NM"] == F.TT_FIN]
    p1 = [r for r in rows if r["ITEM_CD"] == F.P1]
    p2 = [r for r in rows if r["ITEM_CD"] == F.P2]
    broken = p1[:3] + p2 + p1[3:]
    with pytest.raises(RuntimeError, match="순서"):
        list(oot_export._stream_code_lines(iter(broken), F.TT_FIN))


def test_cache_drops_expired_and_keeps_under_cap(monkeypatch):
    """화면 캐시: 새로 넣을 때 만료 항목을 지우고, 상한을 넘으면 오래된 것부터 지운다."""
    import kdp_core
    monkeypatch.setattr(kdp_core, "_DATA_CACHE", {})
    monkeypatch.setattr(kdp_core, "_CACHE_TTL", 300.0)
    monkeypatch.setattr(kdp_core, "_CACHE_MAX_CHARS", 25)
    monkeypatch.setattr(kdp_core, "_save_cache_disk", lambda: None)
    texts = iter(["a" * 10, "b" * 10, "c" * 10, "d" * 10])
    monkeypatch.setattr(kdp_core, "_fetch_csv", lambda params: next(texts))
    clock = {"t": 1000.0}
    monkeypatch.setattr(kdp_core.time, "time", lambda: clock["t"])

    kdp_core._view_csv({"k": 1})                 # t=1000
    clock["t"] = 1400.0                          # k=1 은 만료(400초 > 300초)
    kdp_core._view_csv({"k": 2})
    assert len(kdp_core._DATA_CACHE) == 1        # 만료 항목은 메모리에서도 지워졌다
    clock["t"] = 1401.0
    kdp_core._view_csv({"k": 3})
    clock["t"] = 1402.0
    kdp_core._view_csv({"k": 4})                 # 10+10+10 = 30 > 25 → 가장 오래된 k=2 를 지움
    keys = sorted(kdp_core._DATA_CACHE)
    assert len(keys) == 2 and all("k=2" not in k for k in keys)
    assert sum(len(t) for t, _ in kdp_core._DATA_CACHE.values()) <= 25


def test_schedule_cache_drops_expired(monkeypatch):
    import kdp_core
    monkeypatch.setattr(kdp_core, "_SCHED_CACHE", {})
    monkeypatch.setattr(kdp_core, "_fetch_stability_schedule", lambda code, tt: [])
    clock = {"t": 0.0}
    monkeypatch.setattr(kdp_core.time, "time", lambda: clock["t"])
    kdp_core._stability_schedule("A", "x")
    clock["t"] = kdp_core._SCHED_TTL + 1
    kdp_core._stability_schedule("B", "x")
    assert list(kdp_core._SCHED_CACHE) == [("B", "x", "")]


def test_cache_skips_oversized_and_prunes_on_disk_load(monkeypatch, tmp_path):
    """상한보다 큰 하나는 담지 않고(다른 항목을 지우지 않음), 디스크에서 불러올 때도 상한을 지킨다."""
    import gzip as _gz
    import pickle
    import kdp_core
    monkeypatch.setattr(kdp_core, "_DATA_CACHE", {})
    monkeypatch.setattr(kdp_core, "_CACHE_TTL", 300.0)
    monkeypatch.setattr(kdp_core, "_CACHE_MAX_CHARS", 25)
    monkeypatch.setattr(kdp_core, "_save_cache_disk", lambda: None)
    texts = iter(["a" * 10, "b" * 30])
    monkeypatch.setattr(kdp_core, "_fetch_csv", lambda params: next(texts))
    kdp_core._view_csv({"k": 1})
    assert kdp_core._view_csv({"k": 2}) == "b" * 30
    assert [t for t, _ in kdp_core._DATA_CACHE.values()] == ["a" * 10]

    import time as _time
    now = _time.time()
    f = tmp_path / "c.pkl.gz"
    with _gz.open(f, "wb") as fh:
        pickle.dump({"x": ("x" * 10, now - 3), "y": ("y" * 10, now - 2), "z": ("z" * 10, now - 1)}, fh)
    monkeypatch.setattr(kdp_core, "_CACHE_FILE", str(f))
    kdp_core._DATA_CACHE.clear()
    kdp_core._load_cache_disk()
    assert sorted(kdp_core._DATA_CACHE) == ["y", "z"]


def test_cache_cap_env_bad_value_falls_back(monkeypatch):
    import kdp_core
    monkeypatch.setenv("KDP_CACHE_MAX_MB", "abc")
    assert kdp_core._cache_max_chars() == 60_000_000
    monkeypatch.setenv("KDP_CACHE_MAX_MB", "-5")
    assert kdp_core._cache_max_chars() == 60_000_000
    monkeypatch.setenv("KDP_CACHE_MAX_MB", "10")
    assert kdp_core._cache_max_chars() == 5_000_000
