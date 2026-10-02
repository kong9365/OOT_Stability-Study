"""동일품목군(유사품목 모아보기) — 유사도 검색 · 그룹 저장 · 풀링 OOT 집계.

APQR 관점: 코드가 다른 동일 제품을 하나로 합쳐(pooling) 관리도·OOT를 산출한다.
규격·시험방법이 동일한 코드에만 적용한다(풀링 전제).
판정 로직은 기존과 동일(±3σ 초과 = OOT). 집계 단위만 품목코드 → 그룹으로 바꾼다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import storage_io


# --------------------------------------------------------------------------
# 1. 유사도 검색 (후보 검색 + '목록에 없어 직접 검색'을 같은 함수로 처리)
# --------------------------------------------------------------------------
@dataclass
class Candidate:
    품목코드: str
    품목명: str
    유사도: float  # 0.0 ~ 1.0


def search_similar_items(query: str, catalog: list[dict], top_n: int = 10) -> list[Candidate]:
    """query(품목명)와 catalog 품목명의 글자 유사도를 계산해 상위 후보를 반환한다.

    catalog: [{"품목코드": ..., "품목명": ...}, ...]
    """
    scored = [
        Candidate(
            품목코드=row["품목코드"],
            품목명=row["품목명"],
            유사도=round(SequenceMatcher(None, query, row["품목명"]).ratio(), 4),
        )
        for row in catalog
    ]
    scored.sort(key=lambda c: c.유사도, reverse=True)
    return scored[:top_n]


# --------------------------------------------------------------------------
# 2. 동일품목군 저장 (APQR 재현성: 합친 코드 + 갱신 시점을 남긴다)
# --------------------------------------------------------------------------
@dataclass
class ItemGroup:
    group_id: str
    group_name: str
    member_codes: list[str]
    updated_at: str


class GroupStore:
    """확정된 동일품목군을 JSON 파일로 저장/조회한다.

    변경 이력 전체를 남기는 감사추적이 필요하면 별도 확장 — 여기선 현재 구성만 저장한다.
    """

    def __init__(self, path):
        self.path = Path(path)

    def _read(self) -> dict:
        return storage_io.read_json(self.path, default={}) or {}

    def save_group(self, group_id: str, group_name: str, member_codes: list[str]) -> ItemGroup:
        data = self._read()
        data[group_id] = asdict(
            ItemGroup(
                group_id=group_id,
                group_name=group_name,
                member_codes=sorted(set(member_codes)),
                updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        )
        storage_io.write_json(self.path, data)
        return ItemGroup(**data[group_id])

    def load_group(self, group_id: str) -> ItemGroup | None:
        data = self._read()
        return ItemGroup(**data[group_id]) if group_id in data else None

    def list_groups(self) -> list[ItemGroup]:
        return [ItemGroup(**g) for g in self._read().values()]

    def delete_group(self, group_id: str) -> bool:
        data = self._read()
        if group_id not in data:
            return False
        del data[group_id]
        storage_io.write_json(self.path, data)
        return True


# --------------------------------------------------------------------------
# 3. 풀링 집계 + OOT 플래그
# --------------------------------------------------------------------------
@dataclass
class PooledResult:
    group_id: str
    시험항목: str
    n: int
    mean: float
    std: float
    ucl_3s: float
    lcl_3s: float
    ucl_2s: float
    lcl_2s: float
    points: list[dict]  # 레코드별 값 + OOT/경고 플래그


def pool_and_flag(
    records: list[dict],
    member_codes: list[str],
    시험항목: str,
    group_id: str = "",
    valid_col: str = "시험결과_유효",
) -> PooledResult:
    """member_codes의 유효 레코드를 풀링해 평균·σ·관리한계·OOT 플래그를 산출한다.

    records: [{"품목코드", "LOT", "시험항목", "시험결과", valid_col: bool, ...}, ...]
    - 기존 규칙 유지: valid_col == True 인 레코드만 사용(재시험 무효 0값 등 제외).
    - σ는 표본표준편차(ddof=1) — 기존 Tableau WINDOW_STDEV와 일치.
    - 판정: |값 - 평균| > 3σ 이면 OOT. 2σ 초과(3σ 이내)는 경고로 표시.
    """
    rows = [
        r
        for r in records
        if r["품목코드"] in member_codes
        and r["시험항목"] == 시험항목
        and r.get(valid_col, True)
    ]
    values = [r["시험결과"] for r in rows]
    if len(values) < 2:
        raise ValueError("풀링에 필요한 유효 레코드가 부족합니다(2건 이상 필요).")

    mean = statistics.fmean(values)
    std = statistics.stdev(values)  # ddof=1 (표본표준편차)
    ucl_3s, lcl_3s = mean + 3 * std, mean - 3 * std
    ucl_2s, lcl_2s = mean + 2 * std, mean - 2 * std

    points = []
    for r in rows:
        v = r["시험결과"]
        out_3s = v > ucl_3s or v < lcl_3s
        points.append(
            {
                "품목코드": r["품목코드"],
                "LOT": r.get("LOT"),
                "시험결과": v,
                "oot_3s": out_3s,
                "warn_2s": (v > ucl_2s or v < lcl_2s) and not out_3s,
            }
        )

    return PooledResult(
        group_id=group_id,
        시험항목=시험항목,
        n=len(values),
        mean=mean,
        std=std,
        ucl_3s=ucl_3s,
        lcl_3s=lcl_3s,
        ucl_2s=ucl_2s,
        lcl_2s=lcl_2s,
        points=points,
    )


def pooled_to_dict(res: PooledResult) -> dict:
    """PooledResult → JSON 직렬화용 dict."""
    return asdict(res)
