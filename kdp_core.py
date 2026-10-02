# -*- coding: utf-8 -*-
"""
kdp_core.py — 광동 품질·시험 통합 대시보드 백엔드 로직 (Streamlit 비의존).

FastAPI(dashboard_api.py)와 필요 시 다른 진입점이 공유하는 순수 Python 모듈.
Databricks `광동제약_gmp_lims`(수정판 LIMS 결과, databricks_client.py)에서 데이터를 받아
OOT 판정 / 안정성 회귀 / ANCOVA를 계산한다.

핵심 함수
  - oot_products(test_type)            : (품목코드, 품목) 목록
  - oot_lot_summary(code, test_type)   : LOT별 정상/주의/관리이탈/정성 카운트 + OOT 항목
  - stability_analysis(code, ...)      : 시점별 회귀·유효기간·시점간 OOT·ANCOVA
"""
from __future__ import annotations

import csv
import gzip
import io
import os
import pickle
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

import databricks_client as dbx
from stability import analyze_dataframe, ci_bound  # 검증된 회귀 엔진 재사용

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=False)

# 데이터 출처: Databricks `광동제약_gmp_lims` (bronze, 서비스 계정 OAuth M2M). 인증·SQL 상세는 databricks_client.py.
LIMS_CATALOG = "광동제약_gmp_lims"
PLANT_CD = "005"

# 시험종류 — Tableau vf_시험종류 서버측 필터값(완제품 기본). 안정성 종류는 '안정성' 포함.
# 시험종류 목록(드롭다운 폴백). Tableau 뷰 'OOT_추출용'은 vf_시험종류 파라미터로 필터되며
# CSV에 '시험종류' 컬럼이 없어 동적 조회 불가 → 유효 파라미터 값을 여기서 수동 관리(폴백)한다.
# 근본 해결: 경량 뷰 '시험종류목록'(oot_test_types 참조) 생성 시 이 목록을 자동 대체.
# ※ 2026-07 Tableau 필터 전체 18종 반영.
OOT_TEST_TYPES = [
    "완제품", "의약외품(완제품)", "반제품", "원료시험", "직접자재", "표시자재",
    "시험기기 및 기구", "제조용수시험", "배지성능시험", "환경시험", "기타시험",
    "Qualification", "Validation",
    "장기 안정성시험(Long Term)", "가속 안정성시험(Acclerated)",
    "시판후 안정성시험(Ongoing Stability)",
    "4b장기 안정성시험(LT4b)", "4b시판후 안정성시험(OS4b)",
]
STAB_TEST_TYPES = [t for t in OOT_TEST_TYPES if "안정성" in t]

# 안정성 차트 배치 색상 팔레트(디자인 일치)
BATCH_COLORS = ["#E5310F", "#1F7A52", "#B8893B", "#2563eb", "#9333ea", "#0891b2"]

# ── 데이터 캐시(기존 Tableau 연동과 동일한 캐시 전략 유지) ───────────────────
_LOCK = threading.Lock()

# 조회 결과(CSV 텍스트) 인메모리 TTL 캐시 — 같은 params 반복 조회를 네트워크 없이 즉시 반환.
_DATA_CACHE: dict[str, tuple[str, float]] = {}   # key -> (csv_text, wall_ts)
_CACHE_TTL = float(os.getenv("KDP_CACHE_TTL_SEC", "300"))
# 디스크 영속 캐시 — 서버 재시작 후에도 이전 조회 데이터를 즉시 재사용(Databricks 재조회 생략).
_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".kdp_data_cache.pkl.gz")


def _save_cache_disk() -> None:
    """데이터 캐시를 디스크에 저장(실패 무시)."""
    try:
        with _LOCK:
            snap = dict(_DATA_CACHE)
        tmp = _CACHE_FILE + ".tmp"
        with gzip.open(tmp, "wb") as f:
            pickle.dump(snap, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, _CACHE_FILE)
    except Exception:
        pass


def _load_cache_disk() -> int:
    """디스크 캐시에서 TTL 이내 항목을 메모리로 적재. 적재 수 반환."""
    try:
        if not os.path.exists(_CACHE_FILE):
            return 0
        with gzip.open(_CACHE_FILE, "rb") as f:
            snap = pickle.load(f)
        now = time.time()
        n = 0
        with _LOCK:
            for k, v in snap.items():
                text, ts = v
                if (now - ts) < _CACHE_TTL:
                    _DATA_CACHE[k] = (text, ts)
                    n += 1
        return n
    except Exception:
        return 0


def clear_data_cache() -> int:
    """데이터 캐시 전체 무효화('데이터 새로고침'). 무효화 항목 수 반환."""
    with _LOCK:
        n = len(_DATA_CACHE)
        _DATA_CACHE.clear()
        _testtype_cache["types"] = None            # 시험종류 목록도 다음 조회 시 재조회
    try:
        if os.path.exists(_CACHE_FILE):
            os.remove(_CACHE_FILE)
    except Exception:
        pass
    return n


# ── Databricks 조회 SQL (수정판 LIMS 결과 — gold 뷰 결함을 bronze에서 직접 보정) ──
# 상세: Databricks/DATABRICKS_LIMS_INTEGRATION.md §7.1·§7.3. PLANT_CD=005, 차수(ORDER_ID)까지
# 조인해 중복 제거, 문자 결과는 RESULT_VALUE_NUMBER에서 제외(try_cast 성공 시만 채움).
_RESULTS_CTE = f"""
WITH results AS (
  SELECT
    trr.ITEM_CD,
    CASE WHEN trim(coalesce(trr.ITEM_NM_REPORT,'')) = '' THEN cii.ITEM_NM ELSE trr.ITEM_NM_REPORT END AS ITEM_NM,
    trr.LOT_NO, qbm.BIZPROCESS_NM, ttr.TESTITEM_NM, ttr.GROUP_NM, ttr.STANDARD_TEXT,
    CASE WHEN try_cast(ttr.RESULT_VALUE AS DOUBLE) IS NOT NULL THEN ttr.RESULT_VALUE_NUMBER END AS RESULT_VALUE_NUMBER,
    try_cast(nullif(trr.REQUEST_DATE,'') AS DATE) AS REQUEST_DATE,
    try_cast(nullif(trr.LOT_DATE,'') AS DATE) AS LOT_DATE,
    try_cast(nullif(trr.EXPIRE_DATE,'') AS DATE) AS EXPIRE_DATE,
    trr.REQUEST_REMARK
  FROM `{LIMS_CATALOG}`.bronze.lims_dbo_test_request_receive trr
  LEFT JOIN `{LIMS_CATALOG}`.bronze.lims_dbo_test_order_result tor
    ON tor.PLANT_CD=trr.PLANT_CD AND tor.REQUEST_ID=trr.REQUEST_ID
  LEFT JOIN `{LIMS_CATALOG}`.bronze.lims_dbo_test_testitem_result ttr
    ON ttr.PLANT_CD=tor.PLANT_CD AND ttr.REQUEST_ID=tor.REQUEST_ID AND ttr.ORDER_ID=tor.ORDER_ID
  LEFT JOIN `{LIMS_CATALOG}`.bronze.lims_dbo_cm_item_info cii
    ON cii.PLANT_CD=trr.PLANT_CD AND cii.ITEM_CD=trr.ITEM_CD
  LEFT JOIN `{LIMS_CATALOG}`.bronze.lims_dbo_qm_bizprocess_master qbm
    ON qbm.PLANT_CD=trr.PLANT_CD AND qbm.BIZPROCESS_CD=trr.BIZPROCESS_CD
  WHERE trr.PLANT_CD='{PLANT_CD}' AND ttr.TESTITEM_ID IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY trr.PLANT_CD,trr.REQUEST_ID,tor.ORDER_ID,ttr.TESTITEM_ID
    ORDER BY ttr.UPDATE_TIME DESC, tor.UPDATE_TIME DESC
  )=1
)
"""


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _row_to_korean(r: dict) -> dict:
    """Databricks 결과행(영문 컬럼) → 기존 Tableau 'OOT_추출용' CSV와 동일한 한글 컬럼 dict.

    확인_평균·확인_표준편차·OOT_구간분류_히트맵은 Tableau 계산 필드였던 자리로, 이 값들은
    kdp_core의 사업 로직(oot_lot_summary 등)이 선택 연도 범위로 항상 자체 재계산하므로
    여기서는 '정량(수치) 결과 여부' 플래그로만 채운다(1=정량, 0=정성/결과없음).
    """
    v = r.get("RESULT_VALUE_NUMBER")
    is_quant = v is not None
    vs = "" if v is None else str(v)
    return {
        "품목코드": r.get("ITEM_CD") or "", "품목": r.get("ITEM_NM") or "",
        "제조번호": r.get("LOT_NO") or "", "시험항목": r.get("TESTITEM_NM") or "",
        "대분류": r.get("GROUP_NM") or "", "시험기준": r.get("STANDARD_TEXT") or "",
        "LOT결과_0제외": vs, "확인_평균": vs, "확인_표준편차": "1" if is_quant else "0",
        "OOT_구간분류_히트맵": "",
        "의뢰일자": r.get("REQUEST_DATE") or "", "제조일자": r.get("LOT_DATE") or "",
        "유효기한": r.get("EXPIRE_DATE") or "", "의뢰 특이사항": r.get("REQUEST_REMARK") or "",
    }


