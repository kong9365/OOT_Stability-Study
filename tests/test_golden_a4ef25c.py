# -*- coding: utf-8 -*-
"""a4ef25c 응답과 같은지 — 합성 자료로 굳힌 정답 파일과 견준다.

- 안정성 분석 · APQR 묶어 보기: 한 글자도 같아야 한다(M1 — OOT 규칙이 새지 않음).
- OOT 화면(oot_lot_summary): 규칙 줄이 없는 자료에서, 새로 더한 칸만 빼면 한 글자도 같아야 한다.
"""
from __future__ import annotations

import copy

import pytest

import golden_cases as G

# OOT 화면 응답에 새로 더한 칸(D-3① 대분류 · 규칙으로 뺀 줄 표시) — 이것만 빼고 견준다.
ADDED_ITEM_KEYS = ("group",)
ADDED_LOT_KEYS = ("excluded",)
ADDED_TOP_KEYS = ("excluded", "ruleNote")


def _strip_added(resp: dict) -> dict:
    resp = copy.deepcopy(resp)
    for k in ADDED_TOP_KEYS:
        resp.pop(k, None)
    for lot in resp.get("lots", []):
        for k in ADDED_LOT_KEYS:
            lot.pop(k, None)
        for it in lot.get("items", []) + lot.get("normalItems", []):
            for k in ADDED_ITEM_KEYS:
                it.pop(k, None)
    return resp


def _golden(name: str) -> str:
    with open(G.golden_path(name), encoding="utf-8") as f:
        return f.read().rstrip("\n")


@pytest.mark.parametrize("name,ds,fn", G.UNCHANGED_CASES, ids=[c[0] for c in G.UNCHANGED_CASES])
def test_stability_and_apqr_unchanged(fake_dbx, name, ds, fn):
    import kdp_core
    fake_dbx(G.ROWS[ds]())
    assert G.dumps(fn(kdp_core)) == _golden(name)


@pytest.mark.parametrize("name,ds,fn", G.LOT_CASES, ids=[c[0] for c in G.LOT_CASES])
def test_oot_lots_same_as_a4ef25c(fake_dbx, name, ds, fn):
    import kdp_core
    fake_dbx(G.ROWS[ds]())
    assert G.dumps(_strip_added(fn(kdp_core))) == _golden(name)
