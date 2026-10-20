# -*- coding: utf-8 -*-
"""규격 해석 · 시점별 규격 이탈(OOS) · 가속 유의적 변화 · 일정표 시점/종료 판정."""
from __future__ import annotations

import copy
import datetime as dt

import pytest

import oot_fake_rows as F
import stability_schedule as SS

LT = F.TT_LT
ACC = "가속 안정성시험(Acclerated)"


# ── 규격 문구 해석 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,want", [
    ("95.0 ~ 105.0 %", (95.0, 105.0)),
    ("90.0 % 이상", (90.0, None)),
    ("3 ppm 이하", (None, 3.0)),
    ("5,000 ppm 이하", (None, 5000.0)),                                   # 천 단위 쉼표
    ("1,000~2,000 mg", (1000.0, 2000.0)),
    ("아이비엽 30 % 에탄올엑스 중 헤데라코시드C 10.0 % 이상", (10.0, None)),   # 문구 속 다른 숫자
    ("평균 Q + 10 % 이상 (85 % 이상)", (85.0, None)),                      # 용출
    ("성상: 백색", (None, None)),
    ("", (None, None)),
])
def test_parse_criterion(text, want):
    import kdp_core
    assert kdp_core.parse_criterion(text) == want


# ── 가짜 가속/장기 자료 ───────────────────────────────────────────────────────
def _rows(tt, series, std="95.0 ~ 105.0 %"):
    """장기 가짜 자료에서 제조번호 23001 의 성분가 값을 series({개월: 값})로 바꾸고 시험종류를 tt 로."""
    rows = copy.deepcopy(F.plain_rows())
    out = []
    for r in rows:
        if r["BIZPROCESS_NM"] != LT:
            continue
        r["BIZPROCESS_NM"] = tt
        if r["TESTITEM_NM"] == "성분가":
            r["STANDARD_TEXT"] = std
            if r["LOT_NO"] == "23001":
                m = float(r["REQUEST_REMARK"].split(":")[1].split("개월")[0])
                if m in series:
                    r["RESULT_VALUE_NUMBER"] = r["RESULT_NUMBER_RAW"] = r["RULE_VALUE"] = F.dec(series[m])
                    r["RESULT_TEXT"] = f"{series[m]:g}"
        out.append(r)
    return out


FALLING = {0.0: 100.0, 3.0: 97.0, 6.0: 93.0, 9.0: 91.0, 12.0: 89.0}


def test_oos_listed_for_stability(fake_dbx):
    import kdp_core
    fake_dbx(_rows(LT, FALLING))
    a = kdp_core.stability_analysis(F.P1, LT)
    got = {(o["batch"], o["time"]): o["side"] for o in a["oos"]}
    assert set(got) == {("23001", 6.0), ("23001", 9.0), ("23001", 12.0)}
    assert all(v == "하한 미달" for v in got.values())
    assert "sigChange" not in a            # 유의적 변화는 가속시험에만


def test_accelerated_significant_change(fake_dbx):
    import kdp_core
    fake_dbx(_rows(ACC, FALLING))
    a = kdp_core.stability_analysis(F.P1, ACC)
    assert a["accelerated"] is True
    sc = {s["batch"]: s for s in a["sigChange"]}
    assert set(sc) == {"23001"}            # 다른 배치는 변화 5% 미만·규격 안
    s = sc["23001"]
    assert s["overLimit"] is True and s["changePct"] == -11.0 and s["changeTime"] == 12.0
    assert s["initial"] == 100.0 and s["oosCount"] == 3


def test_no_oos_keys_when_in_spec(fake_dbx):
    import kdp_core
    fake_dbx(F.plain_rows())
    a = kdp_core.stability_analysis(F.P1, LT)
    assert "oos" not in a and "sigChange" not in a and "specAssumed" not in a


def test_unreadable_spec_is_flagged_not_judged(fake_dbx):
    import kdp_core
    fake_dbx(_rows(LT, FALLING, std="표시량에 따른다"))
    a = kdp_core.stability_analysis(F.P1, LT)
    assert a["specAssumed"] is True        # 기본 90~150 을 썼다는 표시
    assert "oos" not in a                  # 근거 없는 기본값으로는 규격 이탈을 판정하지 않는다


def test_finished_product_analysis_has_no_oos(fake_dbx):
    """출하시험(완제품) 분석 응답은 예전 꼴 그대로(골든)."""
    import kdp_core
    fake_dbx(F.rule_rows())
    a = kdp_core.stability_analysis(F.P1, F.TT_FIN)
    assert "oos" not in a


# ── 일정표 ───────────────────────────────────────────────────────────────────
def _sched(plan, lot, points, end_type=None):
    """points: [(기간 글, 날짜, 상태, request_id|None)]"""
    return [{"PLAN_ID": plan, "LOT_NO": lot, "STABILITY_TEST_STATUS": "DOING", "END_TYPE": end_type,
             "SCHEDULE_NUM": "", "SCHEDULE_PERIOD": p, "SCHEDULE_DATE": d, "SCHEDULE_STATUS": st,
             "REQUEST_ID": rid} for p, d, st, rid in points]


TODAY = dt.date(2026, 10, 21)