_FULL_FIELDS = ["품목코드", "품목", "제조번호", "시험항목", "대분류", "시험기준",
               "LOT결과_0제외", "확인_평균", "확인_표준편차", "OOT_구간분류_히트맵",
               "의뢰일자", "제조일자", "유효기한", "의뢰 특이사항"]


def _rows_to_csv(rows: list[dict], fields: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _fetch_csv(params: dict) -> str:
    """Databricks 조회 → 기존 Tableau 뷰 CSV와 동일한 형태의 텍스트(네트워크 호출).

    params는 기존 Tableau 뷰 파라미터 이름을 그대로 쓴다(vf_시험종류/vf_품목코드) — 호출부 불변.
    vf_품목코드가 없으면(품목 목록 조회) 가벼운 DISTINCT 조회만 수행한다.
    """
    test_type = params.get("vf_시험종류")
    item_code = params.get("vf_품목코드")
    if item_code:
        clauses, sql_params = ["BIZPROCESS_NM = :tt", "ITEM_CD = :code"], {"tt": test_type, "code": item_code}
        sql = _RESULTS_CTE + "SELECT * FROM results WHERE " + " AND ".join(clauses)
        rows = [_row_to_korean(r) for r in dbx.query(sql, sql_params)]
        return _rows_to_csv(rows, _FULL_FIELDS)
    # 품목 목록만 필요(oot_products) — 전체 조인 없이 가벼운 DISTINCT 조회.
    sql = f"""
SELECT DISTINCT trr.ITEM_CD AS ITEM_CD,
  coalesce(nullif(trr.ITEM_NM_REPORT, ''), cii.ITEM_NM) AS ITEM_NM
FROM `{LIMS_CATALOG}`.bronze.lims_dbo_test_request_receive trr
LEFT JOIN `{LIMS_CATALOG}`.bronze.lims_dbo_cm_item_info cii
  ON cii.PLANT_CD=trr.PLANT_CD AND cii.ITEM_CD=trr.ITEM_CD
LEFT JOIN `{LIMS_CATALOG}`.bronze.lims_dbo_qm_bizprocess_master qbm
  ON qbm.PLANT_CD=trr.PLANT_CD AND qbm.BIZPROCESS_CD=trr.BIZPROCESS_CD
WHERE trr.PLANT_CD='{PLANT_CD}' AND qbm.BIZPROCESS_NM = :tt AND trr.ITEM_CD IS NOT NULL
ORDER BY ITEM_CD
"""
    rows = [{"품목코드": r.get("ITEM_CD") or "", "품목": r.get("ITEM_NM") or ""}
            for r in dbx.query(sql, {"tt": test_type})]
    return _rows_to_csv(rows, ["품목코드", "품목"])


def _view_csv(params: dict) -> str:
    """조회 결과 CSV — 인메모리 TTL 캐시. 같은 params 재조회는 즉시(네트워크 생략)."""
    key = "|".join(f"{k}={v}" for k, v in sorted(params.items()))
    now = time.time()
    with _LOCK:
        hit = _DATA_CACHE.get(key)
        if hit and (now - hit[1] < _CACHE_TTL):
            return hit[0]
    text = _fetch_csv(params)                       # 네트워크는 락 밖에서(병렬 조회 허용)
    with _LOCK:
        _DATA_CACHE[key] = (text, time.time())
    _save_cache_disk()                              # 재시작 후에도 재사용되도록 디스크 저장
    return text


# ── 시험종류 목록: Databricks에서 동적 조회(+안전 폴백) ────────────────────
_testtype_cache: dict[str, object] = {"types": None, "ts": 0.0}
_TESTTYPE_TTL = float(os.getenv("KDP_TESTTYPE_TTL_SEC", "3600"))   # 시험종류는 자주 안 바뀜 → 1시간


def _order_test_types(types: list[str]) -> list[str]:
    """알려진 순서(OOT_TEST_TYPES) 우선, 신규 항목은 뒤, 안정성은 더 뒤로."""
    pref = {t: i for i, t in enumerate(OOT_TEST_TYPES)}
    return sorted(types, key=lambda t: (pref.get(t, len(OOT_TEST_TYPES) + (1000 if "안정성" in t else 0)), t))


def _fetch_test_types() -> Optional[list[str]]:
    """실제 시험 의뢰에 쓰인 시험종류(BIZPROCESS_NM) distinct. 조회 실패 시 None(→폴백)."""
    sql = f"""
SELECT DISTINCT qbm.BIZPROCESS_NM AS BIZPROCESS_NM
FROM `{LIMS_CATALOG}`.bronze.lims_dbo_test_request_receive trr
JOIN `{LIMS_CATALOG}`.bronze.lims_dbo_qm_bizprocess_master qbm
  ON qbm.PLANT_CD=trr.PLANT_CD AND qbm.BIZPROCESS_CD=trr.BIZPROCESS_CD
WHERE trr.PLANT_CD='{PLANT_CD}' AND qbm.BIZPROCESS_NM IS NOT NULL
"""
    rows = dbx.query(sql)
    out = [str(r["BIZPROCESS_NM"]).strip() for r in rows if r.get("BIZPROCESS_NM")]
    return out or None


def fetch_oot_rows_for_types(test_types: list[str]) -> list[dict]:
    """자동 알람(oot_alarm.py)용 — 지정된 전 시험종류를 한 번에 조회하고 Databricks에서
    품목·시험종류·시험항목별 평균/표준편차/Z-score까지 계산해 ±2σ 초과 후보만 반환한다.

    kdp_core의 다른 조회(_product_df 등)는 선택 연도 범위로 평균·표준편차를 자체 재계산하므로
    원천 확인_표준편차가 '정량 여부' 플래그로만 있어도 충분하지만, 이 알람 경로는 그 값을
    그대로 메일 본문·발송이력(oot_alarm_sent.csv)에 적는다 — 따라서 여기서는 전체 이력 기준
    실제 평균·표준편차를 계산해 돌려준다(기존 Tableau 'OOT_구간분류_히트맵'과 동일한 역할).

    반환: 기존 Tableau CSV와 동일한 한글 키 dict 목록(+시험종류), ±2σ 이내(정상)는 제외.
    """
    if not test_types:
        return []
    params = {f"tt{i}": t for i, t in enumerate(test_types)}
    placeholders = ", ".join(f":{k}" for k in params)
    sql = _RESULTS_CTE + f"""
, scored AS (
  SELECT *,
    avg(RESULT_VALUE_NUMBER) OVER (PARTITION BY ITEM_CD, BIZPROCESS_NM, TESTITEM_NM) AS MEAN_VALUE,
    stddev_samp(RESULT_VALUE_NUMBER) OVER (PARTITION BY ITEM_CD, BIZPROCESS_NM, TESTITEM_NM) AS STDDEV_VALUE
  FROM results
  WHERE RESULT_VALUE_NUMBER IS NOT NULL AND ITEM_CD IS NOT NULL AND LOT_NO IS NOT NULL AND TESTITEM_NM IS NOT NULL
    AND BIZPROCESS_NM IN ({placeholders})
)
SELECT *, (RESULT_VALUE_NUMBER - MEAN_VALUE) / nullif(STDDEV_VALUE, 0) AS Z_SCORE FROM scored
WHERE abs((RESULT_VALUE_NUMBER - MEAN_VALUE) / nullif(STDDEV_VALUE, 0)) > 2
"""
    rows = dbx.query(sql, params)
    out = []
    for r in rows:
        z = r.get("Z_SCORE")
        az = abs(float(z)) if z is not None else None
        label = "관리이탈 (±3σ 초과)" if (az is not None and az > 3) else "주의 (±2σ~±3σ)"
        mean_v, sd_v = r.get("MEAN_VALUE"), r.get("STDDEV_VALUE")
        out.append({
            "시험종류": r.get("BIZPROCESS_NM") or "", "품목": r.get("ITEM_NM") or "",
            "품목코드": r.get("ITEM_CD") or "", "제조번호": r.get("LOT_NO") or "",
            "시험항목": r.get("TESTITEM_NM") or "",
            "LOT결과_0제외": "" if r.get("RESULT_VALUE_NUMBER") is None else str(r["RESULT_VALUE_NUMBER"]),
            "OOT_구간분류_히트맵": label,
            "확인_평균": "" if mean_v is None else str(round(float(mean_v), 4)),
            "확인_표준편차": "" if sd_v is None else str(round(float(sd_v), 4)),
        })
    return out


def oot_test_types() -> list[str]:
    """시험종류 드롭다운 목록 — 경량 뷰 동적 조회 우선, 실패 시 하드코딩 폴백. TTL 캐시."""
    with _LOCK:
        cached = _testtype_cache["types"]
        if cached and (time.monotonic() - float(_testtype_cache["ts"]) < _TESTTYPE_TTL):
            return list(cached)                     # type: ignore[arg-type]
    try:
        fetched = _fetch_test_types()
    except Exception:
        fetched = None
    result = _order_test_types(fetched) if fetched else list(OOT_TEST_TYPES)
    with _LOCK:
        _testtype_cache["types"] = result
        _testtype_cache["ts"] = time.monotonic()
    return list(result)


def stab_test_types() -> list[str]:
    """안정성 시험종류(동적 목록에서 파생)."""
    return [t for t in oot_test_types() if "안정성" in t]


# ── 유틸 ─────────────────────────────────────────────────────────────────────
def _num(x) -> float:
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, TypeError):
        return float("nan")


