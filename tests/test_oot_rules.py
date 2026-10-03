# -*- coding: utf-8 -*-
"""조회문 규칙 칸(거짓 0 · 쉼표 숫자 · 분초 서식 · D-4 잠정)을 OOT 경로가 쓰는지.

조회문 자체(SQL)의 규칙 계산은 DuckDB 시험(test_offline_dbx.py)이 맡는다 — 여기서는 규칙 칸이
채워진 줄을 받은 뒤 화면·엑셀이 어떻게 쓰는지, 그리고 조회문 글의 약속(M1)만 본다.
"""
from __future__ import annotations

import re

import oot_fake_rows as F


def _lots(resp):
    return {l["lot"]: l for l in resp["lots"]}


def _all_items(lot):
    return lot["items"] + lot["normalItems"]


def test_screen_drops_false_zero_and_provisional_retest(fake_dbx):
    import kdp_core
    fake_dbx(F.rule_rows())
    resp = kdp_core.oot_lot_summary(F.P1, F.TT_FIN, None)
    lots = _lots(resp)
    assert lots["23001"]["excluded"] == {"거짓 0": 1}
    assert lots["23005"]["excluded"] == {"거짓 0": 1}
    assert lots["23007"]["excluded"] == {"재시험 원값(잠정)": 1}
    assert lots["23002"]["excluded"] == {}
    assert {k: len(v) for k, v in resp["excluded"].items()} == {"거짓 0": 2, "재시험 원값(잠정)": 1}
    assert resp["excluded"]["거짓 0"][0] == {"lot": "23001", "group": "함량", "name": "성분가",
                                           "text": "100.20", "raw": "0.000000"}
    assert "잠정" in resp["ruleNote"]
    # 거짓 0 줄의 0 과 원시험 92.0 은 어느 로트 항목에도 값으로 나오지 않는다
    vals = [(it["name"], it["val"]) for l in resp["lots"] for it in _all_items(l)]
    assert ("성분나", 0.0) not in vals and ("성분가", 0.0) not in vals
    assert ("성분가", 92.0) not in vals
    # 뺀 줄은 정성 개수에 섞이지 않는다(23005: 확인시험 1건만 정성)
    assert lots["23005"]["qual"] == 1


def test_screen_restores_comma_numbers_and_tags_format_rows(fake_dbx):
    import kdp_core
    fake_dbx(F.rule_rows())
    lots = _lots(kdp_core.oot_lot_summary(F.P1, F.TT_FIN, None))
    hard = [it for l in lots.values() for it in _all_items(l) if it["name"] == "경도"]
    assert len(hard) == len(F.P1_LOTS)              # 쉼표 숫자 8줄도 계산에 들어옴(예전 16줄)
    assert {it["baseN"] for it in hard} == {len(F.P1_LOTS)}
    # '7분 30초' 줄은 값이 비어 정성으로 남는다(확인시험 + 붕해)
    assert lots["23011"]["qual"] == 2
    assert all(it["name"] != "붕해" for it in _all_items(lots["23011"]))
    # 홀로 있는 적부 N/A 줄(23012 유연물질)은 그대로 계산한다
    assert any(it["name"] == "유연물질" for it in _all_items(lots["23012"]))


def test_year_filter_limits_excluded_list(fake_dbx):
    import kdp_core
    fake_dbx(F.rule_rows())
    assert kdp_core.oot_lot_summary(F.P1, F.TT_FIN, "2024")["excluded"] == {}
    assert len(kdp_core.oot_lot_summary(F.P1, F.TT_FIN, "2023")["excluded"]["거짓 0"]) == 2


def test_excel_uses_rule_values(fake_dbx, monkeypatch):
    import kdp_core
    import oot_excel_report
    cfgs = []
    monkeypatch.setattr(oot_excel_report, "build_report", lambda wb, cfg: (cfgs.append(cfg),
                                                                          wb.create_sheet(cfg["sheet"])))
    fake_dbx(F.rule_rows())
    kdp_core.oot_excel(F.P1, F.TT_FIN)
    by = {c["sheet"]: c for c in cfgs}
    assert len(by["경도"]["values"]) == len(F.P1_LOTS)
    assert 0.0 not in by["성분나"]["values"]
    assert 92.0 not in by["성분가(함량)"]["values"] and 0.0 not in by["성분가(함량)"]["values"]