def test_lot_status_end_progress_delay_stop():
    rows = (
        _sched(1, "A", [("제조시", "2024-01-01", "REQUEST", 1), ("3개월", "2024-04-01", "REQUEST", 2),
                        ("6개월", "2024-07-01", "REQUEST", 3)])
        + _sched(2, "B", [("제조시", "2025-01-01", "REQUEST", 4), ("12개월", "2026-01-01", "READY", None)])
        + _sched(3, "C", [("제조시", "2026-09-01", "REQUEST", 5), ("3개월", "2026-12-01", "READY", None)])
        + _sched(4, "D", [("제조시", "2025-01-01", "REQUEST", 6), ("3개월", "2025-04-01", "READY", None)], end_type="STOP")
    )
    st = SS.lot_schedule(rows, TODAY)
    assert st["A"]["status"] == "종료" and st["A"]["done"] == 3 and st["A"]["total"] == 3
    assert st["B"]["status"] == "지연" and st["B"]["next"] == {"period": "12개월", "date": "2026-01-01"}
    assert st["C"]["status"] == "진행" and st["C"]["next"]["period"] == "3개월"
    assert st["D"]["status"] == "중지"


def test_unrequested_zero_month_not_counted_and_no_next_when_ended():
    rows = _sched(1, "A", [("제조시", "2024-01-01", "READY", None), ("3개월", "2024-04-01", "REQUEST", 2),
                           ("6개월", "2024-07-01", "REQUEST", 3)])
    a = SS.lot_schedule(rows, TODAY)["A"]
    assert a["status"] == "종료" and a["done"] == 2 and a["total"] == 2 and a["next"] is None


def test_lot_with_two_plans_uses_longer_plan():
    rows = _sched(1, "A", [("제조시", "2024-01-01", "REQUEST", 1)]) + \
        _sched(2, "A", [("제조시", "2024-01-01", "REQUEST", 2), ("3개월", "2024-04-01", "READY", None)])
    st = SS.lot_schedule(rows, TODAY)
    assert st["A"]["total"] == 2 and st["A"]["plans"] == 2


def test_period_months():
    assert SS.period_months("3개월") == 3.0
    assert SS.period_months("45일") == 1.5
    assert SS.period_months("제조시") == 0.0
    assert SS.period_months("???", 7) == 7.0
    assert SS.period_months("???", None) is None


def test_schedule_overrides_wrong_remark_and_reports_conflict(monkeypatch, fake_dbx):
    """비고가 '3개월'로 잘못 적힌 9개월 시점 → 일정표대로 9개월, 충돌은 알림."""
    import kdp_core
    rows = copy.deepcopy(F.plain_rows())
    for r in rows:
        if r["BIZPROCESS_NM"] == LT and r["LOT_NO"] == "23003" and r["REQUEST_REMARK"] == "기간 : 9개월":
            r["REQUEST_REMARK"] = "기간 : 3개월"          # 복사 오기재
    fake_dbx(rows)

    # 일정표: 23003 의 시점별 요청 ID(원래 비고 기준 = 올바른 개월)
    months_by_rid = {}
    for r in F.plain_rows():
        if r["BIZPROCESS_NM"] == LT and r["LOT_NO"] == "23003":
            months_by_rid[r["REQUEST_ID"]] = int(r["REQUEST_REMARK"].split(":")[1].split("개월")[0])
    sched = _sched(9, "23003", [(f"{m}개월", "2025-01-01", "REQUEST", rid) for rid, m in sorted(months_by_rid.items())])
    monkeypatch.setattr(kdp_core, "_fetch_stability_schedule", lambda code, tt: sched if tt == LT else None)
    kdp_core._SCHED_CACHE.clear()

    df = kdp_core.stability_df(F.P1, LT)
    item = df[(df["시험항목"] == "성분가") & (df["제조번호"] == "23003")]
    assert sorted(item["시점(개월)"]) == [0.0, 3.0, 6.0, 9.0, 12.0]      # 9개월 점이 3개월로 겹치지 않는다
    assert df.attrs["monthConflicts"]["기간 : 3개월"]["schedule"] == "9개월"
    a = kdp_core.stability_analysis(F.P1, LT)
    assert a["monthConflicts"] == [{"remark": "기간 : 3개월", "schedule": "9개월", "months": 9.0, "rows": 1}]
    assert a["lotSchedule"]["23003"]["status"] == "종료"


def test_schedule_failure_falls_back_to_remark(fake_dbx):
    """일정표를 못 읽으면(None) 비고만으로 예전처럼 — 응답에 일정표 칸이 없다."""
    import kdp_core
    fake_dbx(F.plain_rows())
    a = kdp_core.stability_analysis(F.P1, LT)
    assert a["ok"] and "lotSchedule" not in a and "monthConflicts" not in a


# ── 모집단: 승인만 / 알람은 승인 전 포함 ─────────────────────────────────────────
def test_population_approved_only_except_alarm(monkeypatch):
    import databricks_client as dbx
    import kdp_core
    import oot_export
    gate = "tor.ORDER_STATUS = '90'"
    assert gate in kdp_core._COMMON_CTE          # 화면·엑셀·안정성·APQR
    assert gate in kdp_core._OOT_CTE             # 보관함 넘김
    assert gate in oot_export.ROWS_SQL and gate in oot_export.COUNT_SQL
    assert "ORDER_STATUS" not in kdp_core._OOT_CTE_ALARM   # 알람은 승인 전 결과도
    # 나머지 규칙(①~④)은 같아야 한다 — 승인 조건 한 줄만 빠진 것
    assert kdp_core._OOT_CTE.replace(kdp_core._APPROVED_SQL, "") == kdp_core._OOT_CTE_ALARM

    seen = []
    monkeypatch.setattr(dbx, "query", lambda sql, params=None, large=False: seen.append(sql) or [])
    kdp_core.fetch_oot_rows_for_types([F.TT_FIN])
    assert seen and "ORDER_STATUS" not in seen[0]