def _oot_status(s) -> str:
    s = str(s or "")
    if "주의" in s:                 # '주의 (±2σ~±3σ)'에 3σ가 들어있어 주의를 먼저 판정
        return "주의"
    if "관리이탈" in s or "초과" in s:
        return "관리이탈"
    if "정상" in s:
        return "정상"
    return "데이터부족"


_QUAL_KW = ("불검출", "성상", "현탁액", "반점", "Rf", "S/N", "일치", "검액",
            "음성", "양성", "적합하다", "투명", "색상")
# 단위 토큰(긴 것부터 매칭 — ng/pg 등 g로 시작하는 단위가 g에 먹히지 않도록 순서 중요)
_UNIT = r"(?:mg|㎎|ng|㎍|μg|㎍|ug|pg|kg|g|%|ppm|ppb|IU|CFU)"


def parse_criterion(text):
    """시험기준 텍스트 → (규격하한, 규격상한). stability_page.parse_criterion 과 동일 규칙."""
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return (None, None)
    s = str(text).strip()
    if not s or any(k in s for k in _QUAL_KW):
        return (None, None)
    m = re.search(r"(\d+\.?\d*)\s*[∼~〜–—\-]\s*(\d+\.?\d*)", s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    m = re.search(r"(\d+\.?\d*)\s*" + _UNIT, s)
    if not m:
        return (None, None)
    val = float(m.group(1))
    if "이하" in s or "미만" in s or "이내" in s:   # '이내'도 상한(붕해 등)
        return (None, val)
    if "이상" in s or "초과" in s:
        return (val, None)
    return (None, None)


def parse_unit(text):
    """시험기준 텍스트 → 단위 문자열(%, mg/100mL, ppm 등). 없으면 ''."""
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    s = str(text)
    if any(k in s for k in _QUAL_KW):
        return ""
    # 숫자 뒤 단위 토큰(복합단위 mg/100mL·CFU/mL, 분모의 한글 단위 mg/1환·mg/1정 포함).
    m = re.search(r"\d[\d.,]*\s*(%|[A-Za-zµμ㎍㎎]+(?:\s*/\s*[\dA-Za-z가-힣]+)*)", s)
    if not m:
        return ""
    return re.sub(r"\s+", "", m.group(1))


def spec_text(lo, hi, unit):
    """규격 (하한, 상한, 단위) → 사람이 읽는 표기."""
    u = (" " + unit) if unit else ""
    if lo is not None and hi is not None:
        return f"{lo:g} ~ {hi:g}{u}".strip()
    if lo is not None:
        return f"{lo:g}{u} 이상".strip()
    if hi is not None:
        return f"{hi:g}{u} 이하".strip()
    return "—"


def _year_of(lot: str) -> str:
    return ("20" + lot[:2]) if lot[:2].isdigit() else "기타"


def _parse_date(s):
    """'2021. 8. 13.' / '2024-08-12' → date. 실패 시 None."""
    from datetime import date
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", str(s or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _approved_months(mfg, exp):
    """허가 유효기간(개월) = 유효기한 − 제조일자. 가장 가까운 정수 개월로 반올림."""
    a, b = _parse_date(mfg), _parse_date(exp)
    if not a or not b:
        return None
    days = (b - a).days
    return int(round(days / 30.4375)) if days > 0 else None


# ── OOT ──────────────────────────────────────────────────────────────────────
def oot_products(test_type: str = "완제품") -> list[dict]:
    """(품목코드, 품목) 고유 목록. 2열만 추출(경량)."""
    text = _view_csv({"vf_시험종류": test_type})
    seen: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text)):
        code = (row.get("품목코드") or "").strip()
        if code and code not in seen:
            seen[code] = (row.get("품목") or "").strip()
    return [{"code": k, "name": v} for k, v in sorted(seen.items())]


def prewarm() -> None:
    """기동 시 자주 쓰는 데이터 캐시 적재(백그라운드 호출용). 실패 무시.
    ① 완제품 품목목록  ② 자주/크게 조회되는 품목의 데이터(완제품·장기)를 미리 받아둠.
    대상 품목코드는 env KDP_WARM_CODES(콤마구분)로 조정. 캐시 6시간이면 재기동 후에도 빠름."""
    _load_cache_disk()                              # 재시작 후 이전 캐시 즉시 재사용(디스크)
    try:
        oot_products("완제품")
    except Exception:
        pass
    codes = [c.strip() for c in os.getenv(
        "KDP_WARM_CODES", "10024,29228,23260,23262,23263,23149,23150").split(",") if c.strip()]
    for code in codes:
        for tt in ("완제품", "장기 안정성시험(Long Term)"):
            try:
                _product_df(code, tt)   # _DATA_CACHE 적재(첫 사용자 조회를 즉시로)
            except Exception:
                pass


def _product_df(code: str, test_type: str) -> pd.DataFrame:
    text = _view_csv({"vf_품목코드": str(code), "vf_시험종류": test_type})
    return pd.DataFrame(list(csv.DictReader(io.StringIO(text))))


def _we_run_rules(zs: list) -> tuple:
    """Western Electric 연속 규칙(동일 방향).
    Rule2: 연속 3점 중 2점이 2σ 초과 · Rule3: 연속 5점 중 4점이 1σ 초과.
    입력 zs는 시간순 z-score. 규칙에 관여하는(한계 초과) 점만 True로 표시.
    반환: (r2_flags, r3_flags) — 각 zs와 같은 길이의 bool 리스트."""
    n = len(zs)
    r2 = [False] * n
    r3 = [False] * n
    for i in range(2, n):                                  # Rule2: 3점 창
        for side in (1, -1):
            hits = [j for j in (i - 2, i - 1, i) if zs[j] * side > 2]
            if len(hits) >= 2:
                for j in hits:
                    r2[j] = True
    for i in range(4, n):                                  # Rule3: 5점 창
        for side in (1, -1):
            hits = [j for j in range(i - 4, i + 1) if zs[j] * side > 1]
            if len(hits) >= 4:
                for j in hits:
                    r3[j] = True
    return r2, r3


