import numpy as np
import pandas as pd

from stats import analyze, remove_seasonal_cycle


def make(n_years=30, trend_per_decade=0.0, noise=0.5, seasonal=10.0, seed=0):
    idx = pd.date_range("1990-01-01", periods=n_years * 12, freq="MS")
    rng = np.random.default_rng(seed)
    yrs = np.arange(len(idx)) / 12
    y = (seasonal * np.sin(2 * np.pi * idx.month / 12)
         + trend_per_decade * yrs / 10 + rng.normal(0, noise, len(idx)))
    return pd.Series(y, index=idx)


def test_known_trend_recovered_and_significant():
    r = analyze(make(trend_per_decade=0.4), deseasonalize=True)
    assert abs(r["slope_per_decade"] - 0.4) < 0.1
    assert r["ci_low_per_decade"] < 0.4 < r["ci_high_per_decade"]
    assert r["significant"] and r["p_value"] < 0.001
    assert r["trend"] == "increasing"
    assert r["record_years"] == 30


def test_negative_trend():
    r = analyze(make(trend_per_decade=-0.4), deseasonalize=True)
    assert r["slope_per_decade"] < 0 and r["significant"] and r["trend"] == "decreasing"


def test_pure_noise_not_significant():
    r = analyze(make(noise=1.0, seasonal=0.0, seed=3))
    assert not r["significant"]
    assert r["p_value"] > 0.05
    assert abs(r["slope_per_decade"]) < 0.3


def test_seasonal_removal_zeroes_climatology():
    d = remove_seasonal_cycle(make(seasonal=10.0))
    assert abs(d.groupby(d.index.month).mean()).max() < 1e-9


def test_nan_months_handled():
    s = make(trend_per_decade=0.4)
    s.iloc[[5, 40, 41, 200]] = np.nan
    r = analyze(s, deseasonalize=True)
    assert abs(r["slope_per_decade"] - 0.4) < 0.15 and r["n_months"] == len(s) - 4


# ---------------------------------------------------------------- significance method

import pytest

from stats import METHODS, mann_kendall_p

N_SEEDS = 200


def ar1(n, phi, seed, sigma=1.0):
    """AR(1) noise with NO trend: each month keeps a fraction phi of the previous month."""
    rng = np.random.default_rng(seed)
    e = rng.normal(0, sigma, n + 100)
    x = np.zeros(n + 100)
    for i in range(1, n + 100):
        x[i] = phi * x[i - 1] + e[i]
    return pd.Series(x[100:], index=pd.date_range("2000-01-01", periods=n, freq="MS"))


def false_positive_rate(method, phi, n=321):
    hits = sum(analyze(ar1(n, phi, seed), method=method)["significant"] for seed in range(N_SEEDS))
    return hits / N_SEEDS


@pytest.mark.parametrize("method", METHODS)
def test_known_trend_plus_noise_is_significant(method):
    r = analyze(make(trend_per_decade=0.4), deseasonalize=True, method=method)
    assert r["significant"] and r["p_value"] < 0.001 and r["method"] == method
    assert abs(r["slope_per_decade"] - 0.4) < 0.1


@pytest.mark.parametrize("method", METHODS)
def test_white_noise_is_not_significant(method):
    r = analyze(make(noise=1.0, seasonal=0.0, seed=3), method=method)
    assert not r["significant"] and r["p_value"] > 0.05


def test_trend_in_autocorrelated_noise_still_detected():
    s = ar1(321, 0.6, seed=1) + 1.0 * np.arange(321) / 120      # 1 sd per decade
    assert analyze(s, method="corrected")["significant"]


def test_ar1_false_positives_much_lower_with_correction():
    """AR(1) noise (phi=0.6), no trend, 200 seeds: the plain test cries wolf far more often."""
    plain = false_positive_rate("plain", 0.6)
    corrected = false_positive_rate("corrected", 0.6)
    print(f"\nAR(1) phi=0.6, {N_SEEDS} seeds: false positives plain={plain:.1%} corrected={corrected:.1%}")
    assert plain > 0.20                      # the problem is real
    assert corrected < 0.12                  # close to the nominal 5%
    assert corrected < plain / 2             # "noticeably less often"


def test_white_noise_false_positive_rate_stays_nominal():
    """The correction must not invent significance when there is no autocorrelation."""
    corrected = false_positive_rate("corrected", 0.0)
    print(f"\nwhite noise, {N_SEEDS} seeds: false positives corrected={corrected:.1%}")
    assert corrected < 0.10


def test_method_changes_only_the_p_value():
    s = ar1(321, 0.6, seed=5)
    a, b = analyze(s, method="plain"), analyze(s, method="corrected")
    for k in ("slope_per_decade", "ci_low_per_decade", "ci_high_per_decade", "n_months", "record_years"):
        assert a[k] == b[k]
    assert b["p_value"] > a["p_value"]       # persistence -> less evidence -> larger p


def test_missing_months_work_with_corrected_method():
    s = make(trend_per_decade=0.4)
    s.iloc[[5, 40, 41, 200]] = np.nan
    s.iloc[100:106] = np.nan                 # a six-month gap
    r = analyze(s, deseasonalize=True, method="corrected")
    assert r["n_months"] == len(s) - 10 and r["record_years"] == (len(s) - 10) / 12
    assert abs(r["slope_per_decade"] - 0.4) < 0.15 and r["significant"]
    assert np.isfinite(r["p_value"])


def test_unknown_method_rejected():
    with pytest.raises(ValueError):
        analyze(make(), method="magic")
    with pytest.raises(ValueError):
        mann_kendall_p(np.arange(20.0), method="magic")
