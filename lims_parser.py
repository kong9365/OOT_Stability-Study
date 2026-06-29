# -*- coding: utf-8 -*-
"""
LIMS '시험결과 입력' xls → 안정성 회귀분석용 정제 데이터(long format) 변환.

규칙 (사용자 요청 반영):
- 함량 시험항목만 추출 (시험항목에 '함량' 포함)
- 완제품(시험종류) = 해당 배치 안정성의 최초 이니셜(0개월) 결과로 처리
- 장기 안정성시험 = 의뢰특이사항 '기간 : N개월' → 시점(개월)
- 시험기준 '90.0 ∼ 150.0 %' → 규격하한 / 규격상한
- 시험결과 NaN(이니셜 입력행) 제거
"""
import io
import os
import re
import pandas as pd

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "시험결과_입력.xls")


class DRMProtectedError(Exception):
    """사내 DRM(MarkAny 등)으로 암호화되어 읽을 수 없는 파일."""


def _raw_bytes(file_or_path):
    if hasattr(file_or_path, "read"):
        pos = file_or_path.tell() if hasattr(file_or_path, "tell") else 0
        data = file_or_path.read()
        if hasattr(file_or_path, "seek"):
            file_or_path.seek(pos)
        return data
    with open(file_or_path, "rb") as f:
        return f.read()


def read_any_excel(file_or_path, header=1):
    """
    xls / xlsx / HTML-표 형식 엑셀을 모두 읽는 강건한 로더.
    DRM 암호화 파일은 DRMProtectedError 로 명확히 알림.
    """
    data = _raw_bytes(file_or_path)
    head = data[:64]

    # 1) 사내 DRM 감지
    if b"DOCUMENT SAFER" in head or b"Pydocsafer" in data[:2048] or b"MarkAny" in head:
        raise DRMProtectedError(
            "이 파일은 사내 보안(MarkAny Document SAFER)으로 암호화되어 있어 "
            "그대로는 분석할 수 없습니다. Excel에서 파일을 연 뒤 "
            "[다른 이름으로 저장] → 새 .xlsx 파일로 저장(또는 데이터 복사 후 새 통합문서에 붙여넣기)하여 "
            "DRM이 풀린 사본을 업로드해 주세요."
        )

    name = str(getattr(file_or_path, "name", file_or_path)).lower()
    bio = io.BytesIO(data)
    # 2) 진짜 xlsx (ZIP, PK)
    if head[:2] == b"PK":
        return pd.read_excel(bio, header=header, engine="openpyxl")
    # 3) 구형 xls (OLE2)
    if head[:8] == b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1":
        return pd.read_excel(bio, header=header, engine="xlrd")
    # 4) HTML 표로 내보낸 xls
    if head.lstrip()[:1] in (b"<",) or b"<table" in data[:4096].lower() or b"<html" in head.lower():
        tables = pd.read_html(io.BytesIO(data), header=header)
        if tables:
            return tables[0]
    # 5) CSV (DRM 미적용 권장 형식)
    if name.endswith(".csv") or b"," in head or b"\t" in head:
        for enc in ("utf-8-sig", "cp949", "utf-8"):
            try:
                sep = "\t" if b"\t" in head and b"," not in head else ","
                return pd.read_csv(io.BytesIO(data), header=header, sep=sep,
                                   encoding=enc)
            except Exception:
                continue
    # 6) 마지막 시도: pandas 자동
    return pd.read_excel(io.BytesIO(data), header=header)