def oot_lot_summary(code: str, test_type: str = "완제품", year: Optional[str] = None) -> dict:
    """선택 품목의 LOT별 판정 요약. 한 번의 Databricks 호출로 전 LOT 계산.

    year 지정('전체' 제외) 시: 해당 연도(제조번호 앞 2자리) LOT만 대상으로
    시험항목별 평균·±3σ를 재계산해 OOT를 재판정(APQR 연도별 관점).
    year 미지정/'전체' 시에도 아래 로직이 항상 전 이력 기준으로 자체 재계산한다
    (원천 확인_평균/확인_표준편차는 쓰지 않음 — _row_to_korean 주석 참고).

    반환: {code, name, lots:[{lot, year, normal, warn, crit, qual, flagged,
            items:[{name, val, mean, sd, z, status}]}], years:[...]}
    """
    pdf = _product_df(code, test_type)
    if pdf.empty or "제조번호" not in pdf.columns:
        return {"code": code, "name": "", "lots": [], "years": ["전체"]}

    name = str(pdf.get("품목", pd.Series([""])).iloc[0]) if "품목" in pdf else ""
    val_col = next((c for c in ["LOT결과_0제외", "시험결과_유효", "평균 시험결과"] if c in pdf.columns), None)
    pdf["_상태"] = pdf["OOT_구간분류_히트맵"].map(_oot_status)
    pdf["_sd_t"] = pdf["확인_표준편차"].map(_num)          # Tableau σ(정량 판별용)
    pdf["_sd"] = pdf["_sd_t"]
    pdf["_mu"] = pdf["확인_평균"].map(_num)
    pdf["_v"] = pdf[val_col].map(_num) if val_col else float("nan")
    pdf["_year"] = pdf["제조번호"].astype(str).map(_year_of)
    # 시계열 정렬키(_ord): 의뢰일자(원료 등 제조번호 채번이 불규칙한 경우) 우선, 없으면 제조번호.
    # 원료시험은 제조번호가 M25-002/ZA0262302처럼 혼재 → 의뢰일자순이 실제 접수 순서.
    date_col = next((c for c in ["의뢰일자", "접수일자", "제조일자"] if c in pdf.columns), None)
    if date_col:
        _d = pdf[date_col].map(lambda s: (_parse_date(s).isoformat() if _parse_date(s) else ""))
        # 날짜가 대부분 있으면 날짜 우선(동일 날짜는 제조번호로 안정 정렬), 아니면 제조번호.
        has_date = (_d != "").mean() >= 0.5 if len(_d) else False
        pdf["_ord"] = (_d + "|" + pdf["제조번호"].astype(str)) if has_date else pdf["제조번호"].astype(str)
    else:
        pdf["_ord"] = pdf["제조번호"].astype(str)

    # 선택기용 연도 목록은 전체 데이터 기준(필터 전)
    years = sorted({y for y in pdf["_year"] if y != "기타"}, reverse=True)
    if bool((pdf["_year"] == "기타").any()):
        years.append("기타")

    sample_base = {}   # 시험항목 -> {"n"} (기준선 표본 정보)
    base = {}          # 시험항목 -> {"mu","sd","sd_raw","R","n"}
    sample_info = None                 # 상단 표본 안내(로트 기준)
    rule_tags = {}                     # pdf index -> [연속규칙 태그]
    MIN = 20
    # 표시·판정 대상 로트: 연도 선택 시 그 연도만(보충 없음), '전체'면 전 이력.
    # 어느 경우든 μ·σ는 대상 로트의 실제 값으로 재계산(Tableau 사전값 미사용) → 일관 판정.
    if bool(year) and year != "전체":
        pdf = pdf[pdf["_year"] == year].copy()                  # 그 연도 로트만
    else:
        pdf = pdf.copy()                                        # 전체 이력(=최대한 많은 표본)

    if not pdf.empty:
        nlot = int(pdf["제조번호"].astype(str).nunique())
        sample_info = {"lots": nlot, "min": MIN, "short": nlot < MIN,
                       "mode": ("전체" if (not year or year == "전체") else str(year))}
        # 시험항목별 μ·σ(ddof=1) = 대상 로트의 정량 값(정성 σ_t≤0 제외).
        # σ 하한(분해능 보정): 보고값이 정수 등으로 반올림돼(예: 수분 24) σ가 측정 분해능보다
        # 작아지면 1단위 차이가 3σ로 과대 판정됨. 분해능 R(서로 다른 값 간 최소 간격)을 σ 하한으로
        # 적용 → 1단위 차이 ≈ 1σ. 연속(잘 분해된) 데이터는 R이 작아 자동 무효(완제품 등 영향 없음).
        for it, grp in pdf.groupby("시험항목"):
            vals = grp.loc[grp["_sd_t"] > 0, "_v"].dropna().tolist()
            n = len(vals)
            mu = float(np.mean(vals)) if n >= 2 else float("nan")
            sd_raw = float(np.std(vals, ddof=1)) if n >= 2 else float("nan")
            uniq = sorted(set(vals))
            R = min((b - a for a, b in zip(uniq, uniq[1:])), default=0.0)   # 분해능
            sd = max(sd_raw, R) if (n >= 2 and not np.isnan(sd_raw)) else sd_raw
            base[str(it)] = {"mu": mu, "sd": sd, "sd_raw": sd_raw, "R": R, "n": n}
            sample_base[str(it)] = {"n": n}

        pdf["_mu"] = pdf["시험항목"].map(lambda it: base.get(str(it), {}).get("mu", float("nan")))
        pdf["_sd"] = pdf["시험항목"].map(lambda it: base.get(str(it), {}).get("sd", float("nan")))
        pdf.loc[pdf["_sd_t"] <= 0, "_sd"] = float("nan")        # 정성 행은 제외 유지

        # ── 판정: 단일점(±3σ/±2σ) + 관리도 연속 규칙(Western Electric Rule 2·3) ──
        # Rule1: 1점 >3σ = 관리이탈 · Rule2: 연속 3점 중 2점 >2σ(동일방향) = 경향이탈
        # Rule3: 연속 5점 중 4점 >1σ(동일방향) = 경향이탈. 시계열은 제조번호(로트) 오름차순.
        status_map = {}
        for it, grp in pdf.groupby("시험항목"):
            q = grp[(grp["_sd"] > 0) & grp["_v"].notna() & grp["_mu"].notna()]
            q = q.sort_values("_ord")                           # 시간순(의뢰일자/제조번호 오름차순)
            idx = q.index.tolist()
            zs = ((q["_v"] - q["_mu"]) / q["_sd"]).tolist()
            r2, r3 = _we_run_rules(zs)
            for k, ix in enumerate(idx):
                z, az, tags = zs[k], abs(zs[k]), []
                if r2[k]:
                    tags.append("연속3중2점 >2σ")
                if r3[k]:
                    tags.append("연속5중4점 >1σ")
                if az > 3:
                    st = "관리이탈"
                elif tags:
                    st = "경향이탈"
                elif az > 2:
                    st = "주의"
                else:
                    st = "정상"
                status_map[ix] = st
                if tags:
                    rule_tags[ix] = tags
        pdf["_상태"] = pdf.index.map(lambda i: status_map.get(i, "데이터부족"))

    lots = []
    for lot, g in pdf.groupby(pdf["제조번호"].astype(str)):
        lot = str(lot).strip()
        if not lot:
            continue
        judged = g[g["_sd"] > 0]                       # 정성/데이터부족(σ 0·NULL) 제외
        crit = int((judged["_상태"] == "관리이탈").sum())
        trend = int((judged["_상태"] == "경향이탈").sum())
        warn = int((judged["_상태"] == "주의").sum())
        normal = int((judged["_상태"] == "정상").sum())
        qual = int(len(g) - len(judged))
        def _item(r):
            z = (r["_v"] - r["_mu"]) / r["_sd"] if r["_sd"] else float("nan")
            it = str(r.get("시험항목", ""))
            sb = sample_base.get(it)
            bs = base.get(it, {})
            spec_lo, spec_hi = parse_criterion(r.get("시험기준"))   # 규격 하한·상한(관리도 기준선용)
            sd_raw = bs.get("sd_raw")
            floored = bool(sd_raw is not None and not np.isnan(sd_raw)
                           and r["_sd"] and r["_sd"] > sd_raw + 1e-12)
            return {
                "name": it, "status": r["_상태"],
                "val": None if np.isnan(r["_v"]) else round(float(r["_v"]), 4),
                "mean": None if np.isnan(r["_mu"]) else round(float(r["_mu"]), 4),
                "sd": None if np.isnan(r["_sd"]) else round(float(r["_sd"]), 4),
                "sdRaw": (None if (sd_raw is None or np.isnan(sd_raw)) else round(float(sd_raw), 4)),
                "sdFloored": floored,                      # 분해능 σ 하한 적용 여부
                "z": None if np.isnan(z) else round(float(z), 3),
                "baseN": (sb["n"] if sb else None),        # 기준선 표본수
                "rules": rule_tags.get(r.name, []),        # 연속규칙 태그(경향이탈)
                "specLo": spec_lo, "specHi": spec_hi,      # 규격 하한/상한(mg 등)
                "spec": (str(r.get("시험기준")).strip() if r.get("시험기준") is not None else None),
            }
        _flag = judged[judged["_상태"].isin(["주의", "관리이탈", "경향이탈"])]
        items = [_item(r) for _, r in _flag.iterrows()]
        items.sort(key=lambda it: ({"관리이탈": 3, "경향이탈": 2, "주의": 1}.get(it["status"], 0),
                                   abs(it["z"]) if it["z"] is not None else 0), reverse=True)
        normal_items = [_item(r) for _, r in judged[judged["_상태"] == "정상"].iterrows()]
        normal_items.sort(key=lambda it: abs(it["z"]) if it["z"] is not None else 0, reverse=True)
        seq = str(g["_ord"].iloc[0]) if "_ord" in g else lot     # 시계열 정렬키(의뢰일자|제조번호)
        lots.append({"lot": lot, "year": _year_of(lot), "normal": normal, "warn": warn,
                     "crit": crit, "trend": trend, "qual": qual, "flagged": bool(items),
                     "seq": seq, "items": items, "normalItems": normal_items})

    lots.sort(key=lambda l: l["seq"], reverse=True)              # 최신(의뢰일자/제조번호)순
    return {"code": code, "name": name, "lots": lots, "years": ["전체"] + years,
            "sampleInfo": sample_info}


