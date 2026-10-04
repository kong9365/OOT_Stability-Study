# -*- coding: utf-8 -*-
"""합성 LIMS 결과 — 조회문(results·ruled) 이 돌려줄 꼴의 줄을 만든다.

실제 자료가 아니다. 품목·제조번호·값은 모두 지어낸 것이다(사람 이름·사번 없음).
- plain_rows(): 규칙에 걸리는 줄이 없고, 시험항목마다 대분류가 하나뿐인 자료.
- rule_rows(): plain 에 규칙에 걸리는 줄(거짓 0 · 쉼표 숫자 · 분초 서식 · 적부 N/A 원시험 ·
  같은 이름 다른 대분류)을 더한 자료. 각 줄의 RULE_VALUE · EXCLUDED_REASON 은 알람·넘김 조회문
  (_OOT_CTE, D-4 잠정까지)이 내야 할 답을 손으로 적은 것이다.
- row_rules_only(): 같은 줄을 공통 조회문(_COMMON_CTE, 줄 하나 규칙만 — D-4 전)이 돌려줄 꼴로.

숫자는 Databricks 의 decimal(17,6) 처럼 Decimal 로 돌려준다(화면 CSV 의 글자 꼴을 맞추려고).
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

P1, P2 = "10001", "10002"
P1_NAME, P2_NAME = "테스트정A", "테스트정B"
TT_FIN = "완제품"
TT_LT = "장기 안정성시험(Long Term)"
BIZ_CD = {TT_FIN: "B01", TT_LT: "B14"}

FIELDS = [
    "ITEM_CD", "ITEM_NM", "LOT_NO", "BIZPROCESS_NM", "TESTITEM_NM", "GROUP_NM", "STANDARD_TEXT",
    "RESULT_VALUE_NUMBER", "REQUEST_DATE", "LOT_DATE", "EXPIRE_DATE", "REQUEST_REMARK",
    # 아래는 규칙 단계가 더하는 칸(옛 코드는 읽지 않는다)
    "RESULT_TEXT", "RESULT_NUMBER_RAW", "RULE_VALUE", "EXCLUDED_REASON", "REQUEST_NO",
    "REQUEST_ID", "ORDER_ID", "TESTITEM_ID", "ORDER_SEQ", "TESTITEM_SEQ", "RESULT_YN",
    "RETEST_ITEM_YN", "BIZPROCESS_CD",
]


def dec(x) -> Decimal | None:
    return None if x is None else Decimal(f"{float(x):.6f}")


class _Builder:
    def __init__(self):
        self.rows: list[dict] = []
        self._req: dict[tuple, int] = {}
        self._tid = 900000

    def request(self, code, tt, lot, month=None, req_no=None):
        key = (code, tt, lot, month, req_no)
        if key not in self._req:
            self._req[key] = 500000 + len(self._req)
        return self._req[key]

    def add(self, *, code, tt, lot, group, item, std, num, text=None, raw="same",
            rule="same", reason="", yn="Y", retest="N", order=1, month=None,
            req_date="", lot_date="", exp_date="", remark="", req_no=None, seq=1):
        rid = self.request(code, tt, lot, month, req_no)
        self._tid += 1
        num_d = dec(num)
        raw_d = num_d if raw == "same" else dec(raw)
        rule_d = num_d if rule == "same" else dec(rule)
        if text is None:
            text = "" if num is None else f"{float(num):g}"
        self.rows.append({
            "ITEM_CD": code, "ITEM_NM": P1_NAME if code == P1 else P2_NAME,
            "LOT_NO": lot, "BIZPROCESS_NM": tt, "TESTITEM_NM": item, "GROUP_NM": group,
            "STANDARD_TEXT": std, "RESULT_VALUE_NUMBER": num_d,
            "REQUEST_DATE": req_date, "LOT_DATE": lot_date, "EXPIRE_DATE": exp_date,
            "REQUEST_REMARK": remark,
            "RESULT_TEXT": text, "RESULT_NUMBER_RAW": raw_d, "RULE_VALUE": rule_d,
            "EXCLUDED_REASON": reason,
            "REQUEST_NO": req_no or f"R{rid}", "REQUEST_ID": rid, "ORDER_ID": rid * 10 + order,
            "TESTITEM_ID": self._tid, "ORDER_SEQ": order, "TESTITEM_SEQ": seq,
            "RESULT_YN": yn, "RETEST_ITEM_YN": retest, "BIZPROCESS_CD": BIZ_CD[tt],
        })


def _dates(i: int, months: int = 0) -> dict:
    lot_d = date(2023, 1, 5) + timedelta(days=14 * i)
    req_d = lot_d + timedelta(days=3 + 30 * months)
    exp_d = lot_d + timedelta(days=1096)
    return {"req_date": req_d.isoformat(), "lot_date": lot_d.isoformat(),
            "exp_date": exp_d.isoformat()}


P1_LOTS = [f"23{n:03d}" for n in range(1, 15)] + [f"24{n:03d}" for n in range(1, 11)]
P2_LOTS = [f"23{n:03d}" for n in range(101, 113)]


def _finished(b: _Builder, code: str, lots: list[str], rng: random.Random, shift: float,
              rules: bool) -> None:
    for i, lot in enumerate(lots):
        d = _dates(i)
        common = dict(code=code, tt=TT_FIN, lot=lot, **d)
        v = 100.0 + shift + rng.gauss(0, 1.0)
        if code == P1 and lot == "23010":
            v = 104.5                                   # 관리이탈 후보
        v = round(v, 1)
        if rules and code == P1 and lot == "23007":
            # 적부 N/A 원시험(1차) + 재시험 최종(2차) — 원시험은 D-4 잠정 규칙으로 빠진다
            b.add(group="함량", item="성분가", std="95.0 ~ 105.0 %", num=92.0, yn="A",
                  retest="Y", order=1, rule=None, reason="재시험 원값(잠정)", **common)
            b.add(group="함량", item="성분가", std="95.0 ~ 105.0 %", num=v, order=2, **common)
        else:
            b.add(group="함량", item="성분가", std="95.0 ~ 105.0 %", num=v, **common)
        if rules and code == P1 and lot == "23001":
            # 거짓 0 — 원문은 숫자인데 저장 숫자만 0
            b.add(group="함량", item="성분가", std="95.0 ~ 105.0 %", num=0, text="100.20",
                  rule=None, reason="거짓 0", seq=9, **common)

        w = 50.0 + shift / 2 + rng.gauss(0, 0.5)
        if code == P1 and lot in ("24003", "24004", "24005", "24006"):
            w = {"24003": 51.0, "24004": 51.1, "24005": 50.9, "24006": 51.2}[lot]   # 경향
        b.add(group="함량", item="성분나", std="45.0 ~ 55.0 %", num=round(w, 2), seq=2, **common)
        if rules and code == P1 and lot == "23005":
            b.add(group="함량", item="성분나", std="45.0 ~ 55.0 %", num=0, text="49.80",
                  rule=None, reason="거짓 0", seq=8, **common)

        if rules and code == P1 and lot == "23011":
            b.add(group="물리", item="붕해", std="15분 이내", num=None, text="7분 30초", raw=7.5,
                  rule=None, reason="서식 결과(결정 전)", seq=3, **common)
        else:
            b.add(group="물리", item="붕해", std="15분 이내", num=rng.choice([6, 7, 7, 8, 8, 9]),
                  seq=3, **common)

        b.add(group="확인", item="확인시험", std="적합", num=None, text="적합", seq=4, **common)

        u = round(0.10 + rng.gauss(0, 0.02), 3)
        yn = "A" if (rules and code == P1 and lot == "23012") else "Y"    # 홀로 있는 N/A — 그대로
        b.add(group="순도", item="유연물질", std="0.5 % 이하", num=u, yn=yn, seq=5, **common)

        if rules and code == P1:
            hv = 1200 + int(rng.gauss(0, 30))
            if i % 3 == 0:                                  # 쉼표 숫자 — 저장 숫자로 되살림
                b.add(group="물리", item="경도", std="1000 ~ 1500 N", num=None,
                      text=f"{hv:,}", raw=hv, rule=hv, seq=6, **common)
            else:
                b.add(group="물리", item="경도", std="1000 ~ 1500 N", num=hv, seq=6, **common)
            # 같은 시험항목 이름이 다른 대분류에도 있음(D-3①)
            b.add(group="용출", item="성분가", std="Q 80 % 이상", num=round(95 + rng.gauss(0, 2), 1),
                  seq=7, **common)

    if code == P1:
        # 제조번호 빈 줄 — 화면 로트에는 안 보이지만 평균에는 들어간다
        d = _dates(30)
        b.add(code=code, tt=TT_FIN, lot="", group="함량", item="성분가", std="95.0 ~ 105.0 %",
              num=100.3, **d)
        if rules:
            # 빈 제조번호의 N/A 줄은 D-4 묶음에서 뺀다(G4) — 그대로 남는다
            b.add(code=code, tt=TT_FIN, lot="", group="함량", item="성분가",
                  std="95.0 ~ 105.0 %", num=100.1, yn="A", seq=2, **d)


def _stability(b: _Builder, rng: random.Random, rules: bool) -> None:
    for i, lot in enumerate(["23001", "23002", "23003"]):
        months = [3, 6, 9, 12] if lot == "23003" else [0, 3, 6, 9, 12]
        for m in months:
            d = _dates(i, m)
            common = dict(code=P1, tt=TT_LT, lot=lot, month=m, remark=f"기간 : {m}개월", **d)
            v = round(100.0 - 0.15 * m + rng.gauss(0, 0.2), 2)
            if rules and lot == "23002" and m == 6:
                b.add(group="함량", item="성분가", std="95.0 ~ 105.0 %", num=97.0, yn="A",
                      retest="Y", order=1, rule=None, reason="재시험 원값(잠정)", **common)
                b.add(group="함량", item="성분가", std="95.0 ~ 105.0 %", num=v, order=2, **common)
            else:
                b.add(group="함량", item="성분가", std="95.0 ~ 105.0 %", num=v, **common)
            b.add(group="성상", item="성상", std="백색의 정제", num=None, text="백색의 정제", seq=2,
                  **common)


def _build(rules: bool) -> list[dict]:
    b = _Builder()
    rng = random.Random(20261004)
    _finished(b, P1, P1_LOTS, rng, 0.0, rules)
    _finished(b, P2, P2_LOTS, rng, 0.5, rules)
    _stability(b, rng, rules)
    return b.rows


def plain_rows() -> list[dict]:
    return _build(False)


def rule_rows() -> list[dict]:
    return _build(True)


D4_REASON = "재시험 원값(잠정)"


def row_rules_only(rows: list[dict]) -> list[dict]:
    """공통 조회문(_COMMON_CTE) 꼴 — D-4 잠정을 적용하기 전.

    D-4 로 비운 줄은 줄 하나 규칙 값으로 되돌린다. 그런 줄은 거짓 0 이 아니므로(거짓 0 이면 값이
    원래 비어 D-4 에 걸리지 않음) 그 값은 저장 숫자, 저장 숫자가 비었으면 쉼표로 되살린 원값이다.
    """
    out = []
    for r in rows:
        r = dict(r)
        if r["EXCLUDED_REASON"] == D4_REASON:
            num = r["RESULT_VALUE_NUMBER"]
            r["RULE_VALUE"] = num if num is not None else r["RESULT_NUMBER_RAW"]
            r["EXCLUDED_REASON"] = ""
        out.append(r)
    return out


def fake_query(rows: list[dict]):
    """databricks_client.query 를 흉내낸다. 품목 조회(:tt·:code)만 걸러서 돌려준다.

    품목 조회는 공통 조회문(D-4 전)이어야 한다 — 창 함수가 들어 있으면 멈춘다(M1).
    """
    def _q(sql, params=None, large=False):
        params = params or {}
        if "code" in params:
            assert "D4_HAS_OTHER" not in sql and sql.count("OVER (") == 1, "품목 조회에 D-4 창 함수"
            return [r for r in row_rules_only(rows)
                    if r["ITEM_CD"] == params["code"] and r["BIZPROCESS_NM"] == params["tt"]]
        if "SELECT DISTINCT trr.ITEM_CD" in sql:
            seen = {}
            for r in rows:
                if r["BIZPROCESS_NM"] == params.get("tt"):
                    seen.setdefault(r["ITEM_CD"], r["ITEM_NM"])
            return [{"ITEM_CD": k, "ITEM_NM": v} for k, v in sorted(seen.items())]
        raise AssertionError("가짜 조회가 모르는 조회문입니다")
    return _q
