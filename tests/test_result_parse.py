# -*- coding: utf-8 -*-
"""결과 원문 해석(단위·불검출·정량한계 미만·용출 여러 값·다단계) — 화면·알람 계산까지."""
from __future__ import annotations

import pytest

import oot_fake_rows as F
import result_parse as rp


@pytest.mark.parametrize("text,item,group,want", [
    ("76 ppm", "에탄올", "잔류용매", (76.0, "숫자+단위", None)),
    ("0.1 %", "니트로소", "유연물질", (0.1, "숫자+단위", None)),
    ("0ppm", "에탄올", "", (0.0, "숫자+단위", None)),
    ("N/D", "에탄올", "", (0.0, "불검출", None)),
    ("불검출", "에탄올", "", (0.0, "불검출", None)),
    ("<0.05 % (제조처 성적서에 따름)", "유연물질", "", (0.0, "정량한계미만", 0.05)),
    ("<100 CFU/g", "총호기성생균수", "미생물한도", (0.0, "정량한계미만", 100.0)),
    ("10 미만/1g", "진균", "", (0.0, "정량한계미만", 10.0)),
    ("0.00 % (LOQ 이하)", "유연물질", "", (0.0, "불검출", None)),
    ("1,924", "에탄올", "", (1924.0, "숫자", None)),
    ("98.1", "함량 시험", "함량", (98.1, "숫자", None)),
    ("N/A", "x", "", (None, "빈값", None)),
    ("적합", "x", "", (None, "정성", None)),
    ("5분 30초", "붕해", "", (None, "정성", None)),
    ("0.0%, 0.0%, 0.1%", "유연물질", "유연물질", (None, "정성", None)),     # 서로 다른 물질 나열 — 평균 안 함
    ("11.4 %", "함량균일성(2차)", "", (None, "2차이상", None)),
])
def test_parse(text, item, group, want):
    assert rp.parse_result(text, item, group) == want


def test_dissolution_stage1_mean():
    v, kind, _ = rp.parse_result("12 %, 11 %, 12 %, 16 %, 15 %, 16 %", "4 시간 후 용출률(L1)", "용출(L1)")
    assert kind == "여러값평균" and abs(v - 82 / 6) < 1e-9


def test_stage_names():
    assert rp.stage_of("4 시간 후 용출률(L2)") == 2 and rp.stage_of("용출시험(S3)") == 3
    assert rp.stage_of("디오스민(질량편차2차)") == 2 and rp.stage_of("함량 시험") is None
    assert rp.stage_family("4 시간 후 용출률(L2)") == "4 시간 후 용출률"
    assert rp.stage_family("함량균일성(1차)") == "함량균일성"


def test_loq_floor():
    assert rp.loq_floor_z(3.5, 0.05, 0.05) == 0.0          # LOQ 이하 → 높은 쪽 이탈 아님
    assert rp.loq_floor_z(3.5, 0.2, 0.05) == 3.5
    assert rp.loq_floor_z(-3.5, 0.0, 0.05) == -3.5         # 낮은 쪽은 그대로
    assert rp.loq_floor_z(3.5, 0.05, None) == 3.5


# ── 화면(oot_lot_summary)·알람까지 ────────────────────────────────────────────────
def _rows():
    b = F._Builder()
    for i in range(12):
        lot, d = f"24{i:03d}", F._dates(i)
        common = dict(code=F.P1, tt=F.TT_FIN, lot=lot, **d)
        b.add(group="함량", item="성분가", std="95.0 ~ 105.0 %", num=100 + (i % 3) * 0.3, **common)
        b.add(group="잔류용매", item="에탄올", std="5,000 ppm 이하", num=None, seq=2,
              text=("76 ppm" if i == 11 else ("N/D" if i % 2 else "0 ppm")), **common)
        b.add(group="유연물질", item="유연물질A", std="0.5 % 이하", num=None, seq=3,
              text=("0.2 %" if i == 11 else ("0.05 %" if i == 10 else "<0.05 %")), **common)
        b.add(group="용출(L1)", item="4 시간 후 용출률(L1)", std="개개 용출률 30 % 이하", num=None, seq=4,
              text="12 %, 11 %, 12 %, 16 %, 15 %, 16 %", **common)
        entered = i in (9, 11)
        b.add(group="용출(L2)", item="4 시간 후 용출률(L2)", std="개개 용출률 30 % 이하", num=None, seq=5,
              text=("1) 평균용출율: 12 %" if entered else "N/A"), yn=("Y" if entered else "A"), **common)
    return b.rows


def _items(resp, lot):
    L = next(x for x in resp["lots"] if x["lot"] == lot)
    return {it["name"]: it for it in L["items"] + L["normalItems"]}, L