# ── 동일품목군 (APQR 풀링 OOT) ────────────────────────────────────────────────
def _product_dfs(codes: list[str], test_type: str) -> list[pd.DataFrame]:
    """여러 품목코드를 병렬 조회(_view_csv 캐시 적용). 개별 실패는 빈 DataFrame."""
    codes = [str(c).strip() for c in codes if str(c).strip()]
    if not codes:
        return []

    def _safe(c):
        try:
            return _product_df(c, test_type)
        except Exception:
            return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=min(4, len(codes))) as ex:
        return list(ex.map(_safe, codes))


def group_catalog(test_type: str = "완제품") -> list[dict]:
    """동일품목군 검색용 전체 품목 카탈로그 [{"품목코드","품목명"}, ...]."""
    return [{"품목코드": p["code"], "품목명": p["name"]} for p in oot_products(test_type)]


def group_test_items(codes: list[str], test_type: str = "완제품",
                     year: Optional[str] = None) -> list[str]:
    """선택 코드들에서 유효(σ>0) 시험항목 목록(합집합, 정렬) — 시험항목 선택용.
    year 지정('전체' 제외) 시 해당 연도(제조번호 앞2자리) 레코드만."""
    yr = year if (year and year != "전체") else None
    items: set[str] = set()
    for d in _product_dfs(codes, test_type):
        if d is None or d.empty or "시험항목" not in d.columns:
            continue
        if yr and "제조번호" in d.columns:
            d = d[d["제조번호"].astype(str).map(_year_of) == yr]
            if d.empty:
                continue
        sd = (d["확인_표준편차"].map(_num).tolist()
              if "확인_표준편차" in d.columns else [1.0] * len(d))
        for it, s in zip(d["시험항목"].astype(str).tolist(), sd):
            it = it.strip()
            if it and s > 0:
                items.add(it)
    return sorted(items)


def group_years(codes: list[str], test_type: str = "완제품") -> list[str]:
    """선택 코드들의 데이터에 존재하는 연도(제조번호 앞2자리, 내림차순) — 그룹 연도 선택기용."""
    ys: set[str] = set()
    for d in _product_dfs(codes, test_type):
        if d is None or d.empty or "제조번호" not in d.columns:
            continue
        for lot in d["제조번호"].astype(str):
            y = _year_of(lot)
            if y != "기타":
                ys.add(y)
    return sorted(ys, reverse=True)


def group_records(codes: list[str], test_type: str, test_item: str,
                  year: Optional[str] = None) -> list[dict]:
    """여러 품목코드의 유효 시험 레코드를 병렬 조회 → 시험항목(+연도) 필터 → 풀링 입력 스키마 매핑.

    반환: [{"품목코드","LOT","시험항목","시험결과","시험결과_유효"}, ...]
    - 시험항목은 클라이언트 필터(REST에 vf_시험항목 없음),
    - year 지정('전체' 제외) 시 제조번호 앞2자리로 연도 필터(풀링 전),
    - 유효 판정: 확인_표준편차 > 0(정성·데이터부족 제외 — oot_lot_summary와 동일 규칙),
    - 시험결과 = LOT결과_0제외(대체: 시험결과_유효/평균 시험결과), LOT = 제조번호.
    """
    yr = year if (year and year != "전체") else None
    frames = [d for d in _product_dfs(codes, test_type) if d is not None and not d.empty]
    if not frames:
        return []
    pdf = pd.concat(frames, ignore_index=True)
    if "시험항목" not in pdf.columns:
        return []
    val_col = next((c for c in ["LOT결과_0제외", "시험결과_유효", "평균 시험결과"] if c in pdf.columns), None)
    out = []
    for _, r in pdf.iterrows():
        if str(r.get("시험항목", "")).strip() != test_item:
            continue
        lot = str(r.get("제조번호", "")).strip()
        if yr and _year_of(lot) != yr:                    # 연도 필터(풀링 전)
            continue
        if not (_num(r.get("확인_표준편차")) > 0):        # 정성/데이터부족 제외
            continue
        v = _num(r.get(val_col)) if val_col else float("nan")
        if np.isnan(v):
            continue
        out.append({
            "품목코드": str(r.get("품목코드", "")).strip(),
            "LOT": lot,
            "시험항목": test_item,
            "시험결과": float(v),
            "시험결과_유효": True,
        })
    return out


def group_pooled(codes: list[str], test_type: str, test_item: str,
                 group_id: str = "", year: Optional[str] = None) -> dict:
    """group_records(+연도필터) → oot_group.pool_and_flag → dict. 레코드 <2건이면 ValueError 전파."""
    import oot_group
    recs = group_records(codes, test_type, test_item, year=year)
    res = oot_group.pool_and_flag(recs, [str(c).strip() for c in codes], test_item, group_id=group_id)
    d = oot_group.pooled_to_dict(res)
    d["testType"] = test_type
    return d


def group_pooled_all(codes: list[str], test_type: str = "완제품",
                     year: Optional[str] = None) -> dict:
    """선택 코드들의 **모든 시험항목**을 각각 풀링(연도 반영, APQR 전체 관점).
    유효 레코드 <2건 항목은 제외. 반환: {testType, results:[pooled dict, ...]}(시험항목순)."""
    import oot_group
    cds = [str(c).strip() for c in codes if str(c).strip()]
    results = []
    for it in group_test_items(cds, test_type):        # 전 연도 기준 항목 목록
        recs = group_records(cds, test_type, it, year=year)
        if len(recs) < 2:
            continue
        try:
            res = oot_group.pool_and_flag(recs, cds, it)
        except ValueError:
            continue
        results.append(oot_group.pooled_to_dict(res))
    return {"testType": test_type, "results": results}


# ── 엑셀 리포트 (첨부 양식 build_report 재사용) ────────────────────────────────
def _excel_cfg(sheet: str, 품목: str, 시험종류: str, 시험항목: str,
               시험기준: str, lots: list, values: list) -> dict:
    """build_report용 cfg — 샘플 라벨에 프로젝트 데이터 매핑.
    규격하한(LSL·이상)·규격상한(USL·이하)을 parse_criterion 원값으로 전달 →
    build_report가 규격 유형별로 Cp·K·Cpk·기준일탈을 올바르게 산출한다."""
    lo, hi = parse_criterion(시험기준)
    unit = parse_unit(시험기준)
    spec = str(시험기준 or "").strip()
    # 붕해(시간) 규격: "N분 이내/이하" → 상한 = N (분 값 그대로).
    if hi is None and "붕해" in str(시험항목):
        mt = re.search(r"(\d+\.?\d*)\s*분", spec)
        if mt and re.search(r"이내|이하|미만", spec):
            hi = float(mt.group(1))
            unit = unit or "분"
    # '이하'(상한만) 규격은 하한을 0으로 두어 범위 Cp/K/Cpk 산출(불순물·NMOR 등).
    # 단, 붕해·제제균일성(균일성)·질량편차는 하한을 N/A로 유지 → 단측 Cpk만 산출(기존 방식).
    _NA_LO = ("붕해", "균일성", "질량편차")
    if hi is not None and lo is None:
        _it = str(시험항목)
        if not any(k in _it for k in _NA_LO):
            lo = 0.0
    return {
        "sheet": sheet, "title": f"{품목} {시험종류} {시험항목}".strip(),
        "제품명": 품목, "제조공정": 시험종류, "검사항목": 시험항목,
        "허가기준": spec, "규격하한": lo, "규격상한": hi,
        "단위": unit, "자가기준_1차": spec, "자가기준_2차": None,
        "lots": lots, "values": values,
    }


def _safe_sheet(name: str, used: set) -> str:
    """엑셀 시트명(≤31자·금지문자 제거·중복 회피)."""
    s = re.sub(r"[\\/?*\[\]:]", "_", str(name)).strip()[:31] or "sheet"
    base, i = s, 1
    while s in used:
        i += 1
        s = (base[:27] + f"_{i}")[:31]
    used.add(s)
    return s


