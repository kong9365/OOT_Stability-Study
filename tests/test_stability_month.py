# -*- coding: utf-8 -*-
"""안정성 시점(개월) 읽기 — 일 단위 환산 · 제조시 · 못 읽은 줄 알림.

골든(a4ef25c) 시험은 '기간 : N개월' 만 있는 자료라 그대로 통과해야 한다 — 이 파일은 새 표기만 본다.
"""
from __future__ import annotations

import copy

import pytest

import oot_fake_rows as F
from lims_parser import classify_month, parse_month

LT = F.TT_LT


@pytest.mark.parametrize("remark,tt,month,kind", [
    ("기간 : 3개월", LT, 3.0, "개월"),
    ("기간:12개월", LT, 12.0, "개월"),
    ("기간 : 45일", LT, 1.5, "일"),
    ("기간 : 90일", LT, 3.0, "일"),
    ("기간 : 120일", LT, 4.0, "일"),
    ("기간 : 제조시", LT, 0.0, "제조시"),
    ("기간 : 제조 시", LT, 0.0, "제조시"),
    ("무엇이든", F.TT_FIN, 0.0, "완제품"),     # 완제품은 특이사항과 무관하게 0개월
])
def test_classify(remark, tt, month, kind):
    assert classify_month(remark, tt) == (month, kind)
    assert parse_month(remark, tt) == month


@pytest.mark.parametrize("remark", ["", None, "기간 : 알수없음", "비고 없음", "기간 : 3주"])
def test_unreadable_stays_none(remark):
    assert classify_month(remark, LT) == (None, None)


def _rows_with_new_remarks():
    rows = copy.deepcopy(F.plain_rows())
    for r in rows:
        if r["BIZPROCESS_NM"] != LT:
            continue
        if r["LOT_NO"] == "23003" and r["REQUEST_REMARK"] == "기간 : 3개월":
            r["REQUEST_REMARK"] = "기간 : 90일"
        if r["LOT_NO"] == "23001" and r["REQUEST_REMARK"] == "기간 : 0개월":
            r["REQUEST_REMARK"] = "기간 : 제조시"
        if r["LOT_NO"] == "23001" and r["REQUEST_REMARK"] == "기간 : 9개월":
            r["REQUEST_REMARK"] = "기간 : 알수없음"
    return rows


def test_stability_df_converts_and_reports(fake_dbx):
    import kdp_core
    fake_dbx(_rows_with_new_remarks())
    df = kdp_core.stability_df(F.P1, LT)
    item = df[df["시험항목"] == "성분가"]

    # 90일 → 3개월 로 들어온다(0 은 완제품 출하시험 기준점)
    assert sorted(item[item["제조번호"] == "23003"]["시점(개월)"]) == [0.0, 3.0, 6.0, 9.0, 12.0]
    # 제조시 → 0개월
    assert 0.0 in set(item[item["제조번호"] == "23001"]["시점(개월)"])
    # 못 읽은 줄은 빠지되 알린다(정량 결과가 있는 줄만 센다)
    assert df.attrs["unmatchedRemarks"] == {"기간 : 알수없음": 1}
    assert 9.0 not in set(item[item["제조번호"] == "23001"]["시점(개월)"])
    cv = df.attrs["convertedRemarks"]
    assert cv["기간 : 90일"]["months"] == 3.0
    assert cv["기간 : 제조시"]["months"] == 0.0


def test_analysis_response_carries_notes(fake_dbx):
    import kdp_core
    fake_dbx(_rows_with_new_remarks())
    a = kdp_core.stability_analysis(F.P1, LT)
    assert a["ok"]
    assert a["unmatchedRows"] == 1
    assert a["unmatchedRemarks"] == [{"remark": "기간 : 알수없음", "rows": 1}]
    assert {c["remark"] for c in a["convertedRemarks"]} == {"기간 : 90일", "기간 : 제조시"}
    t = kdp_core.stability_tables(F.P1, LT)
    assert t["unmatchedRows"] == 1


def test_clean_data_keeps_response_shape(fake_dbx):
    """읽지 못한/환산한 줄이 없으면 응답에 새 칸이 생기지 않는다(골든과 같은 꼴)."""
    import kdp_core
    fake_dbx(F.plain_rows())
    a = kdp_core.stability_analysis(F.P1, LT)
    assert a["ok"]
    for k in ("unmatchedRemarks", "unmatchedRows", "convertedRemarks"):
        assert k not in a