def test_ruled_csv_keeps_old_columns_identical():
    """새 칸을 더해도 예전 칸(저장 숫자 등)은 같은 글자 — 안정성·APQR 이 읽는 칸."""
    import kdp_core
    row = [r for r in F.rule_rows() if r["EXCLUDED_REASON"] == "거짓 0"][0]
    k = kdp_core._row_to_korean(row)
    assert k["LOT결과_0제외"] == "0.000000" and k["확인_표준편차"] == "1"
    assert k["규칙적용값"] == "" and k["뺀까닭"] == "거짓 0" and k["결과원문"] == "100.20"
    assert kdp_core._FULL_FIELDS[:14] == ["품목코드", "품목", "제조번호", "시험항목", "대분류", "시험기준",
                                          "LOT결과_0제외", "확인_평균", "확인_표준편차",
                                          "OOT_구간분류_히트맵", "의뢰일자", "제조일자", "유효기한",
                                          "의뢰 특이사항"]


# a4ef25c 조회문에서 그대로 남아야 하는 줄(저장 숫자 칸 · 조인 · 걸러내기 · 중복 지우기).
A4EF25C_LINES = [
    "    CASE WHEN try_cast(ttr.RESULT_VALUE AS DOUBLE) IS NOT NULL THEN ttr.RESULT_VALUE_NUMBER END AS RESULT_VALUE_NUMBER,",
    "  FROM `{c}`.bronze.lims_dbo_test_request_receive trr",
    "  LEFT JOIN `{c}`.bronze.lims_dbo_test_order_result tor",
    "    ON tor.PLANT_CD=trr.PLANT_CD AND tor.REQUEST_ID=trr.REQUEST_ID",
    "  LEFT JOIN `{c}`.bronze.lims_dbo_test_testitem_result ttr",
    "    ON ttr.PLANT_CD=tor.PLANT_CD AND ttr.REQUEST_ID=tor.REQUEST_ID AND ttr.ORDER_ID=tor.ORDER_ID",
    "  WHERE trr.PLANT_CD='{p}' AND ttr.TESTITEM_ID IS NOT NULL",
    "  QUALIFY ROW_NUMBER() OVER (",
    "    PARTITION BY trr.PLANT_CD,trr.REQUEST_ID,tor.ORDER_ID,ttr.TESTITEM_ID",
    "    ORDER BY ttr.UPDATE_TIME DESC, tor.UPDATE_TIME DESC",
]


def test_sql_keeps_stored_number_and_row_set():
    import kdp_core
    sql = kdp_core._RESULTS_CTE
    lines = sql.split("\n")
    for want in A4EF25C_LINES:
        assert want.format(c=kdp_core.LIMS_CATALOG, p=kdp_core.PLANT_CD) in lines
    # 규칙 단계는 줄을 걸러내지 않는다(WHERE·QUALIFY 는 results 안에만)
    tail = sql.split("ruled0 AS (", 1)[1]
    assert "WHERE" not in tail and "QUALIFY" not in tail and "JOIN" not in tail
    assert "RESULT_VALUE_NUMBER AS RESULT_VALUE_NUMBER" not in tail


def test_sql_portable_without_regex():
    import kdp_core
    sql = kdp_core._RESULTS_CTE
    assert "\\" not in sql
    assert not re.search(r"regexp|rlike|similar to", sql, re.I)
    assert "LIKE '%분%' AND RESULT_TEXT LIKE '%초%'" in sql     # '분'만으로 잡지 않음(G4)


def test_oot_paths_read_rule_columns(fake_dbx, monkeypatch):
    import databricks_client as dbx
    import kdp_core
    seen = []

    def _q(sql, params=None, large=False):
        seen.append(sql)
        return []
    monkeypatch.setattr(dbx, "query", _q)
    kdp_core._DATA_CACHE.clear()
    kdp_core._fetch_csv({"vf_시험종류": F.TT_FIN, "vf_품목코드": F.P1})
    kdp_core.fetch_oot_rows_for_types([F.TT_FIN])
    assert "SELECT * FROM ruled WHERE" in seen[0]
    assert "FROM ruled" in seen[1] and "avg(RULE_VALUE)" in seen[1]
    assert "RESULT_VALUE_NUMBER - MEAN_VALUE" not in seen[1]
