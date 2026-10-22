# -*- coding: utf-8 -*-
"""LIMS 결과 원문(RESULT_VALUE) → OOT 계산용 숫자.

LIMS 는 결과를 글자로 저장하고, 순수 숫자가 아니면 저장 숫자 칸을 0 으로 둔다. 예전에는 순수 숫자만
계산에 써서 '76 ppm', '0.1 %', 'N/D' 같은 결과가 빠졌다(2026-10-22 전수 조사: 정량 기준 결과의 약 15%).
여기서 한 번에 읽고, 화면·엑셀·넘김·알람이 모두 같은 규칙을 쓴다.

규칙(2026-10-22 품질 기준 결정)
- 숫자+단위('76 ppm', '0.1 %', '100 CFU/g') → 숫자.
- 불검출('N/D', '불검출', '검출되지 않음') → 0. '0 ppm' 으로 적은 결과와 같게 평균·σ 에 넣는다.
- 정량한계 미만('<0.05 %', '<100 CFU/g', '10 미만/1g') → 0, 그 값을 LOQ 로 기억한다.
  OOT 상한은 max(평균+kσ, LOQ) — LOQ 이하 값은 높은 쪽 이탈로 보지 않는다.
  불검출·정량한계 미만(검열값) 자체는 높은 쪽·낮은 쪽 모두 이탈로 판정하지 않는다(judge_z).
- 다단계 시험(용출 L1/L2/L3·S1/S2/S3, 함량균일성·질량편차·붕해 (1차)/(2차))은 **1차 결과로만** 트렌딩한다.
  2차 이상 결과는 값 계산에서 빼고, 2차 진입 자체를 이벤트형 OOT 로 따로 본다(kdp_core.stage_events).
- 1차 결과가 한 칸에 여러 개('12 %, 11 %, 12 %, 16 %, 15 %, 16 %')면 평균. 단위 정제 시험(용출·균일성·
  질량편차·붕해)만 — 다른 항목의 여러 값(서로 다른 유연물질 나열 등)은 평균을 내면 뜻이 없어 정성으로 둔다.
- 그 밖의 글자(적합, 서술형 확인시험 등)는 정성 → 계산 제외(예전과 같음).

정규식은 공백을 한 칸으로 접은 뒤(그리고 200자 이하에서만) 돌린다 — 공백이 길게 이어진 원문 하나로
처리 시간이 폭증해 서버가 멈추지 않게(2026-10-22 보안 검토).
"""
from __future__ import annotations

import re
from typing import Optional

STAGE_REASON = "2차 이상 단계(진입 이벤트로 관리)"
CENSORED_KINDS = ("불검출", "정량한계미만")
_MAX_LEN = 200

_UNIT = (r"(?:%|ppm|ppb|mg|㎎|g|mL|ml|μg|µg|㎍|ug|IU|CFU ?/ ?(?:g|mL|ml)|CFU|개 ?/ ?(?:g|mL)|"
         r"/ ?1?(?:g|mL)|cP|mPa·s|°C|℃)")
_NUM = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_RE_NUM_UNIT = re.compile(rf"^({_NUM}) ?({_UNIT})?$", re.I)
_RE_LT = re.compile(rf"^[<≤] ?({_NUM}) ?{_UNIT}?$", re.I)
_RE_LT_KO = re.compile(rf"^({_NUM}) ?{_UNIT}? ?미만 ?{_UNIT}?$", re.I)
_RE_ND = re.compile(r"^(?:N\.? ?/? ?D\.?|불 ?검 ?출|미 ?검 ?출|검출 ?되지 ?않음|검출 ?안 ?됨|not detected)$", re.I)
_RE_NA = re.compile(r"^(?:N ?/? ?A|-|—|)$", re.I)
_NOTE = re.compile(r" ?\(([^()]{0,80})\)$")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_UNIT_DOSE = re.compile(r"용출|균일성|질량편차|붕해")
# 단계 표기는 괄호 안의 꼴만: (L1)(L2)(L3) · (S1)(S2)(S3) · (1차)/(2차) · (질량편차2차)
# — '3차원 구조', '2차 포장', '13차' 같은 이름을 단계로 잘못 읽지 않게(2026-10-22 검토).
_RE_STAGE = re.compile(r"\((?:L|S) ?([1-3])\)|(?<!\d)([1-3])차\)")


