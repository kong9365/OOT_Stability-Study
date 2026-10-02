"""
안정성 함량 회귀분석 엔진 (ICH Q1E 기반)
- 선형회귀로 함량(%) vs 시간(개월) 분석
- 95% 신뢰구간이 규격선과 만나는 시점 = 유효기간(Shelf-life)

모든 계산은 검증 가능하도록 중간값(steps)을 함께 반환한다.
"""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from scipy import stats


@dataclass
class RegressionResult:
    """단일 (제조번호 × 시험항목) 회귀분석 결과."""
    batch: str
    test_item: str
    n: int                      # 데이터 개수
    x: np.ndarray               # 시점(개월)
    y: np.ndarray               # 함량(%)
    slope: float                # 기울기 b
    intercept: float            # 절편 a
    r_squared: float            # 결정계수 R²
    se_resid: float             # 잔차 표준오차
    t_crit: float               # t(0.95, n-2) 단측
    spec_low: float
    spec_high: float
    trend: str                  # "감소" / "증가" / "변화 없음"
    shelf_life: Optional[float] # 유효기간(개월). None이면 산출 불가
    limiting_side: str          # 어느 규격선이 유효기간을 제한했는지
    last_timepoint: float       # 마지막 측정 시점
    steps: dict = field(default_factory=dict)  # 검증용 계산 단계

    @property
    def shelf_life_text(self) -> str:
        if self.shelf_life is None:
            return "산출 불가 (추세 없음/데이터 부족)"
        # 규제상 통상 측정 시점 단위로 내림하여 보수적으로 표현
        return f"{self.shelf_life:.1f}개월까지 안정성 유효"


def _t_critical(n: int, conf: float = 0.95) -> float:
    """단측 t 임계값 t(conf, n-2)."""
    df = n - 2
    if df < 1:
        return float("nan")
    return float(stats.t.ppf(conf, df))


def ci_bound(x_new, slope, intercept, x, se_resid, t_crit, sxx, n, side="low"):
    """
    회귀선의 95% 평균신뢰구간(confidence interval) 경계값.
    ICH Q1E는 평균응답의 단측 95% CI를 사용한다.
        SE_mean(x) = se_resid * sqrt( 1/n + (x-x̄)²/Sxx )
    """
    x_mean = np.mean(x)
    y_hat = intercept + slope * x_new
    se_mean = se_resid * np.sqrt(1.0 / n + (x_new - x_mean) ** 2 / sxx)
    margin = t_crit * se_mean
    return y_hat - margin if side == "low" else y_hat + margin