def oot_excel(code: str, test_type: str = "완제품", year: Optional[str] = None) -> bytes:
    """OOT 조회(연도 필터 반영)를 첨부 양식 엑셀로. 시험항목당 시트 1개. bytes 반환."""
    import io as _io
    from openpyxl import Workbook
    import oot_excel_report
    pdf = _product_df(code, test_type)
    if pdf.empty or "제조번호" not in pdf.columns:
        raise ValueError("데이터가 없습니다.")
    name = str(pdf.get("품목", pd.Series([""])).iloc[0]) if "품목" in pdf else ""
    val_col = next((c for c in ["LOT결과_0제외", "시험결과_유효", "평균 시험결과"] if c in pdf.columns), None)
    yr = year if (year and year != "전체") else None
    wb = Workbook()
    wb.remove(wb.active)
    used: set = set()
    for item, g in pdf.groupby(pdf["시험항목"].astype(str)):
        item = item.strip()
        if not item:
            continue
        g = g[g["확인_표준편차"].map(_num) > 0]            # 정량만(σ_t>0)
        if yr:
            g = g[g["제조번호"].astype(str).map(_year_of) == yr]
        if g.empty:
            continue
        lots, values = [], []
        for _, r in g.iterrows():
            v = _num(r.get(val_col)) if val_col else float("nan")
            if np.isnan(v):
                continue
            lots.append(str(r.get("제조번호", "")).strip())
            values.append(round(float(v), 6))
        if len(values) < 2:
            continue
        specs = [str(x).strip() for x in g.get("시험기준", pd.Series([], dtype=str)).tolist() if str(x).strip()]
        spec = specs[0] if specs else ""
        cfg = _excel_cfg(_safe_sheet(item, used), name, test_type, item, spec, lots, values)
        cfg["title"] = f"{name} {test_type} {item} · {yr or '전체'}년".strip()
        oot_excel_report.build_report(wb, cfg)
    if not wb.sheetnames:
        raise ValueError("엑셀로 만들 유효한 시험항목이 없습니다(정량·2건 이상 필요).")
    buf = _io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def group_excel(codes: list[str], test_type: str = "완제품",
                year: Optional[str] = None) -> bytes:
    """APQR 풀링(연도 반영) — 선택 코드들의 **전 시험항목**을 시트당 1개로. bytes."""
    import io as _io
    from openpyxl import Workbook
    import oot_excel_report
    cds = [str(c).strip() for c in codes if str(c).strip()]
    frames = [d for d in _product_dfs(cds, test_type) if d is not None and not d.empty]
    if not frames:
        raise ValueError("데이터가 없습니다.")
    pdf = pd.concat(frames, ignore_index=True)
    if "시험항목" not in pdf.columns:
        raise ValueError("시험항목 컬럼이 없습니다.")
    val_col = next((c for c in ["LOT결과_0제외", "시험결과_유효", "평균 시험결과"] if c in pdf.columns), None)
    yr = year if (year and year != "전체") else None
    gname = "동일품목군"
    if "품목" in pdf.columns:
        names = [str(x).strip() for x in pdf["품목"].tolist() if str(x).strip()]
        if names:
            gname = max(set(names), key=names.count)
    wb = Workbook()
    wb.remove(wb.active)
    used: set = set()
    for item, g in pdf.groupby(pdf["시험항목"].astype(str)):
        item = item.strip()
        if not item:
            continue
        g = g[g["확인_표준편차"].map(_num) > 0]            # 정량만
        if yr:
            g = g[g["제조번호"].astype(str).map(_year_of) == yr]
        if g.empty:
            continue
        lots, values = [], []
        for _, r in g.iterrows():
            v = _num(r.get(val_col)) if val_col else float("nan")
            if np.isnan(v):
                continue
            lots.append(str(r.get("제조번호", "")).strip())   # 제조번호만(품목코드 접두 제거)
            values.append(round(float(v), 6))
        if len(values) < 2:
            continue
        specs = [str(x).strip() for x in g.get("시험기준", pd.Series([], dtype=str)).tolist() if str(x).strip()]
        spec = specs[0] if specs else ""
        cfg = _excel_cfg(_safe_sheet(item, used), gname, test_type, item, spec, lots, values)
        cfg["title"] = f"[APQR 참고] {gname} {test_type} {item} · {yr or '전체'}년".strip()
        oot_excel_report.build_report(wb, cfg)
    if not wb.sheetnames:
        raise ValueError("엑셀로 만들 유효한 시험항목이 없습니다(정량·2건 이상 필요).")
    buf = _io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 안정성 ────────────────────────────────────────────────────────────────────
def stability_df(code: str, test_type: str) -> pd.DataFrame:
    """OOT_추출용 → 안정성 long format(제조번호·시험항목·대분류·시점(개월)·결과값·규격)."""
    from lims_parser import parse_month
    is_stab = "안정성" in test_type
    # 시험종류 데이터 + (안정성이면) 완제품 0개월 baseline 을 병렬 조회 → 콜드 로딩 절반.
    rel = None
    if is_stab:
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_main = ex.submit(_product_df, code, test_type)
            f_rel = ex.submit(_product_df, code, "완제품")
            raw = f_main.result()
            try:
                rel = f_rel.result()
            except Exception:
                rel = pd.DataFrame()
    else:
        raw = _product_df(code, test_type)
    if raw.empty:
        return pd.DataFrame()
    rec = []
    for _, row in raw.iterrows():
        month = parse_month(row.get("의뢰 특이사항", ""), test_type)
        val = _num(row.get("LOT결과_0제외", ""))
        if month is None or np.isnan(val):
            continue
        crit = row.get("시험기준", "")
        lo, hi = parse_criterion(crit)
        rec.append({"제조번호": str(row.get("제조번호", "")).strip(),
                    "시험항목": str(row.get("시험항목", "")).strip(),
                    "대분류": str(row.get("대분류", "")).strip(),
                    "시점(개월)": month, "결과값": val,
                    "규격하한": lo if lo is not None else float("nan"),
                    "규격상한": hi if hi is not None else float("nan"),
                    "단위": parse_unit(crit),
                    "제조일자": str(row.get("제조일자", "")).strip(),
                    "유효기한": str(row.get("유효기한", "")).strip()})

    # 0개월 기준값 = 완제품(출하시험) 결과 포함 (ICH·원 LIMS 앱과 동일: 출하시점 = 0개월).
    # 안정성 배치에 매칭되는 출하결과를 0개월 점으로 추가 → 시점 1개 늘어 회귀 가능해짐.
    # rel(완제품)은 위에서 병렬로 미리 조회됨.
    if is_stab and rec and rel is not None:
        if not rel.empty and "제조번호" in rel.columns:
            stab_keys = {(r["제조번호"], r["시험항목"]) for r in rec}
            have0 = {(r["제조번호"], r["시험항목"]) for r in rec if r["시점(개월)"] == 0.0}
            for _, row in rel.iterrows():
                b = str(row.get("제조번호", "")).strip()
                item = str(row.get("시험항목", "")).strip()
                val = _num(row.get("LOT결과_0제외", ""))
                key = (b, item)
                if key not in stab_keys or key in have0 or np.isnan(val):
                    continue
                crit = row.get("시험기준", "")
                lo, hi = parse_criterion(crit)
                rec.append({"제조번호": b, "시험항목": item,
                            "대분류": str(row.get("대분류", "")).strip(),
                            "시점(개월)": 0.0, "결과값": val,
                            "규격하한": lo if lo is not None else float("nan"),
                            "규격상한": hi if hi is not None else float("nan"),
                            "단위": parse_unit(crit),
                            "제조일자": str(row.get("제조일자", "")).strip(),
                            "유효기한": str(row.get("유효기한", "")).strip()})
                have0.add(key)
    return pd.DataFrame(rec)


