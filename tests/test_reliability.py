"""Reliability of trend tests for zero-inflated snow series, and display rounding of tiny
significant results. Synthetic series only (plus one read-only check of the committed series)."""
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import common
import stats
from app import data, display, presets

IDX = pd.date_range("2000-01-01", periods=240, freq="MS")      # 20 years
RNG = np.random.default_rng(7)


def snow(winter_months, amount=50.0, idx=IDX):
    """Snow only in the given calendar months (value ~amount), exactly 0 in the others."""
    v = np.where(np.isin(idx.month, winter_months), amount * (1 + 0.3 * RNG.random(len(idx))), 0.0)
    return pd.Series(v, index=idx)


# ---------------------------------------------------------------- stats.reliability

def test_mostly_zero_series_is_flagged_low():
    s = snow([12, 1, 2, 3])                                     # 8 of 12 months zero = 67%
    r = stats.reliability(s, min_seasonal_peak=2.0)
    assert r["reliability"] == "low" and r["trigger"] == "ties"
    assert r["share_zero"] == pytest.approx(8 / 12)


def test_normal_series_is_ok():
    s = pd.Series(10 + RNG.normal(size=240), index=IDX)
    assert stats.reliability(s, min_seasonal_peak=2.0)["reliability"] == "ok"


def test_forty_percent_zeros_is_still_ok():
    s = snow([10, 11, 12, 1, 2, 3, 4])                          # 5 of 12 months zero = 42%
    r = stats.reliability(s, min_seasonal_peak=2.0)
    assert r["share_zero"] == pytest.approx(5 / 12) and r["reliability"] == "ok"
    s = pd.Series(np.where(np.arange(240) % 5 < 2, 0.0, 30.0 + RNG.random(240)), index=IDX)  # exactly 40%
    assert stats.reliability(s, 2.0)["reliability"] == "ok"


def test_snow_free_summers_are_seasonality_not_unreliable():
    """Pacific Northwest pattern: half the year snow-free, a large winter peak -> ok."""
    s = snow([11, 12, 1, 2, 3, 4])                              # exactly 50% zero: not MORE than 50%
    r = stats.reliability(s, min_seasonal_peak=2.0)
    assert r["share_zero"] == pytest.approx(0.5) and r["reliability"] == "ok"
    assert r["seasonal_peak"] > 40


def test_low_seasonal_peak_is_flagged_even_without_zeros():
    s = snow([12, 1, 2, 3, 4, 5, 6, 7, 8], amount=0.5)         # never more than ~0.65 at its peak
    r = stats.reliability(s, min_seasonal_peak=2.0)
    assert r["share_zero"] < 0.5 and r["reliability"] == "low" and r["trigger"] == "seasonal_peak"
    assert stats.reliability(s, min_seasonal_peak=0.1)["reliability"] == "ok"


def test_seasonal_peak_is_the_largest_calendar_month_mean():
    s = pd.Series(0.0, index=IDX)
    s[s.index.month == 2] = np.tile([1.0, 3.0], 10)             # February mean = 2
    s[s.index.month == 1] = 1.5
    assert stats.seasonal_peak(s) == pytest.approx(2.0)


def test_ties_at_a_nonzero_value_also_count():
    s = pd.Series(np.where(np.arange(240) % 3 == 0, 5.0 + RNG.random(240), 7.0), index=IDX)  # 67% at 7.0
    r = stats.reliability(s)
    assert r["share_zero"] == 0 and r["share_tied"] > 0.5 and r["reliability"] == "low"


# ---------------------------------------------------------------- display

SNOWDEPTH = {"id": "GLDAS_NOAH025_M/SnowDepth_inst", "name": "Snow depth", "units": "m", "card_units": "cm",
             "zero_inflated": True, "min_seasonal_peak": 1.0}


def _r(slope, significant):
    return {"slope_per_decade": slope, "ci_low_per_decade": slope * 2, "ci_high_per_decade": slope / 2,
            "ci_plain_low_per_decade": slope * 2, "ci_plain_high_per_decade": slope / 2,
            "significant": significant, "trend": "decreasing", "record_years": 20.0,
            "deseasonalized": True, "method": "corrected", "p_value": 0.001}


def test_significant_tiny_result_never_says_about_zero():
    idx = IDX[:24]
    ser = pd.Series(0.01, index=idx)
    out = display.present(SNOWDEPTH, ser, ser, _r(-4.66e-8, True), "Box A", "m")   # -4.66e-6 cm
    assert out["headline"] == "Snow depth is decreasing"
    assert "about 0" not in out["slope_text"] and "about 0" not in out["range_text"]
    assert out["slope_text"] == "-0.0000047" and "-0.0000047 cm per decade" in out["explanation"]
    tiny = display.present(SNOWDEPTH, ser, ser, _r(-4.66e-11, True), "Box A", "m")
    assert tiny["slope_text"] == "-4.7e-09"                    # scientific form below 0.000001
    # not significant: 'about 0' is honest and allowed
    assert display.present(SNOWDEPTH, ser, ser, _r(-4.65e-8, False), "Box A", "m")["slope_text"] == "about 0"


@pytest.mark.parametrize("x, text", [(-0.00004, "-0.00004"), (0.0000123, "+0.000012"),
                                     (-3.2e-8, "-3.2e-08"), (0.49, "+0.49"), (0.0, "0")])
