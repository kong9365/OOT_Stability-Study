# -*- coding: utf-8 -*-
"""조회문 규칙 칸(거짓 0 · 쉼표 숫자 · 분초 서식 · D-4 잠정)을 OOT 경로가 쓰는지.

조회문 자체(SQL)의 규칙 계산은 DuckDB 시험(test_offline_dbx.py)이 맡는다 — 여기서는 규칙 칸이
채워진 줄을 받은 뒤 화면·엑셀이 어떻게 쓰는지, 조회문 글의 약속(M1), 그리고 화면·엑셀의
D-4(apply_d4, pandas)가 알람·넘김 조회문의 D-4 답과 같은지 본다.
"""
from __future__ import annotations

import random
import re

import pandas as pd

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
    for sql in (kdp_core._COMMON_CTE, kdp_core._OOT_CTE):
        lines = sql.split("\n")
        for want in A4EF25C_LINES:
            assert want.format(c=kdp_core.LIMS_CATALOG, p=kdp_core.PLANT_CD) in lines
        # 규칙 단계는 줄을 걸러내지 않는다(WHERE·QUALIFY 는 results 안에만)
        tail = sql.split("ruled0 AS (", 1)[1]
        assert "WHERE" not in tail and "QUALIFY" not in tail and "JOIN" not in tail
        assert "RESULT_VALUE_NUMBER AS RESULT_VALUE_NUMBER" not in tail


def test_common_query_same_shape_as_a4ef25c(monkeypatch):
    """(a) 화면·안정성·APQR 공용 조회문은 a4ef25c 처럼 창 함수가 중복 지우기 하나뿐(M1).

    창 함수가 더 있으면 Databricks 가 돌려주는 줄 순서가 바뀌어, 첫 줄을 골라 쓰는 안정성·APQR 응답이
    바뀐다. 규칙 단계는 칸만 더한다(걸러내기·묶기·정렬 없음). D-4 창 함수는 알람·넘김 조회문에만.
    """
    import databricks_client as dbx
    import kdp_core
    import oot_export
    seen = []
    monkeypatch.setattr(dbx, "query", lambda sql, params=None, large=False: seen.append(sql) or [])
    kdp_core._DATA_CACHE.clear()
    kdp_core._fetch_csv({"vf_시험종류": F.TT_LT, "vf_품목코드": F.P1})
    assert seen[0] == (kdp_core._COMMON_CTE
                       + "SELECT * FROM ruled WHERE BIZPROCESS_NM = :tt AND ITEM_CD = :code")
    assert seen[0].count("OVER (") == 1                     # a4ef25c 공통 조회문도 1개(QUALIFY)
    assert "QUALIFY ROW_NUMBER() OVER (" in seen[0] and "D4_HAS_OTHER" not in seen[0]
    tail = kdp_core._COMMON_CTE.split("ruled0 AS (", 1)[1].upper()
    for word in ("OVER", "WHERE", "QUALIFY", "JOIN", "GROUP BY", "ORDER BY", "DISTINCT", "UNION", "LIMIT"):
        assert word not in tail, word
    for sql in (kdp_core._OOT_CTE, oot_export.ROWS_SQL, oot_export.COUNT_SQL):
        assert "D4_HAS_OTHER" in sql and sql.count("OVER (") == 2


def test_sql_portable_without_regex():
    import kdp_core
    sql = kdp_core._OOT_CTE + kdp_core._COMMON_CTE
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
    assert "SELECT * FROM ruled WHERE" in seen[0] and "D4_HAS_OTHER" not in seen[0]
    assert "FROM ruled" in seen[1] and "avg(RULE_VALUE)" in seen[1]
    assert "D4_HAS_OTHER" in seen[1]                          # 알람은 조회문이 D-4 까지 낸다
    assert "RESULT_VALUE_NUMBER - MEAN_VALUE" not in seen[1]


# ── 화면·엑셀의 D-4(apply_d4) ──────────────────────────────────────────────────

def _korean_df(rows):
    """조회 줄 → 화면이 읽는 꼴(_product_df 처럼 CSV 를 거친 글자 표)."""
    import csv
    import io

    import kdp_core
    text = kdp_core._rows_to_csv([kdp_core._row_to_korean(r) for r in rows], kdp_core._FULL_FIELDS)
    return pd.DataFrame(list(csv.DictReader(io.StringIO(text))))


def _rule_cols(pdf):
    return {r["TESTITEM_ID"]: (r["규칙적용값"], r["뺀까닭"]) for _, r in pdf.iterrows()}


