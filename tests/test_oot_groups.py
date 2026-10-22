# -*- coding: utf-8 -*-
"""D-3① — 같은 시험항목 이름이라도 대분류가 다르면 다른 항목으로 묶는다(화면·엑셀·알람)."""
from __future__ import annotations

import oot_fake_rows as F


def _items(resp, name):
    return [it for l in resp["lots"] for it in l["items"] + l["normalItems"] if it["name"] == name]


def test_screen_splits_same_name_by_group(fake_dbx):
    import kdp_core
    fake_dbx(F.rule_rows())
    resp = kdp_core.oot_lot_summary(F.P1, F.TT_FIN, None)
    by_group = {}
    for it in _items(resp, "성분가"):
        by_group.setdefault(it["group"], []).append(it)
    assert set(by_group) == {"함량", "용출"}
    # 함량: 로트 24 + 제조번호 빈 줄 2(빈 줄의 N/A 줄은 그대로 남음) + 거짓 0 줄의 원문 숫자 1 · 용출: 로트 24
    assert {it["baseN"] for it in by_group["함량"]} == {27}
    assert {it["baseN"] for it in by_group["용출"]} == {24}
    assert 99 < by_group["함량"][0]["mean"] < 101
    assert 93 < by_group["용출"][0]["mean"] < 97


def test_plain_items_carry_group(fake_dbx):
    import kdp_core
    fake_dbx(F.plain_rows())
    resp = kdp_core.oot_lot_summary(F.P1, F.TT_FIN, None)
    groups = {(it["name"], it["group"]) for l in resp["lots"] for it in l["items"] + l["normalItems"]}
    assert groups == {("성분가", "함량"), ("성분나", "함량"), ("붕해", "물리"), ("유연물질", "순도")}


def test_excel_one_sheet_per_group_item(fake_dbx, monkeypatch):
    import kdp_core
    import oot_excel_report
    cfgs = []
    monkeypatch.setattr(oot_excel_report, "build_report",
                        lambda wb, cfg: (cfgs.append(cfg), wb.create_sheet(cfg["sheet"])))
    fake_dbx(F.rule_rows())
    kdp_core.oot_excel(F.P1, F.TT_FIN)
    sheets = [c["sheet"] for c in cfgs]
    assert sheets == ["경도", "붕해", "성분가(용출)", "성분가(함량)", "성분나", "유연물질"]
    by = {c["sheet"]: c for c in cfgs}
    assert by["성분가(함량)"]["검사항목"] == "성분가(함량)"
    assert "성분가(용출)" in by["성분가(용출)"]["title"]
    # 대분류가 하나뿐인 항목은 예전 이름 그대로
    assert by["성분나"]["검사항목"] == "성분나" and "(" not in by["성분나"]["title"].split("성분나")[1]


def test_alarm_groups_by_major_category(monkeypatch):
    """알람의 평균·σ 는 '대분류+시험항목' 묶음마다 — 같은 이름이라도 대분류가 다르면 따로(D-3①)."""
    import databricks_client as dbx
    import kdp_core
    seen = []

    def row(lot, grp, v, text=None):
        return {"BIZPROCESS_NM": F.TT_FIN, "ITEM_NM": F.P1_NAME, "ITEM_CD": F.P1, "LOT_NO": lot,
                "GROUP_NM": grp, "TESTITEM_NM": "성분가", "RULE_VALUE": v, "RESULT_TEXT": text,
                "RESULT_YN": "Y", "EXCLUDED_REASON": ""}
    rows = [row(f"23{i:03d}", "용출", 95.0 + (i % 3) * 0.5) for i in range(12)] + [row("23099", "용출", 80.0)]
    rows += [row(f"23{i:03d}", "함량", 80.0 + (i % 3) * 0.5) for i in range(12)]   # 다른 대분류: 80 이 정상
    monkeypatch.setattr(dbx, "query_iter", lambda sql, params=None: iter(seen.append(sql) or rows))
    out = kdp_core.fetch_oot_rows_for_types([F.TT_FIN])
    assert "FROM ruled" in seen[0]
    hits = [(o["대분류"], o["제조번호"]) for o in out]
    assert hits == [("용출", "23099")]
    assert out[0]["시험항목"] == "성분가" and out[0]["OOT_구간분류_히트맵"].startswith("관리이탈")