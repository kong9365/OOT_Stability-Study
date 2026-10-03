# -*- coding: utf-8 -*-
"""a4ef25c 응답을 굳힌 정답 파일의 경우 목록 — 만들기(make_golden_a4ef25c.py)와 시험이 함께 쓴다."""
from __future__ import annotations

import json
import os

import oot_fake_rows as F

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_a4ef25c")

# (이름, 자료, 부르는 함수) — 함수는 kdp_core 모듈을 받아 응답을 돌려준다.
LOT_CASES = [
    ("lots_P1_all", "plain", lambda c: c.oot_lot_summary(F.P1, F.TT_FIN, None)),
    ("lots_P1_2023", "plain", lambda c: c.oot_lot_summary(F.P1, F.TT_FIN, "2023")),
    ("lots_P1_2024", "plain", lambda c: c.oot_lot_summary(F.P1, F.TT_FIN, "2024")),
    ("lots_P1_whole", "plain", lambda c: c.oot_lot_summary(F.P1, F.TT_FIN, "전체")),
    ("lots_P2_all", "plain", lambda c: c.oot_lot_summary(F.P2, F.TT_FIN, None)),
    ("lots_P1_LT", "plain", lambda c: c.oot_lot_summary(F.P1, F.TT_LT, None)),
    ("lots_none", "plain", lambda c: c.oot_lot_summary("99999", F.TT_FIN, None)),
]

# 안정성 분석 · APQR 묶어 보기 — 규칙 줄이 섞인 자료로도 한 글자도 같아야 한다(M1).
UNCHANGED_CASES = [
    ("stab_P1_LT", "rules", lambda c: c.stability_analysis(F.P1, F.TT_LT)),
    ("stab_P1_LT_indep", "rules",
     lambda c: c.stability_analysis(F.P1, F.TT_LT, method="independent", test_item="성분가")),
    ("stab_P1_LT_batch", "rules", lambda c: c.stability_analysis(F.P1, F.TT_LT, batch="23002")),
    ("stab_P1_FIN", "rules", lambda c: c.stability_analysis(F.P1, F.TT_FIN)),
    ("stabtab_P1_LT", "rules", lambda c: c.stability_tables(F.P1, F.TT_LT)),
    ("stabtab_P1_LT_batch", "rules", lambda c: c.stability_tables(F.P1, F.TT_LT, batch="23003")),
    ("pooled_all", "rules", lambda c: c.group_pooled_all([F.P1, F.P2], F.TT_FIN)),
    ("pooled_all_2023", "rules", lambda c: c.group_pooled_all([F.P1, F.P2], F.TT_FIN, "2023")),
    ("pooled_one", "rules", lambda c: c.group_pooled([F.P1, F.P2], F.TT_FIN, "성분가")),
    ("pooled_one_hard", "rules", lambda c: c.group_pooled([F.P1], F.TT_FIN, "경도")),
    ("group_items", "rules", lambda c: c.group_test_items([F.P1, F.P2], F.TT_FIN)),
    ("group_years", "rules", lambda c: c.group_years([F.P1, F.P2], F.TT_FIN)),
    ("stab_P1_LT_plain", "plain", lambda c: c.stability_analysis(F.P1, F.TT_LT)),
    ("pooled_all_plain", "plain", lambda c: c.group_pooled_all([F.P1, F.P2], F.TT_FIN)),
]

ROWS = {"plain": F.plain_rows, "rules": F.rule_rows}


def dumps(obj) -> str:
    """응답을 글자로 — 키 순서까지 그대로(API 가 내보내는 순서)."""
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def golden_path(name: str) -> str:
    return os.path.join(GOLDEN_DIR, name + ".json")
