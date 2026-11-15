"""Display layer: precipitation conversion, number formatting, headlines, explanations, units.
The statistics themselves are untouched; these tests check only what is shown."""
import math

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import common
from app import data, display, presets

PRECIP = {"id": "GPM_3IMERGM/precipitation", "name": "Precipitation", "units": "mm/hr",
          "card_units": "mm/month", "relative_change": True}


# ---------------------------------------------------------------- precipitation conversion

def test_precipitation_values_hand_computed():
    s = pd.Series([0.1, 0.1, 0.05], index=pd.to_datetime(["2001-01-01", "2001-02-01", "2004-02-01"]))
    out = display.convert_values(PRECIP, s, "mm/hr")
    # Jan 2001: 0.1 mm/hr x 24 h x 31 d = 74.4 ; Feb 2001: x 28 d = 67.2 ; Feb 2004 (leap): 0.05 x 24 x 29 = 34.8
    assert np.allclose(out.values, [74.4, 67.2, 34.8])


def test_precipitation_slope_range_and_percent_convert_the_same_way():
    assert display.slope_factor(PRECIP) == pytest.approx(24 * 365.25 / 12) == pytest.approx(730.5)
    idx = pd.date_range("2000-01-01", periods=24, freq="MS")
    ser = pd.Series(0.05, index=idx)                         # mean 0.05 mm/hr
    r = {"slope_per_decade": 0.001, "ci_low_per_decade": -0.002, "ci_high_per_decade": 0.004,
         "ci_plain_low_per_decade": -0.001, "ci_plain_high_per_decade": 0.003,
         "significant": False, "trend": "increasing", "record_years": 2.0,
         "deseasonalized": True, "method": "corrected"}
    out = display.present(PRECIP, ser, pd.Series(0.05, index=idx), r, "Box A", "mm/hr")
    # 0.001 mm/hr per decade x 730.5 = 0.7305 mm/month per decade; every range end x 730.5 too
    assert out["slope_per_decade"] == pytest.approx(0.7305)
    assert (out["ci_low_per_decade"], out["ci_high_per_decade"]) == (pytest.approx(-1.461), pytest.approx(2.922))
    assert out["ci_plain_high_per_decade"] == pytest.approx(3 * 0.7305)
    # percent of the regional mean: 0.001 / 0.05 x 100 = +2% per decade (unit-free)
    assert out["percent_per_decade"] == pytest.approx(2.0)
    assert (out["ci_low_percent"], out["ci_high_percent"]) == (pytest.approx(-4.0), pytest.approx(8.0))
    assert out["units"] == "mm/month" and out["series_units"] == "mm/hr"
    assert out["fitted_display"].iloc[0] == pytest.approx(0.05 * 730.5)


def test_precipitation_refuses_unexpected_units():
    s = pd.Series([1.0], index=pd.to_datetime(["2001-01-01"]))
    with pytest.raises(ValueError):
        display.convert_values(PRECIP, s, "mm/day")
    with pytest.raises(ValueError):
        display.slope_factor({**PRECIP, "units": "kg m-2 s-1"})


def test_other_variables_are_not_converted():
    t2m = {"id": "M2TMNXSLV/T2M", "name": "Air temperature (2 m)", "units": "K", "display_units": "degC"}
    s = pd.Series([10.0, 11.0], index=pd.date_range("2001-01-01", periods=2, freq="MS"))
    assert display.convert_values(t2m, s, "°C").equals(s) and display.slope_factor(t2m) == 1.0


# ---------------------------------------------------------------- formatting

@pytest.mark.parametrize("x, text", [
    (0.4903, "+0.49"), (-0.66, "-0.66"), (12.345, "+12.35"), (0.1, "+0.10"),
    (0.004, "+0.004"), (0.00076, "+0.00076"), (-0.0023, "-0.0023"), (0.05, "+0.05"),
    (0.0995, "+0.1"), (0.00004, "about 0"), (0.0, "0"), (-0.000012, "about 0"),
])
def test_fmt_signed(x, text):
    assert display.fmt_signed(x) == text


def test_never_shows_plus_or_minus_zero_point_zero_zero():
    for x in np.concatenate([np.logspace(-8, 3, 400), -np.logspace(-8, 3, 400)]):
        s = display.fmt_signed(float(x))
        assert s not in ("+0.00", "-0.00", "0.00", "+0.0", "-0.0", "+0", "-0"), (x, s)
        if s != "about 0":
            assert float(s) != 0 and math.copysign(1, float(s)) == math.copysign(1, x)
    assert display.fmt_range(-0.0023, 0.0038) == "-0.0023 to +0.0038"


