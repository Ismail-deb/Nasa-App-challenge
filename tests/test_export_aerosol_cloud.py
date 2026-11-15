"""Aerosol optical depth (M2TMNXAER/TOTEXTTAU) and cloud cover (M2TMNXRAD/CLDTOT): export,
honest labels, display units, and refusal of unknown or mismatched units. Synthetic files only."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

import common
import export_series
from app import data, display, presets

PRESETS = {"boxa": {"name": "Box A", "bbox": [-1.0, -1.0, 1.0, 1.0], "lens": "solar"}}


def write_var(path, name, value, units):
    """One grid cell at (0, 0), 24 months of a constant value, with an optional units attribute."""
    t = pd.date_range("2001-01-01", periods=24, freq="MS")
    da = xr.DataArray(np.full((24, 1, 1), value, "float32"),
                      coords={"time": t, "lat": [0.0], "lon": [0.0]}, dims=("time", "lat", "lon"), name=name)
    if units is not None:
        da.attrs["units"] = units
    da.to_dataset().to_netcdf(path, engine="h5netcdf")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    proc, series = tmp_path / "processed", tmp_path / "series"
    proc.mkdir()
    monkeypatch.setattr(common, "PROCESSED_DIR", proc)
    monkeypatch.setattr(common, "SERIES_DIR", series)
    monkeypatch.setattr(presets, "load_presets", lambda: PRESETS)
    data._open.cache_clear()
    yield proc, series
    data._open.cache_clear()


def test_both_variables_are_exported():
    assert "M2TMNXAER/TOTEXTTAU" in export_series.VARIABLES
    assert "M2TMNXRAD/CLDTOT" in export_series.VARIABLES


def test_aod_exported_unitless_with_honest_label(env):
    proc, series = env
    write_var(proc / "M2TMNXAER_TOTEXTTAU.nc", "TOTEXTTAU", 0.12, "1")
    report = export_series.export(["M2TMNXAER/TOTEXTTAU"])
    assert report["written"] == ["TOTEXTTAU__boxa.csv"]
    assert np.allclose(pd.read_csv(series / "TOTEXTTAU__boxa.csv")["value"], 0.12, atol=1e-6)
    r = presets.read_index()[0]
    assert r["units"] == "1" and r["display_units"] == "unitless" and r["display_conversion"] is None
    assert r["note"].startswith("Aerosol optical depth, unitless; higher means more particles such as "
                                "smoke or dust blocking sunlight.")


def test_cloud_cover_exported_as_fraction_and_shown_as_percent(env):
    proc, series = env
    write_var(proc / "M2TMNXRAD_CLDTOT.nc", "CLDTOT", 0.4, "1")
    export_series.export(["M2TMNXRAD/CLDTOT"])
    assert np.allclose(pd.read_csv(series / "CLDTOT__boxa.csv")["value"], 0.4, atol=1e-6)  # CSV stays a fraction
    r = presets.read_index()[0]
    assert r["units"] == "1" and r["display_units"] == "% of sky"
    assert "x 100" in r["display_conversion"] and "percentage points" in r["display_conversion"]
    assert r["note"].startswith("Fraction of sky covered, displayed as %.")


def test_cloud_cover_display_conversion_hand_computed():
    cld = data.find_entry("M2TMNXRAD/CLDTOT")
    s = pd.Series([0.25, 0.6], index=pd.date_range("2001-01-01", periods=2, freq="MS"))
    assert np.allclose(display.convert_values(cld, s, "1").values, [25.0, 60.0])
    assert display.slope_factor(cld) == 100.0                       # slope and range ends x 100 too
    aod = data.find_entry("M2TMNXAER/TOTEXTTAU")
    assert display.slope_factor(aod) == 1.0 and display.convert_values(aod, s, "1").equals(s)


def test_percent_conversion_refuses_unknown_units():
    s = pd.Series([0.5], index=pd.to_datetime(["2001-01-01"]))
    with pytest.raises(ValueError):                                 # stored % would become 0..10000
        display.convert_values({"id": "x", "units": "%", "card_units": "%"}, s)
    with pytest.raises(ValueError):
        display.slope_factor({"id": "x", "units": "W m-2", "card_units": "%"})
    with pytest.raises(ValueError):                                 # series stored in other units
        display.convert_values(data.find_entry("M2TMNXRAD/CLDTOT"), s, "%")


def test_file_units_attribute_must_match_catalog(env, capsys):
    proc, series = env
    write_var(proc / "M2TMNXRAD_CLDTOT.nc", "CLDTOT", 40.0, "%")    # someone stored percent
    report = export_series.export(["M2TMNXRAD/CLDTOT"])
    assert report["written"] == []
    (_, _, reason), = report["skipped"]
    assert reason.startswith("units mismatch") and "'%'" in reason
    assert "skip M2TMNXRAD/CLDTOT: units mismatch" in capsys.readouterr().out
    assert not (series / "CLDTOT__boxa.csv").exists()


def test_unknown_conversion_in_catalog_refuses_before_writing(env, monkeypatch):
    proc, series = env
    write_var(proc / "M2TMNXAER_TOTEXTTAU.nc", "TOTEXTTAU", 0.12, "1")
    real = data.find_entry
    monkeypatch.setattr(data, "find_entry",
                        lambda v: {**real(v), "card_units": "mm/day"} if v == "M2TMNXAER/TOTEXTTAU" else real(v))
    monkeypatch.setattr(export_series.data, "find_entry", data.find_entry)
    with pytest.raises(SystemExit, match="unknown unit combination"):
        export_series.export(["M2TMNXAER/TOTEXTTAU"])
    assert not series.exists() or not list(series.iterdir())       # nothing written


def test_every_skip_prints_a_reason(env, capsys):
    report = export_series.export()                                 # nothing present at all
    out = capsys.readouterr().out
    assert len(report["skipped"]) == len(export_series.VARIABLES)
    for var_id, region, reason in report["skipped"]:
        assert reason and f"skip {var_id}: {reason}" in out
