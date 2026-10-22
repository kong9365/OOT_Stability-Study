# -*- coding: utf-8 -*-
"""안정성 일정표(ST_STABILITY_SCHEDULE) — 시점(개월)의 근거와 제조번호별 진행·종료 판정.

시점(개월)의 근거는 LIMS 안정성 일정의 SCHEDULE_PERIOD 다. 의뢰 비고의 '기간 : N개월' 은 사람이 적은
글이라 복사 오기재가 있다(비고 3개월·일정 7~8개월 3건, 2026-10-21 확인). 일정표에 이 의뢰가 있으면
일정표를, 없으면 비고를 쓴다. 일정표 조회가 실패해도 비고만으로 예전처럼 돈다.

종료 판정에 LIMS 계획 상태(STABILITY_TEST_STATUS)는 쓰지 않는다 — 안정성 계획 699건 중 698건이
DOING, END 는 0건이라 아무도 관리하지 않는 값이다. 대신 일정표 상태(SCHEDULE_STATUS)로 판정한다.

순수 함수(조회 제외)라 Databricks 없이 시험할 수 있다.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

import kst
from lims_parser import classify_month


def query_sql(catalog: str, plant_cd: str) -> str:
    """품목(:code)·시험종류(:tt)의 안정성 계획 일정 전체(미의뢰 시점 포함)."""
    cat = f"`{catalog}`.bronze.lims_dbo_"
    return f"""
SELECT p.PLAN_ID, p.LOT_NO, p.STABILITY_TEST_STATUS, p.END_TYPE,
       s.SCHEDULE_NUM, s.SCHEDULE_PERIOD, s.SCHEDULE_DATE, s.SCHEDULE_STATUS, s.REQUEST_ID
FROM {cat}st_stability_plan p
JOIN {cat}st_stability_schedule s ON s.PLANT_CD=p.PLANT_CD AND s.PLAN_ID=p.PLAN_ID
WHERE p.PLANT_CD='{plant_cd}' AND p.ITEM_CD = :code
  AND p.PLAN_ID IN (
    SELECT s2.PLAN_ID FROM {cat}st_stability_schedule s2
    JOIN {cat}test_request_receive trr ON trr.PLANT_CD=s2.PLANT_CD AND trr.REQUEST_ID=s2.REQUEST_ID
    JOIN {cat}qm_bizprocess_master qbm ON qbm.PLANT_CD=trr.PLANT_CD AND qbm.BIZPROCESS_CD=trr.BIZPROCESS_CD
    WHERE s2.PLANT_CD='{plant_cd}' AND trr.ITEM_CD = :code AND qbm.BIZPROCESS_NM = :tt)
"""


def rid(x) -> str:
    """REQUEST_ID 를 비교용 글자로('123.0'·Decimal 도 같게)."""
    t = "" if x is None else str(x).strip()
    return t[:-2] if t.endswith(".0") else t


def period_months(period, num=None) -> Optional[float]:
    """SCHEDULE_PERIOD('3개월'·'45일'·'제조시') → 개월. 못 읽으면 SCHEDULE_NUM."""
    m, _ = classify_month("기간 : " + str(period or ""), "")
    if m is not None:
        return m
    try:
        return float(num)
    except (TypeError, ValueError):
        return None


def schedule_months(rows: Optional[list]) -> dict:
    """의뢰(REQUEST_ID) → (개월, 일정표 표기). 의뢰가 아직 연결 안 된 시점은 빠진다."""
    out = {}
    for r in rows or []:
        k = rid(r.get("REQUEST_ID"))
        if not k:
            continue
        m = period_months(r.get("SCHEDULE_PERIOD"), r.get("SCHEDULE_NUM"))
        if m is not None:
            out[k] = (m, str(r.get("SCHEDULE_PERIOD") or "").strip())
    return out


def _date(v) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def lot_schedule(rows: Optional[list], today: Optional[_dt.date] = None) -> dict:
    """제조번호별 일정 진행·종료.

    종료: 마지막 시점이 의뢰됨 / 지연: 남은 시점 중 가장 이른 예정일이 오늘 이전 / 진행: 그 밖 /
    중지: 계획이 STOP 으로 끝남. 한 제조번호에 계획이 여럿이면 시점이 가장 많은 계획을 쓴다.
    """
    today = today or kst.now().date()          # 컨테이너 시계(UTC)가 아니라 한국 날짜
    plans: dict = {}
    for r in rows or []:
        plans.setdefault(str(r.get("PLAN_ID")), []).append(r)
    lot_of = {pid: str(pts[0].get("LOT_NO") or "").strip() for pid, pts in plans.items()}
    n_plans: dict = {}
    for lot in lot_of.values():
        n_plans[lot] = n_plans.get(lot, 0) + 1
    best: dict = {}
    for pid, pts in plans.items():
        lot = lot_of[pid]
        if not lot:
            continue
        cur = best.get(lot)
        if cur is None or (len(pts), pid) > (len(cur[1]), cur[0]):
            best[lot] = (pid, pts)
    out = {}
    for lot, (_pid, pts) in best.items():
        def _key(r):
            m = period_months(r.get("SCHEDULE_PERIOD"), r.get("SCHEDULE_NUM"))
            return (m if m is not None else 1e9, str(r.get("SCHEDULE_DATE") or ""))
        # 0개월(제조시)은 출하 완제품 시험으로 갈음해 일정표에 의뢰가 안 걸린 경우가 많다 — 미의뢰여도 세지 않는다.
        pts = sorted((r for r in pts if str(r.get("SCHEDULE_STATUS") or "") == "REQUEST"
                      or period_months(r.get("SCHEDULE_PERIOD"), r.get("SCHEDULE_NUM")) != 0.0), key=_key)
        if not pts:
            continue
        done = [r for r in pts if str(r.get("SCHEDULE_STATUS") or "") == "REQUEST"]
        left = [r for r in pts if str(r.get("SCHEDULE_STATUS") or "") != "REQUEST"]
        last = pts[-1]
        nxt = None
        if left:
            dated = sorted(((_date(r.get("SCHEDULE_DATE")), r) for r in left if _date(r.get("SCHEDULE_DATE"))),
                           key=lambda x: x[0])
            d0, r0 = dated[0] if dated else (None, left[0])
            nxt = {"period": str(r0.get("SCHEDULE_PERIOD") or "").strip(),
                   "date": d0.isoformat() if d0 else None}
        if any(str(r.get("END_TYPE") or "") == "STOP" for r in pts):
            status = "중지"
        elif str(last.get("SCHEDULE_STATUS") or "") == "REQUEST":
            status = "종료"
            nxt = None   # 마지막 시점이 의뢰됐으면 '다음'은 의미 없다(중간에 건너뛴 시점 포함)
        elif nxt and nxt["date"] and nxt["date"] < today.isoformat():
            status = "지연"
        else:
            status = "진행"
        out[lot] = {"status": status, "done": len(done), "total": len(pts),
                    "last": str(last.get("SCHEDULE_PERIOD") or "").strip(), "next": nxt,
                    "plans": n_plans.get(lot, 1)}
    return out