def test_fmt_signed_precise(x, text):
    assert display.fmt_signed(x, precise=True) == text


def test_snow_depth_shown_in_centimetres():
    s = pd.Series([0.0154, 0.0], index=IDX[:2])
    assert np.allclose(display.convert_values(SNOWDEPTH, s, "m").values, [1.54, 0.0])
    assert display.unit_label(SNOWDEPTH) == "cm" and display.slope_factor(SNOWDEPTH) == 100.0


def test_low_reliability_card_text():
    ser = pd.Series(0.001, index=IDX[:24])
    rel = {"reliability": "low", "trigger": "seasonal_peak", "seasonal_peak": 0.0037,
           "share_zero": 0.23, "share_tied": 0.23}
    out = display.present(SNOWDEPTH, ser, ser, _r(-4.65e-6, True), "US Southwest", "m", rel)
    assert out["verdict"] == "Not enough snow in this region to test a trend reliably"
    assert out["reliability"] == "low"
    assert "0.37 cm" in out["reliability_reason"] and "1 cm" in out["reliability_reason"]
    assert "is decreasing" not in out["headline"] and "Significant means" not in out["explanation"]
    assert out["slope_per_decade"] == pytest.approx(-4.65e-4)  # the numbers are still there
    ties = display.present(SNOWDEPTH, ser, ser, _r(-1e-6, False), None, "m",
                           {**rel, "trigger": "ties", "share_zero": 0.62, "share_tied": 0.62})
    assert ties["reliability_reason"].startswith("62% of months have no snow at all")
    ok = display.present(SNOWDEPTH, ser, ser, _r(-1e-3, True), None, "m", {**rel, "reliability": "ok"})
    assert ok["verdict"] == "Significant" and ok["reliability_reason"] is None


# ---------------------------------------------------------------- through the API

PRESETS = {"boxa": {"name": "Box A", "bbox": [-1.0, -1.0, 1.0, 1.0], "lens": "hydro", "why": "t"}}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    series = tmp_path / "series"
    series.mkdir()
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path / "none")
    monkeypatch.setattr(common, "SERIES_DIR", series)
    monkeypatch.setattr(presets, "load_presets", lambda: PRESETS)
    from app.main import app

    def put(var_key, var_id, units, values):
        pd.DataFrame({"date": IDX.strftime("%Y-%m"), "value": values}).to_csv(
            series / f"{var_key}__boxa.csv", index=False)
        with open(series / "index.yml", "a", encoding="utf-8") as f:
            if f.tell() == 0:
                f.write("series:\n")
            f.write(f"- {{variable: {var_id}, region: boxa, units: '{units}', "
                    f"period_start: '2000-01', period_end: '2019-12'}}\n")
    return TestClient(app), put


def test_api_low_reliability_snow(client):
    c, put = client
    trend = np.linspace(0.004, 0.002, 240)                     # metres: peak well under 1 cm
    put("SnowDepth_inst", "GLDAS_NOAH025_M/SnowDepth_inst", "m",
        np.where(np.isin(IDX.month, [12, 1, 2, 3, 4, 5, 6, 7]), trend, 0.0))
    j = c.get("/trend", params={"variable": "GLDAS_NOAH025_M/SnowDepth_inst", "bbox": "-1,-1,1,1"}).json()
    assert j["reliability"] == "low" and j["reliability_reason"].startswith("Even in its snowiest month")
    assert j["verdict"] == "Not enough snow in this region to test a trend reliably"
    assert j["lens_message"] is None
    assert j["units"] == "cm" and j["seasonal_peak"] < 1.0
    assert {"slope_per_decade", "p_value", "significant", "ci_low_per_decade"} <= set(j)  # numbers kept


def test_api_variables_that_are_not_zero_inflated_are_not_checked(client):
    c, put = client
    put("precipitation", "GPM_3IMERGM/precipitation", "mm/hr", np.where(np.arange(240) % 3, 0.0, 0.1))
    j = c.get("/trend", params={"variable": "GPM_3IMERGM/precipitation", "bbox": "-1,-1,1,1"}).json()
    assert j["reliability"] == "ok" and j["reliability_reason"] is None and j["seasonal_peak"] is None


def test_catalog_marks_exactly_the_three_snow_variables():
    flagged = {e["id"] for _, e in common.iter_entries(common.load_catalog()) if e.get("zero_inflated")}
    assert flagged == {"GLDAS_NOAH025_M/SnowDepth_inst", "GLDAS_NOAH025_M/SWE_inst",
                       "GLDAS_NOAH025_M/Snowf_tavg"}
    for vid in flagged:
        assert data.find_entry(vid)["min_seasonal_peak"] > 0


def test_committed_preset_series_flagged_low():
    """Read-only check of the committed data/series/: which preset series are flagged."""
    from app.main import _reliability
    low = set()
    for r in presets.read_index():
        e = data.find_entry(r["variable"])
        ser = presets.load_series(e, r["region"])
        rel = _reliability(e, ser, r["units"])
        if rel and rel["reliability"] == "low":
            low.add((presets.var_key(e), r["region"]))
    assert low == {("SnowDepth_inst", "southwest"), ("SWE_inst", "southwest")}