def _ancova(d: pd.DataFrame) -> Optional[dict]:
    """함량 ~ 시점 + C(제조번호) + 시점:C(제조번호) 순차(Type I) ANOVA.

    교호작용 p < 0.25 → 배치별 개별 회귀, p ≥ 0.25 → 합산 가능(ICH Q1E·α=0.25).
    배치 2개 이상·각 배치 시점 2개 이상일 때만 산출. 불가 시 None.
    """
    bc = d.groupby("제조번호")["시점(개월)"].nunique()
    good = bc[bc >= 2].index
    d = d[d["제조번호"].isin(good)]
    nb = d["제조번호"].nunique()
    # 완전교호작용 모형 파라미터 = 2·배치수. 잔차자유도 ≥1 필요 → obs > 2·배치수.
    if nb < 2 or len(d) <= nb * 2:
        return None
    try:
        import statsmodels.formula.api as smf
        import statsmodels.api as sm
        dd = d.rename(columns={"결과값": "y", "시점(개월)": "t", "제조번호": "b"}).copy()
        dd["b"] = dd["b"].astype(str)
        model = smf.ols("y ~ t + C(b) + t:C(b)", data=dd).fit()
        tbl = sm.stats.anova_lm(model, typ=1)
    except Exception:
        return None

    label = {"t": "시간 (Month)", "C(b)": "제조번호 (Batch)",
             "t:C(b)": "시간×제조번호", "Residual": "오차 (Error)"}
    rows, inter_p, intercept_p = [], None, None
    for src in ["t", "C(b)", "t:C(b)", "Residual"]:
        if src not in tbl.index:
            continue
        r = tbl.loc[src]
        f = r.get("F"); p = r.get("PR(>F)")
        is_inter = src == "t:C(b)"
        is_intercept = src == "C(b)"   # 제조번호 주효과 = 절편 동일성
        if is_inter and pd.notna(p):
            inter_p = float(p)
        if is_intercept and pd.notna(p):
            intercept_p = float(p)
        rows.append({
            "source": label[src], "df": int(r["df"]),
            "ss": round(float(r["sum_sq"]), 2),
            "f": None if (pd.isna(f)) else round(float(f), 2),
            "p": None if (pd.isna(p)) else round(float(p), 3),
            "interaction": is_inter, "intercept": is_intercept,
            "error": src == "Residual",
        })
    if inter_p is None:
        return None

    # ICH Q1E 2단계: ① 기울기(교호작용) 동일성 → ② 절편(제조번호 주효과) 동일성
    slopes_common = inter_p >= 0.25
    intercepts_common = (intercept_p is not None and intercept_p >= 0.25)
    ip = "N/A" if intercept_p is None else f"{intercept_p:.3f}"
    if not slopes_common:
        poolable = False
        model_type = "개별 회귀 (기울기 상이)"
        verdict = "배치별 개별 회귀"
        note = (f"① 교호작용(시간×제조번호) p = {inter_p:.3f} < 0.25 → 배치 간 분해속도(기울기)가 달라 "
                "합산 불가. 배치별 개별 회귀선으로 각각 유효기간을 산출하고 최단값(worst-case)을 채택합니다.")
    elif not intercepts_common:
        poolable = True
        model_type = "공통 기울기·개별 절편 (부분 합산)"
        verdict = "공통 기울기·개별 절편"
        note = (f"① 교호작용 p = {inter_p:.3f} ≥ 0.25 → 기울기 공통. "
                f"② 제조번호(절편) p = {ip} < 0.25 → 절편은 배치별로 상이. "
                "공통 기울기·개별 절편 모형으로 합산 회귀를 적용합니다(ICH Q1E).")
    else:
        poolable = True
        model_type = "완전 합산 (공통 기울기·절편)"
        verdict = "완전 합산 가능"
        note = (f"① 교호작용 p = {inter_p:.3f} ≥ 0.25 → 기울기 공통. "
                f"② 제조번호(절편) p = {ip} ≥ 0.25 → 절편도 공통. "
                "완전 합산(공통 기울기·절편) 회귀를 적용합니다(ICH Q1E).")
    return {
        "alpha": 0.25, "rows": rows,
        "interactionP": round(inter_p, 3),
        "interceptP": None if intercept_p is None else round(intercept_p, 3),
        "slopesCommon": slopes_common, "interceptsCommon": intercepts_common,
        "poolable": poolable, "modelType": model_type,
        "verdict": verdict, "note": note,
    }


def _pick_test_item(df: pd.DataFrame) -> Optional[str]:
    """기본 시험항목 선택 — 함량(대분류) 항목 우선, 회귀가능 데이터 많은 순."""
    best, best_key = None, (-1, -1)
    for item, g in df.groupby("시험항목"):
        pairs = g.groupby("제조번호")["시점(개월)"].nunique()
        n = int(pairs[pairs >= 2].sum())
        is_assay = 1 if g["대분류"].astype(str).str.contains("함량").any() else 0
        key = (is_assay, n)              # 함량 우선, 그다음 데이터 많은 항목
        if key > best_key:
            best, best_key = item, key
    return best if best_key[1] >= 2 else (df["시험항목"].iloc[0] if len(df) else None)


def _steps_json(steps: dict) -> list:
    """RegressionResult.steps(중간계산) → JSON 안전한 [{k, v}] 순서 보존 리스트."""
    out = []
    for k, v in steps.items():
        if isinstance(v, float):
            out.append({"k": k, "v": None if (np.isnan(v)) else round(float(v), 6)})
        else:
            out.append({"k": k, "v": v})
    return out


def stability_analysis(code: str, test_type: str, spec_low: float = 90.0,
                       spec_high: float = 150.0, method: str = "pooled",
                       test_item: Optional[str] = None, batch: Optional[str] = None) -> dict:
    """단일 시험항목에 대한 회귀·유효기간·시점간 OOT·ANCOVA 결과(JSON 친화 dict).

    batch 지정 시 해당 제조번호(LOT) 한 배치만 분석한다(OOT 교차연동용).
    """
    df = stability_df(code, test_type)
    if df.empty:
        return {"ok": False, "reason": "정량 시점 데이터 없음"}
    if batch:
        df = df[df["제조번호"].astype(str) == str(batch)]
        if df.empty:
            return {"ok": False, "reason": f"배치 {batch}의 정량 시점 데이터가 없습니다."}

    items = sorted(df["시험항목"].unique())
    item = test_item if test_item in items else _pick_test_item(df)
    if not item:
        return {"ok": False, "reason": "분석 가능한 시험항목 없음"}
    d = df[df["시험항목"] == item].copy()

    # 규격: 시험기준 파싱값 우선, 양쪽 모두 없으면 수동 기본값
    both_na = d["규격하한"].isna() & d["규격상한"].isna()
    d.loc[both_na, "규격하한"] = spec_low
    d.loc[both_na, "규격상한"] = spec_high
    sl = float(d["규격하한"].dropna().iloc[0]) if d["규격하한"].notna().any() else None
    sh = float(d["규격상한"].dropna().iloc[0]) if d["규격상한"].notna().any() else None
    # 단위·규격표기 (선택 시험항목 기준)
    unit = ""
    if "단위" in d.columns:
        uvals = [str(x) for x in d["단위"] if str(x).strip()]
        unit = uvals[0] if uvals else ""
    spec_str = spec_text(sl, sh, unit)

    # 허가 유효기간(개월) = 유효기한 − 제조일자 (배치별, 행정상 승인값)
    approved = {}
    for b, gb in d.groupby("제조번호"):
        mfg = next((x for x in gb.get("제조일자", []) if str(x).strip()), "")
        exp = next((x for x in gb.get("유효기한", []) if str(x).strip()), "")
        approved[str(b)] = _approved_months(mfg, exp)

    col_map = {"batch": "제조번호", "test": "시험항목", "major": "대분류",
               "time": "시점(개월)", "assay": "결과값",
               "spec_low": "규격하한", "spec_high": "규격상한"}
    results = analyze_dataframe(d, col_map, spec_low, spec_high, method=method)
    if not results:
        return {"ok": False, "reason": "회귀 가능한 데이터 없음(시점 2개 이상 필요)"}

    batches = []
    for i, r in enumerate(sorted(results, key=lambda r: r.batch)):
        batches.append({
            "batch": r.batch, "color": BATCH_COLORS[i % len(BATCH_COLORS)],
            "approved": approved.get(str(r.batch)),
            "pts": [[float(x), float(y)] for x, y in zip(r.x, r.y)],
            "slope": None if np.isnan(r.slope) else round(float(r.slope), 5),
            "intercept": None if np.isnan(r.intercept) else round(float(r.intercept), 3),
            "r2": None if np.isnan(r.r_squared) else round(float(r.r_squared), 4),
            "n": int(r.n), "se": None if np.isnan(r.se_resid) else float(r.se_resid),
            "tcrit": None if np.isnan(r.t_crit) else float(r.t_crit),
            "mx": float(np.mean(r.x)) if r.n else 0.0,
            "sxx": float(np.sum((r.x - np.mean(r.x)) ** 2)) if r.n else 0.0,
            "shelf": None if r.shelf_life is None else round(float(r.shelf_life), 1),
            "trend": r.trend, "lastT": float(r.last_timepoint),
            "limit": r.limiting_side, "steps": _steps_json(r.steps),
        })

    # 가속시험은 6개월 종료 → 유효기간(저장수명) 산출 대상 아님(ICH Q1A/Q1E).
    # 6개월 데이터를 36개월로 외삽하면 CI가 폭발해 무의미한 값이 나오므로 산출하지 않는다.
    accelerated = bool(re.search(r"가속|accel", str(test_type), re.I))
    if accelerated:
        for b in batches:
            b["shelf"] = None
            b["limit"] = "가속시험 — 유효기간 산출 대상 아님(6개월 종료)"

    valid = [b for b in batches if b["shelf"] is not None]
    worst = min(valid, key=lambda b: b["shelf"]) if valid else None

    # 시점간 OOT — worst(없으면 첫) 배치 기준
    tb_name = worst["batch"] if worst else batches[0]["batch"]
    tb = next((r for r in results if r.batch == tb_name), results[0])
    sigma = float(tb.se_resid) if (tb.se_resid and not np.isnan(tb.se_resid)) else float("nan")
    tp_rows, n_oot, n_warn = [], 0, 0
    if not np.isnan(sigma) and sigma > 0 and not np.isnan(tb.slope):
        for x, y in zip(tb.x, tb.y):
            pred = tb.intercept + tb.slope * x
            dev = (y - pred) / sigma
            ad = abs(dev)
            judge = "⚠ OOT (3σ 밖)" if ad > 3 else ("주의 (2~3σ)" if ad > 2 else "정상 (2σ 이내)")
            if ad > 3:
                n_oot += 1
            elif ad > 2:
                n_warn += 1
            tp_rows.append({"time": round(float(x), 0), "meas": round(float(y), 2),
                            "pred": round(float(pred), 2), "dev": round(float(dev), 2),
                            "judge": judge})

    ancova = _ancova(d)
    pair_count = int(sum(len(b["pts"]) for b in batches))
    # 허가 유효기간 대표값(최빈값) + 추정 저장수명이 허가보다 짧은지 플래그
    av = [v for v in approved.values() if v]
    approved_months = max(set(av), key=av.count) if av else None
    # 가속은 유효기간 산출 대상이 아니므로 허가기간 비교 경고도 표시하지 않는다.
    approved_short = bool((not accelerated) and worst and approved_months
                          and worst["shelf"] < approved_months)
    accel_note = ("가속 안정성시험은 6개월 종료 시험으로, 유효기간(저장수명) 산출 대상이 아닙니다. "
                  "유의적 변화(significant change) 평가에 사용하며, 저장수명은 장기 안정성시험 "
                  "데이터로 산출합니다. (ICH Q1A/Q1E)") if accelerated else None
    return {
        "ok": True, "code": code, "testType": test_type, "testItem": item,
        "testItems": items, "batch": batch, "method": method, "specLow": sl, "specHigh": sh,
        "unit": unit, "specText": spec_str,
        "accelerated": accelerated, "accelNote": accel_note,
        "batchCount": len(batches), "pairCount": pair_count,
        "approvedMonths": approved_months, "approvedShort": approved_short,
        "batches": batches, "worst": worst,
        "sigma": None if np.isnan(sigma) else round(sigma, 3),
        "sigmaBase": "통합 잔차오차" if method == "pooled" else "배치 잔차오차",
        "tpBatch": tb_name, "tpRows": tp_rows, "nOot": n_oot, "nWarn": n_warn,
        "ancova": ancova,
    }