# ---------------------------------------------------------------- headline and explanation

def test_headlines():
    assert display.headline("Air temperature (2 m)", True, "increasing", "US Southwest") == \
        "Air temperature (2 m) is increasing"
    assert display.headline("Soil moisture (top 10 cm)", True, "decreasing", None) == \
        "Soil moisture (top 10 cm) is decreasing"
    h = display.headline("Precipitation", False, "decreasing", "US Southwest (Arizona and southern Nevada)")
    assert h == "No clear trend in precipitation for US Southwest (Arizona and southern Nevada)"
    assert "increasing" not in h and "decreasing" not in h
    assert display.headline("Wind speed (50 m)", False, "increasing", None) == \
        "No clear trend in wind speed (50 m) for the selected region"


def test_explanations():
    sig = display.explanation(True, 26.75, "+0.49", "°C", True, "corrected")
    assert "Significant means" in sig and "Not significant" not in sig
    no = display.explanation(False, 25.75, "+0.55", "mm/month", True, "corrected", "+2.6%")
    assert "Significant means" not in no
    assert ("Not significant means the change is within normal year-to-year variation. "
            "It does not prove there is no trend; a longer record may reveal one.") in no
    assert "+0.55 mm/month per decade (+2.6% of the average)" in no


@pytest.mark.parametrize("x, text", [
    (2.6218, "+2.6%"), (-8.07, "-8.1%"), (12.91, "+12.9%"), (0.8, "+0.8%"), (0.1, "+0.1%"),
    (-0.0059, "-0.0059%"), (0.00004, "about 0"), (0.0, "0%"),
])
def test_fmt_percent_one_decimal(x, text):
    assert display.fmt_percent(x) == text


def test_evaporation_and_snowfall_shown_in_mm_per_day():
    evap = {"id": "GLDAS_NOAH025_M/Evap_tavg", "name": "Evaporation", "units": "kg m-2 s-1", "card_units": "mm/day"}
    s = pd.Series([1e-5, 3e-5], index=pd.date_range("2001-01-01", periods=2, freq="MS"))
    # 1e-5 kg/m2/s = 1e-5 mm/s of water; x 86400 s/day = 0.864 mm/day (same for every month)
    assert np.allclose(display.convert_values(evap, s, "kg m-2 s-1").values, [0.864, 2.592])
    assert display.slope_factor(evap) == 86400.0
    with pytest.raises(ValueError):
        display.convert_values({**evap, "units": "mm/hr"}, s)


def test_unit_labels():
    cat = {e["id"]: e for _, e in common.iter_entries(common.load_catalog())}
    assert display.unit_label(cat["M2TMNXSLV/T2M"]) == "°C"
    assert display.unit_label(cat["M2TMNXSLV/WIND50M"]) == "m/s"
    assert display.unit_label(cat["GLDAS_NOAH025_M/SoilMoi0_10cm_inst"]) == "kg/m² (= mm of water)"
    assert display.unit_label(cat["GPM_3IMERGM/precipitation"]) == "mm/month"
    assert display.unit_label(cat["M2TMNXAER/TOTEXTTAU"]) == "unitless"
    assert display.unit_label(cat["M2TMNXRAD/CLDTOT"]) == "% of sky"
    assert display.unit_label(cat["M2TMNXRAD/SWGDN"]) == "W/m²"
    assert display.unit_label(cat["GLDAS_NOAH025_M/Evap_tavg"]) == "mm/day"
    assert display.unit_label(cat["GLDAS_NOAH025_M/Snowf_tavg"]) == "mm/day"
    for e in cat.values():                                   # no raw unit strings left anywhere
        assert display.unit_label(e) not in ("1", "kg m-2", "m s-1", "W m-2", "degC")


# ---------------------------------------------------------------- end to end through the API

PRESETS = {"boxa": {"name": "Box A", "bbox": [-1.0, -1.0, 1.0, 1.0], "lens": "hydro", "why": "t"}}