def test_screen_reads_text_results_and_stage_events(fake_dbx):
    import kdp_core
    fake_dbx(_rows())
    resp = kdp_core.oot_lot_summary(F.P1, F.TT_FIN, None)
    its, lot11 = _items(resp, "24011")
    # 예전엔 빠지던 '76 ppm'·N/D·'0 ppm' 이 들어와 12 로트 모두 계산된다
    assert its["에탄올"]["baseN"] == 12 and its["에탄올"]["valKind"] == "숫자+단위"
    assert its["에탄올"]["status"] == "관리이탈"                    # 처음 검출 → 이탈
    # 정량한계 미만은 0, LOQ 0.05 — LOQ 이하(0.05 %)는 높은 쪽 이탈로 보지 않음, 0.2 % 는 이탈
    assert its["유연물질A"]["loq"] == 0.05 and its["유연물질A"]["status"] == "관리이탈"
    its10, _ = _items(resp, "24010")
    assert its10["유연물질A"]["status"] == "정상" and its10["유연물질A"]["loq"] == 0.05   # LOQ 이하
    # 용출 평균이 모든 로트에서 같으면 σ=0(찌꺼기 σ 로 z 를 만들지 않음) → 판정 대상 아님
    assert "4 시간 후 용출률(L1)" not in its10 or its10["4 시간 후 용출률(L1)"]["sd"] in (None, 0)
    # 용출 1차는 6개 평균으로 트렌딩, 2차는 계산 제외 + 진입 이벤트
    pdf = kdp_core._product_df(F.P1, F.TT_FIN)
    l1 = pdf[pdf["시험항목"] == "4 시간 후 용출률(L1)"]["규칙적용값"].astype(float)
    assert (abs(l1 - 82 / 6) < 1e-3).all()                          # 6개 값 평균으로 읽힘
    assert "4 시간 후 용출률(L2)" not in its and "4 시간 후 용출률(L1)" not in its   # L1 은 σ=0 → 판정 제외
    ev = resp["stageEvents"]
    assert ev[0]["family"] == "4 시간 후 용출률" and ev[0]["enteredLots"] == ["24009", "24011"]
    assert any("최근 10배치 중 2배치" in r for r in ev[0]["rules"])
    assert lot11["stageEntered"] == ["4 시간 후 용출률"]
    assert resp["excluded"][rp.STAGE_REASON]                        # 진입한 2차 줄은 제외 목록에


def test_stability_value_column_unchanged(fake_dbx):
    """안정성·APQR 이 읽는 LOT결과_0제외 는 예전처럼 순수 숫자만(골든 불변)."""
    import kdp_core
    fake_dbx(_rows())
    pdf = kdp_core._product_df(F.P1, F.TT_FIN)
    eth = pdf[pdf["시험항목"] == "에탄올"]
    assert (eth["LOT결과_0제외"] == "").all() and (eth["규칙적용값"] != "").all()


def test_alarm_reads_text_results(monkeypatch):
    import databricks_client as dbx
    import kdp_core
    rows = []
    for r in _rows():
        rows.append({"BIZPROCESS_NM": r["BIZPROCESS_NM"], "ITEM_NM": r["ITEM_NM"], "ITEM_CD": r["ITEM_CD"],
                     "LOT_NO": r["LOT_NO"], "GROUP_NM": r["GROUP_NM"], "TESTITEM_NM": r["TESTITEM_NM"],
                     "RULE_VALUE": r["RESULT_VALUE_NUMBER"], "RESULT_TEXT": r["RESULT_TEXT"],
                     "RESULT_YN": r["RESULT_YN"], "EXCLUDED_REASON": ""})
    monkeypatch.setattr(dbx, "query_iter", lambda sql, params=None: iter(rows))
    out = kdp_core.fetch_oot_rows_for_types([F.TT_FIN])
    hits = {(o["시험항목"], o["제조번호"]) for o in out if o["OOT_구간분류_히트맵"].startswith("관리이탈")}
    assert ("에탄올", "24011") in hits and ("유연물질A", "24011") in hits
    assert ("유연물질A", "24010") not in {(o["시험항목"], o["제조번호"]) for o in out}   # LOQ 이하
    assert not any("(L2)" in o["시험항목"] for o in out)                              # 2차는 트렌딩 제외


def test_stage1_result_kept_when_lot_went_to_stage2(fake_dbx):
    """2차로 간 로트는 1차 적부가 N/A 로 저장된다 — 1차 결과는 그래도 트렌딩에 넣는다."""
    import kdp_core
    rows = _rows()
    for r in rows:
        if r["LOT_NO"] == "24009" and r["TESTITEM_NM"] == "4 시간 후 용출률(L1)":
            r["RESULT_YN"] = "A"
            r["RESULT_TEXT"] = "17 %,14 %,15 %,21 %,18 %,18 %"
    fake_dbx(rows)
    pdf = kdp_core._product_df(F.P1, F.TT_FIN)
    v = pdf[(pdf["시험항목"] == "4 시간 후 용출률(L1)") & (pdf["제조번호"] == "24009")]["규칙적용값"]
    assert abs(float(v.iloc[0]) - 103 / 6) < 1e-3
    # 1차가 아닌 항목의 적부 N/A 원문은 여전히 읽지 않는다
    for r in rows:
        if r["LOT_NO"] == "24009" and r["TESTITEM_NM"] == "에탄올":
            r["RESULT_YN"] = "A"
    fake_dbx(rows)
    pdf = kdp_core._product_df(F.P1, F.TT_FIN)
    assert (pdf[(pdf["시험항목"] == "에탄올") & (pdf["제조번호"] == "24009")]["규칙적용값"] == "").all()