def test_pandas_d4_matches_oot_query_answers():
    """(c) 공통 조회문 줄(D-4 전)에 apply_d4 를 돌린 값 = 알람·넘김 조회문이 낼 답(손으로 적은 답).

    손으로 적은 답이 실제 SQL 과 같은지는 DuckDB 시험(test_offline_dbx)이 본다.
    """
    import kdp_core
    rows, before = F.rule_rows(), F.row_rules_only(F.rule_rows())
    n_hit = 0
    for code in (F.P1, F.P2):
        for tt in (F.TT_FIN, F.TT_LT):
            def pick(rs):
                return [r for r in rs if r["ITEM_CD"] == code and r["BIZPROCESS_NM"] == tt]
            got = _rule_cols(kdp_core.apply_d4(_korean_df(pick(before)), tt))
            want = _rule_cols(_korean_df(pick(rows)))
            assert got == want, (code, tt)
            n_hit += sum(1 for v in want.values() if v[1] == F.D4_REASON)
    assert n_hit == 2                                       # 완제품 23007 · 장기 안정성 23002 6개월


def _row(lot="23001", group="함량", item="성분가", val="100.0", yn="Y", req="R1"):
    return {"품목코드": F.P1, "제조번호": lot, "대분류": group, "시험항목": item, "규칙적용값": val,
            "뺀까닭": "", "적부": yn, "의뢰번호": req}


def _hits(rows, tt):
    import kdp_core
    out = kdp_core.apply_d4(pd.DataFrame(rows), tt)
    return [(r["규칙적용값"], r["뺀까닭"]) for _, r in out.iterrows()]


def test_pandas_d4_groups():
    """묶음: 제조번호·대분류·시험항목(안정성은 의뢰번호까지). 빈 제조번호·홀로 있는 N/A·값 없는 줄은 그대로."""
    cut, kept = ("", F.D4_REASON), ("92.0", "")
    na = _row(yn="A", val="92.0")
    # 같은 묶음에 다른 숫자 결과가 있으면 뺀다(완제품은 의뢰가 달라도 같은 묶음)
    assert _hits([na, _row(req="R2")], F.TT_FIN) == [cut, ("100.0", "")]
    # 대분류·시험항목·제조번호가 다르면 다른 묶음 → 그대로
    assert _hits([na, _row(group="용출")], F.TT_FIN)[0] == kept
    assert _hits([na, _row(item="성분나")], F.TT_FIN)[0] == kept
    assert _hits([na, _row(lot="23002")], F.TT_FIN)[0] == kept
    # 안정성은 의뢰가 다르면 다른 묶음 → 그대로, 같은 의뢰면 뺀다
    assert _hits([na, _row(req="R2")], F.TT_LT)[0] == kept
    assert _hits([na, _row()], F.TT_LT)[0] == cut
    # 빈 제조번호 · 다른 줄이 값 없음(정성) · N/A 끼리 · 홀로 있는 N/A → 그대로
    assert _hits([_row(lot="", yn="A", val="92.0"), _row(lot="")], F.TT_FIN)[0] == kept
    assert _hits([na, _row(val="")], F.TT_FIN)[0] == kept
    assert _hits([na, _row(yn="A", val="93.0")], F.TT_FIN) == [kept, ("93.0", "")]
    assert _hits([na], F.TT_FIN) == [kept]


def _d4_view(resp):
    """화면 응답에서 D-4 결과와 판정만 — 줄 순서에 기대지 않는 부분."""
    status = {(l["lot"], it["group"], it["name"], it["val"]): it["status"]
              for l in resp["lots"] for it in l["items"] + l["normalItems"]}
    return resp["excluded"], {l["lot"]: l["excluded"] for l in resp["lots"]}, status


def test_screen_d4_same_under_shuffled_rows(fake_dbx):
    """(b) 조회 줄 순서를 섞어도 화면의 D-4 결과(뺀 줄 · 로트별 건수 · 판정)가 같다."""
    import kdp_core
    rows = F.rule_rows()
    orders = [rows, rows[::-1]] + [random.Random(s).sample(rows, len(rows)) for s in (1, 2, 3)]
    for tt, n_cut in ((F.TT_FIN, 3), (F.TT_LT, 1)):
        views = []
        for rs in orders:
            fake_dbx(rs)
            views.append(_d4_view(kdp_core.oot_lot_summary(F.P1, tt, None)))
        assert all(v == views[0] for v in views[1:]), tt
        assert sum(len(v) for v in views[0][0].values()) == n_cut
    assert views[0][1]["23002"] == {F.D4_REASON: 1}             # 장기 안정성 23002 6개월
