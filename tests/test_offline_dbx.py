# -*- coding: utf-8 -*-
"""오프라인 조회(offline_dbx) — 조회문 규칙을 실제 SQL 로 돌려 손으로 적은 답과 맞춘다.

DuckDB 가 없으면(설치는 사용자 허락 뒤) SQL 을 실제로 돌리는 시험은 '건너뜀'으로 표시된다.
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest

import oot_fake_rows as F

HAS_DUCKDB = importlib.util.find_spec("duckdb") is not None
needs_duckdb = pytest.mark.skipif(not HAS_DUCKDB, reason="DuckDB 미설치 — 사용자 허락 뒤 설치하면 돈다")
STAMP = "2026-10-03T18:40:00Z"


def test_translate_only_names_and_params():
    import offline_dbx
    sql = ("SELECT 'a:b' AS x FROM `광동제약_gmp_lims`.bronze.lims_dbo_cm_item_info cii "
           "WHERE cii.ITEM_CD = :code AND BIZPROCESS_NM IN (:tt0, :tt1)")
    assert offline_dbx.translate(sql) == ("SELECT 'a:b' AS x FROM lims_dbo_cm_item_info cii "
                                          "WHERE cii.ITEM_CD = $code AND BIZPROCESS_NM IN ($tt0, $tt1)")


@pytest.mark.skipif(HAS_DUCKDB, reason="DuckDB 가 있으면 해당 없음")
def test_offline_without_duckdb_is_clear(tmp_path, capsys):
    import oot_export
    assert oot_export.main(["--offline", str(tmp_path), "--out", str(tmp_path / "o")]) == 2
    assert "DuckDB" in capsys.readouterr().out


def raw_tables(rows):
    """조회문 꼴 합성 줄 → LIMS 원표 다섯(PLANT_CD 005). 숫자는 decimal(17,6) 글로."""
    trr, tor, ttr, cii, qbm = {}, {}, [], {}, {}
    for r in rows:
        trr[r["REQUEST_ID"]] = {
            "PLANT_CD": "005", "REQUEST_ID": r["REQUEST_ID"], "ITEM_CD": r["ITEM_CD"],
            "ITEM_NM_REPORT": r["ITEM_NM"], "LOT_NO": r["LOT_NO"], "BIZPROCESS_CD": r["BIZPROCESS_CD"],
            "REQUEST_NO": r["REQUEST_NO"], "REQUEST_DATE": r["REQUEST_DATE"], "LOT_DATE": r["LOT_DATE"],
            "EXPIRE_DATE": r["EXPIRE_DATE"], "REQUEST_REMARK": r["REQUEST_REMARK"], "_ingested_at": STAMP}
        tor[(r["REQUEST_ID"], r["ORDER_ID"])] = {
            "PLANT_CD": "005", "REQUEST_ID": r["REQUEST_ID"], "ORDER_ID": r["ORDER_ID"],
            "ORDER_SEQ": r["ORDER_SEQ"], "UPDATE_TIME": "2026-10-01 00:00:00", "_ingested_at": STAMP}
        ttr.append({
            "PLANT_CD": "005", "REQUEST_ID": r["REQUEST_ID"], "ORDER_ID": r["ORDER_ID"],
            "TESTITEM_ID": r["TESTITEM_ID"], "TESTITEM_SEQ": r["TESTITEM_SEQ"], "GROUP_NM": r["GROUP_NM"],
            "TESTITEM_NM": r["TESTITEM_NM"], "STANDARD_TEXT": r["STANDARD_TEXT"],
            "RESULT_VALUE": r["RESULT_TEXT"],
            "RESULT_VALUE_NUMBER": None if r["RESULT_NUMBER_RAW"] is None else str(r["RESULT_NUMBER_RAW"]),
            "RESULT_YN": r["RESULT_YN"], "RETEST_ITEM_YN": r["RETEST_ITEM_YN"],
            "UPDATE_TIME": "2026-10-01 00:00:00", "_ingested_at": STAMP})
        cii[r["ITEM_CD"]] = {"PLANT_CD": "005", "ITEM_CD": r["ITEM_CD"], "ITEM_NM": r["ITEM_NM"],
                             "_ingested_at": STAMP}
        qbm[r["BIZPROCESS_CD"]] = {"PLANT_CD": "005", "BIZPROCESS_CD": r["BIZPROCESS_CD"],
                                   "BIZPROCESS_NM": r["BIZPROCESS_NM"], "_ingested_at": STAMP}
    return {
        "lims_dbo_test_request_receive": list(trr.values()),
        "lims_dbo_test_order_result": list(tor.values()),
        "lims_dbo_test_testitem_result": ttr,
        "lims_dbo_cm_item_info": list(cii.values()),
        "lims_dbo_qm_bizprocess_master": list(qbm.values()),
    }


TYPES = {"RESULT_VALUE_NUMBER": "decimal(17,6)", "_ingested_at": "timestamp"}


def write_snapshot(root, rows):
    import pyarrow as pa
    import pyarrow.parquet as pq
    for t, recs in raw_tables(rows).items():
        d = os.path.join(root, "lims_bronze", t)
        os.makedirs(d)
        pq.write_table(pa.Table.from_pylist(recs), os.path.join(d, "part-0000.parquet"))
        cols = [{"name": k, "type": TYPES.get(k, "string")} for k in recs[0]]
        with open(os.path.join(d, "_table.json"), "w", encoding="utf-8") as f:
            json.dump({"table": t, "columns": cols}, f, ensure_ascii=False)


@needs_duckdb
def test_rule_sql_gives_expected_answers(tmp_path):
    """조회문 규칙(거짓 0 · 쉼표 · 분초 · D-4 잠정 · 빈 제조번호 · 홀로 있는 N/A)이 손으로 적은 답과 같다."""
    import kdp_core
    import offline_dbx
    rows = F.rule_rows()
    write_snapshot(str(tmp_path), rows)
    q = offline_dbx.make_query(str(tmp_path))
    got = {r["TESTITEM_ID"]: r for r in q(kdp_core._RESULTS_CTE + "SELECT * FROM ruled")}
    assert len(got) == len(rows)
    n_results = q(kdp_core._RESULTS_CTE + "SELECT count(*) AS N FROM results")[0]["N"]
    assert n_results == len(rows)                     # 규칙 단계는 줄을 걸러내지 않는다
    for r in rows:
        g = got[r["TESTITEM_ID"]]
        assert g["RESULT_VALUE_NUMBER"] == r["RESULT_VALUE_NUMBER"], r     # 저장 숫자 칸은 예전 그대로
        assert g["RULE_VALUE"] == r["RULE_VALUE"], r
        assert g["EXCLUDED_REASON"] == r["EXCLUDED_REASON"], r


@needs_duckdb
def test_export_offline_end_to_end(tmp_path, fake_dbx):
    import kdp_core
    import oot_export
    snap, out = tmp_path / "snap", tmp_path / "out"
    write_snapshot(str(snap), F.rule_rows())
    assert oot_export.main(["--offline", str(snap), "--out", str(out)]) == 0
    meta = json.loads((out / "oot_export_latest.json").read_text("utf-8"))
    assert meta["row_count"] == meta["source_row_count"] == len(F.rule_rows())
    assert meta["data_as_of"] == STAMP
    # 같은 자료로 화면 계산과 같은 상태
    import gzip
    lines = [json.loads(x) for x in gzip.decompress(
        (out / f"oot_export_{meta['export_id']}.jsonl.gz").read_bytes()).decode("utf-8").splitlines()]
    fake_dbx(F.rule_rows())
    resp = kdp_core.oot_lot_summary(F.P1, F.TT_FIN, None)
    screen = {(l["lot"], it["group"], it["name"], it["val"]): it["status"]
              for l in resp["lots"] for it in l["items"] + l["normalItems"]}
    mine = {(x["lot_no"], x["group_nm"], x["testitem_nm"], round(float(x["value"]), 4)): x["status"]
            for x in lines if x["item_cd"] == F.P1 and x["test_type"] == F.TT_FIN and x["lot_blank"] == "N"
            and x["status"] in ("정상", "주의", "관리이탈", "경향이탈")}
    assert mine == screen