def stability_tables(code: str, test_type: str, spec_low: float = 90.0,
                     spec_high: float = 150.0, batch: Optional[str] = None) -> dict:
    """전 시험항목 × 배치에 대한 두 방식 비교표·상세 요약·원자료 (기존 LIMS 앱 정보 복원).

    batch 지정 시 해당 배치만.
    """
    df = stability_df(code, test_type)
    if df.empty:
        return {"ok": False, "reason": "데이터 없음"}
    df = df.copy()
    if batch:
        df = df[df["제조번호"].astype(str) == str(batch)]
        if df.empty:
            return {"ok": False, "reason": f"배치 {batch} 데이터 없음"}
    both_na = df["규격하한"].isna() & df["규격상한"].isna()
    df.loc[both_na, "규격하한"] = spec_low
    df.loc[both_na, "규격상한"] = spec_high
    col_map = {"batch": "제조번호", "test": "시험항목", "major": "대분류",
               "time": "시점(개월)", "assay": "결과값",
               "spec_low": "규격하한", "spec_high": "규격상한"}
    rp = analyze_dataframe(df, col_map, spec_low, spec_high, "pooled")
    ri = analyze_dataframe(df, col_map, spec_low, spec_high, "independent")

    # 가속시험(6개월 종료)은 유효기간 산출 대상 아님 → shelf 표시 안 함
    _accel = bool(re.search(r"가속|accel", str(test_type), re.I))
    if _accel:
        for r in list(rp) + list(ri):
            r.shelf_life = None
            r.limiting_side = "가속시험 — 유효기간 산출 대상 아님(6개월 종료)"

    def _srow(r):
        return {"component": r.test_item, "batch": r.batch, "n": int(r.n),
                "slope": None if np.isnan(r.slope) else round(float(r.slope), 4),
                "intercept": None if np.isnan(r.intercept) else round(float(r.intercept), 3),
                "r2": None if np.isnan(r.r_squared) else round(float(r.r_squared), 4),
                "trend": r.trend,
                "shelf": None if r.shelf_life is None else round(float(r.shelf_life), 1),
                "limit": r.limiting_side}
    summary_pooled = [_srow(r) for r in sorted(rp, key=lambda r: (r.test_item, r.batch))]
    summary_indep = [_srow(r) for r in sorted(ri, key=lambda r: (r.test_item, r.batch))]
    pmap = {(r.test_item, r.batch): r for r in rp}
    imap = {(r.test_item, r.batch): r for r in ri}
    comparison = []
    for k in sorted(pmap, key=lambda k: (k[0], k[1])):
        sp = pmap[k].shelf_life
        si = imap[k].shelf_life if k in imap else None
        comparison.append({"component": k[0], "batch": k[1],
                           "pooled": None if sp is None else round(float(sp), 1),
                           "indep": None if si is None else round(float(si), 1),
                           "diff": None if (sp is None or si is None) else round(float(sp - si), 1)})
    raw = []
    for r in df.sort_values(["시험항목", "제조번호", "시점(개월)"]).to_dict("records"):
        raw.append({"제조번호": r["제조번호"], "시험항목": r["시험항목"], "대분류": r["대분류"],
                    "시점": r["시점(개월)"], "결과값": r["결과값"],
                    "규격하한": None if (isinstance(r["규격하한"], float) and np.isnan(r["규격하한"])) else r["규격하한"],
                    "규격상한": None if (isinstance(r["규격상한"], float) and np.isnan(r["규격상한"])) else r["규격상한"]})
    wp = min([r.shelf_life for r in rp if r.shelf_life is not None], default=None)
    wi = min([r.shelf_life for r in ri if r.shelf_life is not None], default=None)
    return {"ok": True, "summaryPooled": summary_pooled, "summaryIndep": summary_indep,
            "comparison": comparison, "raw": raw,
            "worstPooled": None if wp is None else round(float(wp), 1),
            "worstIndep": None if wi is None else round(float(wi), 1)}


def stability_excel(code: str, test_type: str, spec_low: float = 90.0,
                    spec_high: float = 150.0, batch: Optional[str] = None) -> bytes:
    """안정성 분석결과 Excel(.xlsx) — 두방식비교·요약(통합/독립)·원자료 4개 시트."""
    from openpyxl import Workbook
    t = stability_tables(code, test_type, spec_low, spec_high, batch)
    wb = Workbook()
    ws = wb.active
    ws.title = "두방식비교"
    ws.append(["시험항목", "제조번호", "통합(권장)", "배치별독립", "차이(통합-독립)"])
    for r in t.get("comparison", []):
        ws.append([r["component"], r["batch"], r["pooled"], r["indep"], r["diff"]])
    for title, key in [("요약_통합", "summaryPooled"), ("요약_독립", "summaryIndep")]:
        s = wb.create_sheet(title)
        s.append(["시험항목", "제조번호", "데이터수", "기울기", "절편", "R2", "추세", "유효기간(개월)", "제한규격"])
        for r in t.get(key, []):
            s.append([r["component"], r["batch"], r["n"], r["slope"], r["intercept"],
                      r["r2"], r["trend"], r["shelf"], r["limit"]])
    s = wb.create_sheet("원자료")
    s.append(["제조번호", "시험항목", "대분류", "시점(개월)", "결과값", "규격하한", "규격상한"])
    for r in t.get("raw", []):
        s.append([r["제조번호"], r["시험항목"], r["대분류"], r["시점"], r["결과값"], r["규격하한"], r["규격상한"]])
    import io as _io
    buf = _io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
