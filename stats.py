"""Trend statistics for monthly series: Sen's slope, Mann-Kendall p-value, confidence interval."""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd
import pymannkendall as mk

ALPHA = 0.05
METHODS = ("corrected", "plain")
# Autocorrelation correction: Hamed & Rao (1998) variance-corrected Mann-Kendall, using the
# significant autocorrelations of the first HR_LAGS lags (months). Chosen by simulation
# (see README "Statistical method"); results were insensitive to 3-9 lags.
HR_LAGS = 4


def mann_kendall_p(y: np.ndarray, method: str = "corrected", alpha: float = ALPHA) -> float:
    """Two-sided Mann-Kendall p-value.

    "plain"     : original test, assumes independent values (too optimistic for monthly data).
    "corrected" : Hamed-Rao modification. Month-to-month persistence means the series holds
                  less independent information than its length suggests; the test inflates the
                  variance of the MK statistic accordingly, giving a larger (more honest) p-value.
    """
    if method == "plain":
        return float(mk.original_test(y, alpha=alpha).p)
    if method == "corrected":
        return float(mk.hamed_rao_modification_test(y, alpha=alpha, lag=min(HR_LAGS, len(y) - 2)).p)
    raise ValueError(f"method must be one of {METHODS}, not {method!r}")


def remove_seasonal_cycle(s: pd.Series) -> pd.Series:
    """Subtract the mean of each calendar month (monthly climatology) from a monthly series."""
    clim = s.groupby(s.index.month).transform("mean")
    return s - clim


def _sen(t: np.ndarray, y: np.ndarray, alpha: float):
    """Sen's slope (per unit of t), intercept, and confidence interval of the slope."""
    n = len(y)
    i, j = np.triu_indices(n, k=1)
    dt = t[j] - t[i]
    ok = dt > 0
    slopes = np.sort((y[j] - y[i])[ok] / dt[ok])
    slope = float(np.median(slopes))
    intercept = float(np.median(y - slope * t))
    # Distribution-free CI (Sen 1968), no tie correction.
    var_s = n * (n - 1) * (2 * n + 5) / 18
    c = NormalDist().inv_cdf(1 - alpha / 2) * math.sqrt(var_s)
    m = len(slopes)
    lo = int(max(math.floor((m - c) / 2), 0))
    hi = int(min(math.ceil((m + c) / 2), m - 1))
    return slope, intercept, float(slopes[lo]), float(slopes[hi])


def analyze(series: pd.Series, deseasonalize: bool = False, alpha: float = ALPHA,
            method: str = "corrected") -> dict:
    """Analyze a monthly series (DatetimeIndex). NaNs are dropped; time is kept in real years.

    method: "corrected" (default, autocorrelation-corrected Mann-Kendall) or "plain".
    Sen's slope and its confidence interval do not depend on the method.

    Returns slope_per_decade, ci_low/ci_high (per decade), p_value, significant, method, trend
    ('increasing'/'decreasing'/'no trend'), n_months, record_years, fitted (Series).
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, not {method!r}")
    s = series.astype(float).dropna().sort_index()
    if len(s) < 10:
        raise ValueError("Need at least 10 monthly values to estimate a trend.")
    work = remove_seasonal_cycle(s) if deseasonalize else s

    # time in decimal years, mid-month
    t = (work.index.year + (work.index.month - 0.5) / 12).to_numpy(dtype=float)
    y = work.to_numpy(dtype=float)

    slope, intercept, lo, hi = _sen(t, y, alpha)
    p = mann_kendall_p(y, method, alpha)
    significant = p < alpha
    # Fitted line is drawn on the ORIGINAL series so it overlays the plotted data:
    # same slope, intercept re-fitted on the original values (median residual).
    t0 = t
    fit_int = float(np.median(s.to_numpy() - slope * t0)) if deseasonalize else intercept
    fitted = pd.Series(slope * t0 + fit_int, index=s.index)

    return {
        "slope_per_decade": slope * 10,
        "ci_low_per_decade": lo * 10,
        "ci_high_per_decade": hi * 10,
        "p_value": p,
        "significant": bool(significant),
        "method": method,
        "trend": ("increasing" if slope > 0 else "decreasing" if slope < 0 else "no trend"),
        "n_months": int(len(s)),
        "record_years": float(len(s) / 12),
        "alpha": alpha,
        "deseasonalized": bool(deseasonalize),
        "fitted": fitted,
    }


def verdict(significant: bool) -> str:
    return ("Significant" if significant
            else "Not significant yet; a longer record may reveal a trend")