def _find_crossing(target, slope, intercept, x, se_resid, t_crit, sxx, n,
                   side, x_max_search):
    """
    CI 경계가 규격선(target)과 만나는 x를 이분탐색으로 찾는다.
    x=0(또는 last)에서는 규격 내, 어느 시점에서 규격을 벗어나는 첫 지점.
    """
    f = lambda xv: ci_bound(xv, slope, intercept, x, se_resid, t_crit, sxx, n, side)

    def violates(xv):
        return f(xv) < target if side == "low" else f(xv) > target

    if violates(0.0):
        return None  # 시작부터 규격 위반 → 산출 불가
    if not violates(x_max_search):
        return x_max_search  # 탐색 범위 끝까지 규격 내 → 그 값 반환(하한)

    lo, hi = 0.0, x_max_search
    for _ in range(100):
        mid = (lo + hi) / 2
        if violates(mid):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def analyze(batch, test_item, x, y, spec_low=95.0, spec_high=105.0,
            conf=0.95, search_horizon=None, se_pool=None, df_pool=None):
    """
    한 배치·시험항목에 대한 회귀분석 + 유효기간 산출.
    x: 시점(개월) array-like, y: 함량(%) array-like

    se_pool / df_pool 가 주어지면(ICH Q1E·Minitab 방식) 잔차표준오차와 자유도를
    배치별이 아니라 '여러 배치 통합(pooled)' 값으로 사용한다. 이렇게 해야 시점이
    배치당 3~4개뿐일 때도 자유도가 확보되어 미니탭과 동일한 유효기간이 나온다.
    slope·intercept·R² 는 각 배치 자체 값으로 계산한다.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    # 결측(텍스트 결과 등) 제거
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    order = np.argsort(x)
    x, y = x[order], y[order]
    n = len(x)

    pooled = se_pool is not None and df_pool is not None and df_pool >= 1
    min_n = 2 if pooled else 3   # pooled면 회귀선(점2개)만 있어도 통합오차로 산출
    if n < min_n or (not pooled and n < 3):
        return RegressionResult(
            batch, test_item, n, x, y, np.nan, np.nan, np.nan, np.nan,
            np.nan, spec_low, spec_high, "데이터 부족", None, "-",
            float(x.max()) if n else 0.0,
            steps={"note": f"회귀에는 최소 {min_n}개 시점이 필요합니다."},
        )

    x_mean, y_mean = np.mean(x), np.mean(y)
    sxx = np.sum((x - x_mean) ** 2)
    sxy = np.sum((x - x_mean) * (y - y_mean))
    syy = np.sum((y - y_mean) ** 2)

    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    y_pred = intercept + slope * x
    ss_res = np.sum((y - y_pred) ** 2)
    r_squared = 1 - ss_res / syy if syy > 0 else 1.0

    # 잔차표준오차/자유도: pooled면 통합값, 아니면 배치 자체값
    if pooled:
        se_resid = float(se_pool)
        dof = int(df_pool)
    else:
        se_resid = np.sqrt(ss_res / (n - 2))
        dof = n - 2
    t_crit = float(stats.t.ppf(conf, dof)) if dof >= 1 else float("nan")

    # 추세 판정 (기울기 유의성 t검정) — pooled 오차/자유도 사용
    se_slope = se_resid / np.sqrt(sxx) if sxx > 0 else np.nan
    t_slope = slope / se_slope if se_slope else np.nan
    p_slope = 2 * (1 - stats.t.cdf(abs(t_slope), dof)) if dof >= 1 else np.nan
    if abs(slope) < 1e-9 or (not np.isnan(p_slope) and p_slope > 0.05):
        trend = "변화 없음"
    elif slope < 0:
        trend = "감소"
    else:
        trend = "증가"

    horizon = search_horizon or max(float(x.max()) * 2, 60.0)

    # 규격이 있는 쪽만 검토 (양측/단측 자동) → 더 빠른 시점(보수적) 채택
    has_low = spec_low is not None and not (isinstance(spec_low, float) and np.isnan(spec_low))
    has_high = spec_high is not None and not (isinstance(spec_high, float) and np.isnan(spec_high))
    cross_low = _find_crossing(spec_low, slope, intercept, x, se_resid,
                               t_crit, sxx, n, "low", horizon) if has_low else None
    cross_high = _find_crossing(spec_high, slope, intercept, x, se_resid,
                                t_crit, sxx, n, "high", horizon) if has_high else None

    candidates = []
    if cross_low is not None:
        candidates.append((cross_low, f"하한 {spec_low} (CI 하한 교차)"))
    if cross_high is not None:
        candidates.append((cross_high, f"상한 {spec_high} (CI 상한 교차)"))

    if candidates:
        shelf_life, limiting_side = min(candidates, key=lambda c: c[0])
    else:
        shelf_life, limiting_side = None, "시작부터 규격 위반"

    steps = {
        "n": n,
        "x_mean (x̄)": x_mean,
        "y_mean (ȳ)": y_mean,
        "Sxx = Σ(x-x̄)²": sxx,
        "Sxy = Σ(x-x̄)(y-ȳ)": sxy,
        "Syy = Σ(y-ȳ)²": syy,
        "기울기 b = Sxy/Sxx": slope,
        "절편 a = ȳ - b·x̄": intercept,
        "잔차제곱합 SSres": ss_res,
        "R² = 1 - SSres/Syy": r_squared,
        ("잔차표준오차 SE (통합 pooled)" if pooled
         else "잔차표준오차 SE = √(SSres/(n-2))"): se_resid,
        "자유도 df": dof,
        "신뢰수준(단측)": conf,
        "기울기 표준오차 SE_b": se_slope,
        "t(기울기) = b/SE_b": t_slope,
        "p(기울기)": p_slope,
        f"t임계값 t({conf:g}, df={dof})": t_crit,
        "규격하한 교차(개월)": cross_low,
        "규격상한 교차(개월)": cross_high,
        "채택 유효기간(개월)": shelf_life,
    }

    return RegressionResult(
        batch, test_item, n, x, y, slope, intercept, r_squared, se_resid,
        t_crit, spec_low, spec_high, trend, shelf_life, limiting_side,
        float(x.max()), steps,
    )


def _pooled_error(gpool, tcol, acol, bcol):
    """
    한 (성분·대분류) 그룹 안의 모든 배치를 각각 회귀한 뒤 잔차제곱합을 합쳐
    통합 잔차표준오차(se_pool)와 자유도(df_pool=Σ(n_i-2))를 구한다. (ICH Q1E·Minitab 방식)
    """
    ss_total, df_total = 0.0, 0
    for _, gb in gpool.groupby(bcol):
        x = np.asarray(gb[tcol].values, dtype=float)
        y = np.asarray(gb[acol].values, dtype=float)
        m = ~(np.isnan(x) | np.isnan(y))
        x, y = x[m], y[m]
        n = len(x)
        if n < 2:
            continue
        xb = x.mean()
        sxx = np.sum((x - xb) ** 2)
        if sxx <= 0:
            continue
        slope = np.sum((x - xb) * (y - y.mean())) / sxx
        intercept = y.mean() - slope * xb
        ss_total += np.sum((y - (intercept + slope * x)) ** 2)
        df_total += (n - 2)
    if df_total >= 1:
        return float(np.sqrt(ss_total / df_total)), int(df_total)
    return None, None


def analyze_dataframe(df, col_map, spec_low=95.0, spec_high=105.0,
                      method="pooled"):
    """
    DataFrame을 (제조번호 × [대분류] × 시험항목) 그룹별로 분석.
    col_map: {"batch", "test", "time", "assay",
              "major":..(optional 대분류), "spec_low":.., "spec_high":..}
    규격: spec_low/high 컬럼이 지정되면 데이터값을 그대로 사용(없으면 None=단측).
          컬럼이 지정 안 되면 기본값(spec_low/high 인자) 사용.

    method:
      "pooled"      → ICH Q1E·Minitab. 같은 (대분류·성분) 배치를 묶어 통합 잔차오차 사용.
      "independent" → 배치별 독립 회귀(각 배치 자체 오차/자유도).
    두 방식 모두 양측 규격이면 97.5% 단측(=양측 95%), 단측 규격이면 95% 단측을 쓴다.
    """
    results = []
    major = col_map.get("major")
    bcol, tcol, acol = col_map["batch"], col_map["test"], col_map["time"]
    acol_v = col_map["assay"]

    # 통합(pool) 단위 = (대분류 × 성분). 같은 규격을 공유하는 배치 묶음.
    pool_cols = []
    if major and major in df:
        pool_cols.append(major)
    pool_cols.append(tcol)

    has_low_col = bool(col_map.get("spec_low")) and col_map["spec_low"] in df
    has_high_col = bool(col_map.get("spec_high")) and col_map["spec_high"] in df

    for pkey, gpool in df.groupby(pool_cols):
        pkey = pkey if isinstance(pkey, tuple) else (pkey,)
        test = pkey[-1]
        maj = pkey[0] if (major and major in df) else None

        # 규격 (이 성분 그룹 공통)
        if has_low_col:
            v = gpool[col_map["spec_low"]].dropna()
            sl = float(v.iloc[0]) if len(v) else None
        else:
            sl = spec_low
        if has_high_col:
            v = gpool[col_map["spec_high"]].dropna()
            sh = float(v.iloc[0]) if len(v) else None
        else:
            sh = spec_high

        # 양측 규격 → 97.5% 단측(=양측 95%), 단측 규격 → 95% 단측
        conf = 0.975 if (sl is not None and sh is not None) else 0.95

        # 이 성분 그룹의 통합오차/자유도 (시간=acol, 함량=acol_v)
        if method == "pooled":
            se_pool, df_pool = _pooled_error(gpool, acol, acol_v, bcol)
        else:  # independent: 배치별 자체 오차 사용
            se_pool, df_pool = None, None

        label = f"{test}" + (f" [{maj}]" if maj else "")
        for batch, gb in gpool.groupby(bcol):
            res = analyze(
                str(batch), label,
                gb[acol].values, gb[acol_v].values,
                spec_low=sl, spec_high=sh, conf=conf,
                se_pool=se_pool, df_pool=df_pool,
            )
            results.append(res)
    return results
