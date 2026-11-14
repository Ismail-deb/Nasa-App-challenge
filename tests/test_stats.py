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