def parse_spec(text):
    """
    시험기준 텍스트에서 규격 (하한, 상한) 자동 판별.
      '90.0 ∼ 150.0 %'  → (90.0, 150.0)   양측
      '5000 ppm 이하'    → (None, 5000.0)  단측 상한
      '80 % 이상'        → (80.0, None)    단측 하한
    판별 불가 → (None, None)
    """
    if pd.isna(text):
        return (None, None)
    s = str(text)
    # 1) 범위 표기 (a ∼ b, a ~ b, a - b)
    m = re.search(r"(\d+\.?\d*)\s*[∼~〜–—\-]\s*(\d+\.?\d*)", s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    nums = re.findall(r"\d+\.?\d*", s)
    if not nums:
        return (None, None)
    # 2) 단측: '이하'(상한) / '이상'(하한). 규격 수치는 보통 마지막 숫자
    if "이하" in s:
        return (None, float(nums[-1]))
    if "이상" in s:
        return (float(nums[-1]), None)
    return (None, None)


def _fmt_batch(v):
    """제조번호 정리: 23001.0 → '23001', '24500(살균전)' → 그대로."""
    s = str(v).strip()
    try:
        f = float(s)
        return str(int(f)) if f.is_integer() else s
    except (ValueError, TypeError):
        return s


def parse_month(특이사항, 시험종류):
    """완제품 → 0개월. 안정성 → '기간 : N개월'에서 N 추출."""
    if "완제품" in str(시험종류):
        return 0.0
    m = re.search(r"기간\s*:\s*(\d+)\s*개월", str(특이사항))
    return float(m.group(1)) if m else None


def is_lims_raw(file_or_path):
    """업로드 파일이 LIMS '시험결과 입력' 원본 양식인지 판별. (DRM은 그대로 전파)"""
    try:
        head = read_any_excel(file_or_path, header=1)
        cols = set(map(str, head.columns))
        return {"시험항목", "시험결과", "시험종류"}.issubset(cols)
    except DRMProtectedError:
        raise
    except Exception:
        return False


# 분석 대상 대분류 (이 키워드를 포함하면 포함). '확인'은 정성시험이라 제외.
ALLOWED_CATEGORIES = ["함량"]


def _is_allowed(대분류):
    s = str(대분류)
    if "확인" in s:
        return False
    return any(k in s for k in ALLOWED_CATEGORIES)


def parse_lims(path=DEFAULT_PATH, allowed=None):
    """
    LIMS 원본 → 안정성 분석용 long format.
    대분류가 함량·용출·잔류용매·붕해(allowed)인 행만 포함.
    규격은 시험기준에서 자동 판별. 결과가 텍스트면 결과값=NaN(표시는 되되 분석 제외).
    """
    allowed = allowed or ALLOWED_CATEGORIES
    df = read_any_excel(path, header=1)
    df = df.copy()

    if "대분류" not in df.columns:
        df["대분류"] = ""
    # 대분류 화이트리스트 필터
    keep = df["대분류"].apply(
        lambda v: ("확인" not in str(v)) and any(k in str(v) for k in allowed))
    df = df[keep].copy()
    df = df[df["시험결과"].notna()].copy()

    # 성분명 = 시험항목에서 ' 함량' 제거 (티아민질산염 등). 그 외 항목은 원문 유지.
    df["성분"] = df["시험항목"].astype(str).str.replace(
        r"\s*함량\s*", "", regex=True).str.strip()

    # 시점(개월): 완제품=0, 안정성='기간 : N개월'
    df["시점(개월)"] = df.apply(
        lambda r: parse_month(r["의뢰 특이사항"], r["시험종류"]), axis=1)
    df = df[df["시점(개월)"].notna()].copy()

    # 규격 자동 판별 (양측/단측)
    spec = df["시험기준"].apply(parse_spec)
    df["규격하한"] = spec.apply(lambda t: t[0])
    df["규격상한"] = spec.apply(lambda t: t[1])

    # 결과값 숫자화 (텍스트 결과는 NaN으로 두어 표시는 하되 분석에서는 제외)
    df["결과값"] = pd.to_numeric(df["시험결과"], errors="coerce")

    out = df[[
        "품목", "제조번호", "시험종류", "의뢰 특이사항",
        "대분류", "성분", "시험항목", "시험기준",
        "시점(개월)", "결과값", "규격하한", "규격상한",
    ]].copy()
    out["제조번호"] = out["제조번호"].map(_fmt_batch)

    out = out.sort_values(["품목", "제조번호", "대분류", "성분", "시점(개월)"]
                          ).reset_index(drop=True)
    return out


MERGE_KEY = ["제조번호", "대분류", "성분", "시점(개월)"]
STORE_PATH = "parsed_data.csv"


def merge_into_store(new_df, store_path=STORE_PATH):
    """
    새 데이터를 저장본(parsed_data.csv)에 누적 병합.
    같은 (제조번호·성분·시점)은 새 값으로 갱신, 새 시점/배치는 추가.
    반환: (병합본 DataFrame, 추가·갱신된 행 수)
    """
    if os.path.exists(store_path):
        old = pd.read_csv(store_path)
        old["제조번호"] = old["제조번호"].astype(str)
    else:
        old = pd.DataFrame(columns=new_df.columns)
    new_df = new_df.copy()
    new_df["제조번호"] = new_df["제조번호"].astype(str)

    before = len(old)
    # old 먼저, new 나중 → keep='last'가 새 값 우선
    merged = pd.concat([old, new_df], ignore_index=True)
    merged = merged.drop_duplicates(subset=MERGE_KEY, keep="last")
    merged = merged.sort_values(["제조번호", "성분", "시점(개월)"]).reset_index(drop=True)
    merged.to_csv(store_path, index=False, encoding="utf-8-sig")
    changed = len(merged) - before
    return merged, changed


if __name__ == "__main__":
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    out = parse_lims()
    out.to_csv(STORE_PATH, index=False, encoding="utf-8-sig")
    print(f"parsed_data.csv 생성: {len(out)} 행")
    print("\n=== 성분 x 배치 x 시점 개수 ===")
    piv = out.pivot_table(index=["성분", "제조번호"], columns="시점(개월)",
                          values="함량(%)", aggfunc="mean")
    print(piv.to_string())