def test_api_precipitation_card(tmp_path, monkeypatch):
    series = tmp_path / "series"
    series.mkdir()
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path / "none")
    monkeypatch.setattr(common, "SERIES_DIR", series)
    monkeypatch.setattr(presets, "load_presets", lambda: PRESETS)
    idx = pd.date_range("2000-01-01", periods=120, freq="MS")
    rng = np.random.default_rng(1)
    vals = 0.05 + 0.01 * rng.normal(size=120)
    pd.DataFrame({"date": idx.strftime("%Y-%m"), "value": vals}).to_csv(series / "precipitation__boxa.csv", index=False)
    (series / "index.yml").write_text(
        "series:\n- {variable: GPM_3IMERGM/precipitation, region: boxa, units: mm/hr, "
        "period_start: '2000-01', period_end: '2009-12'}\n", encoding="utf-8")
    from app.main import app
    c = TestClient(app)
    q = {"variable": "GPM_3IMERGM/precipitation", "bbox": "-1,-1,1,1"}
    j = c.get("/trend", params=q).json()
    plain_stats = __import__("stats").analyze(pd.Series(vals, index=idx), deseasonalize=True)
    assert j["units"] == "mm/month" and j["series_units"] == "mm/hr"
    assert j["values"][0] == pytest.approx(round(vals[0] * 24 * 31, 4))          # Jan: 31 days
    assert j["slope_per_decade"] == pytest.approx(plain_stats["slope_per_decade"] * 730.5, abs=1e-4)
    assert j["p_value"] == pytest.approx(plain_stats["p_value"], abs=1e-5)        # statistics unchanged
    assert j["headline"] == "No clear trend in precipitation for Box A"
    assert j["slope_text"] not in ("+0.00", "-0.00") and j["percent_text"].endswith("%")
    assert "Not significant means" in j["explanation"]
    assert c.get("/timeseries", params=q).json()["values"][1] == pytest.approx(round(vals[1] * 24 * 29, 4))  # Feb 2000


def test_runoff_accumulation_shown_in_mm_per_day():
    """GLDAS Qs_acc: monthly mean of 3-hour totals (kg/m2 per 3 h); x 8 three-hour periods = mm/day."""
    q = {"id": "GLDAS_NOAH025_M/Qs_acc", "name": "Surface runoff", "units": "kg m-2",
         "accumulation_hours": 3, "card_units": "mm/day"}
    s = pd.Series([0.0089, 0.05], index=pd.date_range("2000-01-01", periods=2, freq="MS"))
    assert np.allclose(display.convert_values(q, s, "kg m-2").values, [0.0712, 0.4])
    assert display.slope_factor(q) == 8.0
    assert "x 8" in display.conversion_note(q)


def test_kg_m2_state_variables_are_never_multiplied():
    """Soil moisture and SWE are also 'kg m-2' but are amounts, not accumulations: no conversion,
    and asking for mm/day without accumulation_hours is refused rather than guessed."""
    cat = {e["id"]: e for _, e in common.iter_entries(common.load_catalog())}
    for vid in ("GLDAS_NOAH025_M/SoilMoi0_10cm_inst", "GLDAS_NOAH025_M/SWE_inst"):
        assert display.slope_factor(cat[vid]) == 1.0 and display.conversion_note(cat[vid]) is None
    with pytest.raises(ValueError):
        display.slope_factor({"id": "x", "units": "kg m-2", "card_units": "mm/day"})


def test_catalog_gldas_display_units_match_verified_file_attributes():
    cat = {e["id"]: e for _, e in common.iter_entries(common.load_catalog())}
    assert display.unit_label(cat["GLDAS_NOAH025_M/Qs_acc"]) == "mm/day"
    assert cat["GLDAS_NOAH025_M/Qs_acc"]["accumulation_hours"] == 3
    assert display.slope_factor(cat["GLDAS_NOAH025_M/Qs_acc"]) == 8.0
    assert display.slope_factor(cat["GLDAS_NOAH025_M/Evap_tavg"]) == 86400.0
    assert display.slope_factor(cat["GLDAS_NOAH025_M/Snowf_tavg"]) == 86400.0
    assert display.unit_label(cat["GLDAS_NOAH025_M/SnowDepth_inst"]) == "cm"          # shown x 100
    assert display.slope_factor(cat["GLDAS_NOAH025_M/SnowDepth_inst"]) == 100.0
    assert display.unit_label(cat["GLDAS_NOAH025_M/SWE_inst"]) == "kg/m² (= mm of water)"
    assert "NOT river flow" in cat["GLDAS_NOAH025_M/Qs_acc"]["note"]