def _norm(text) -> str:
    return re.sub(r"\s+", " ", "" if text is None else str(text)).strip()


def _to_float(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def stage_of(testitem_nm: str) -> Optional[int]:
    """시험항목 이름의 단계(1·2·3). 단계 표기가 없으면 None."""
    m = _RE_STAGE.search(_norm(testitem_nm)[:_MAX_LEN])
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def stage_family(testitem_nm: str) -> str:
    """단계 표기를 뺀 시험 이름 — '4 시간 후 용출률(L2)' → '4 시간 후 용출률',
    '함량균일성(1차)' → '함량균일성', '디오스민(질량편차2차)' → '디오스민(질량편차)'."""
    s = _norm(testitem_nm)
    s = re.sub(r"\((?:L|S) ?[1-3]\)", "", s)
    s = re.sub(r"(?<!\d)[1-3]차\)", ")", s)
    return s.replace("()", "").strip()


def is_blank_result(text) -> bool:
    return bool(_RE_NA.match(_norm(text)))


def parse_result(text, testitem_nm: str = "", group_nm: str = "") -> tuple[Optional[float], str, Optional[float]]:
    """결과 원문 → (값, 해석 종류, LOQ). 값이 None 이면 계산 제외.

    해석 종류: 숫자 · 숫자+단위 · 불검출 · 정량한계미만 · 여러값평균 · 2차이상 · 정성 · 빈값
    """
    st = stage_of(testitem_nm)
    if st is not None and st >= 2:
        return None, "2차이상", None
    s = _norm(text)
    if _RE_NA.match(s):
        return None, "빈값", None
    if len(s) > _MAX_LEN:
        return None, "정성", None
    note = ""
    m = _NOTE.search(s)
    if m and not s.startswith("("):
        note, s = m.group(1), s[:m.start()].strip()
    if _RE_ND.match(s):
        return 0.0, "불검출", None
    m = _RE_LT.match(s) or _RE_LT_KO.match(s)
    if m:
        return 0.0, "정량한계미만", _to_float(m.group(1))
    m = _RE_NUM_UNIT.match(s)
    if m:
        v = _to_float(m.group(1))
        if v is None:
            return None, "정성", None
        if re.search(r"LOQ|정량 ?한계", note, re.I):        # '0.00 % (LOQ 이하)'
            return 0.0, "불검출", None
        return v, ("숫자" if not m.group(2) else "숫자+단위"), None
    # 1차 단위 정제 시험의 여러 값('12 %, 11 %, …') → 평균. 천 단위 쉼표('1,050 mg')는 값 구분이 아니다.
    if _UNIT_DOSE.search(f"{group_nm} {testitem_nm}"):
        parts = [p.strip() for p in re.split(r"[,;]", _THOUSANDS.sub("", s)) if p.strip()]
        if len(parts) >= 2:
            vals = []
            for p in parts:
                mm = _RE_NUM_UNIT.match(p)
                v = _to_float(mm.group(1)) if mm else None
                if v is None:
                    vals = []
                    break
                vals.append(v)
            if vals:
                return sum(vals) / len(vals), "여러값평균", None
    return None, "정성", None


def judge_z(z, v, loq: Optional[float], censored: bool = False):
    """판정용 z — 화면·엑셀·넘김·알람·관리도가 모두 이 값으로 판정·표시한다.

    - 불검출·정량한계 미만(검열값)은 어느 쪽으로도 이탈로 보지 않는다(0).
    - OOT 상한 = max(평균+kσ, LOQ): LOQ 이하 값의 높은 쪽 z 는 0(그때 'v > max(μ+kσ, LOQ)' ⇔ 'z > k').
    - 그 밖에는 z 그대로(NaN 도 그대로).
    """
    if z is None or z != z:
        return z
    if censored:
        return 0.0
    if loq is not None and v is not None and v == v and v <= loq and z > 0:
        return 0.0
    return z


def loq_floor_z(z, v, loq: Optional[float]):
    """judge_z 의 예전 이름(검열 여부 없이 LOQ 규칙만)."""
    return judge_z(z, v, loq, False)
