"""export_series finds processed files named exactly like the real desktop ones (incl. the '+'
wind file), and --list / skip reasons are never silent. Tiny synthetic files, no network."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

import common
import export_series
import pull_data
from app import data, presets

REAL_NAMES = {   # catalog id -> exact filename seen on the desktop, and the variable inside
    "GPM_3IMERGM/precipitation": ("GPM_3IMERGM_precipitation.nc", "precipitation"),
    "M2TMNXSLV/T2M": ("M2TMNXSLV_T2M.nc", "T2M"),
    "M2TMNXSLV/WIND50M": ("M2TMNXSLV_U50M+V50M.nc", "WIND50M"),
    "GLDAS_NOAH025_M/SoilMoi0_10cm_inst": ("GLDAS_NOAH025_M_SoilMoi0_10cm_inst.nc", "SoilMoi0_10cm_inst"),
    "GLDAS_NOAH025_M/Qs_acc": ("GLDAS_NOAH025_M_Qs_acc.nc", "Qs_acc"),
    "GLDAS_NOAH025_M/Evap_tavg": ("GLDAS_NOAH025_M_Evap_tavg.nc", "Evap_tavg"),
}
PRESETS = {"boxa": {"name": "Box A", "bbox": [-1.0, -1.0, 1.0, 1.0], "lens": "wind"}}
T = pd.date_range("2001-01-01", periods=12, freq="MS")
LAT, LON = np.array([-0.5, 0.5]), np.array([-0.5, 0.5])


@pytest.fixture()
def env(tmp_path, monkeypatch):
    proc, series = tmp_path / "processed", tmp_path / "series"
    proc.mkdir()
    for mod in (common, pull_data):
        monkeypatch.setattr(mod, "PROCESSED_DIR", proc)
    monkeypatch.setattr(common, "SERIES_DIR", series)
    monkeypatch.setattr(presets, "load_presets", lambda: PRESETS)
    data._open.cache_clear()
    yield proc, series
    data._open.cache_clear()


def write(path, var, value):
    xr.DataArray(np.full((12, 2, 2), value, "float32"), coords={"time": T, "lat": LAT, "lon": LON},
                 dims=("time", "lat", "lon"), name=var).to_dataset().to_netcdf(path, engine="h5netcdf")


def test_catalog_paths_are_the_real_names():
    for var_id, (name, var) in REAL_NAMES.items():
        e = data.find_entry(var_id)
        assert common.processed_path(e).name == name
        assert export_series.expected_var_name(e) == var


def test_wind_file_written_by_pull_data_is_found_with_computed_speed(env):
    """Run pull_data's own extract + writer on U50M=3, V50M=4 -> the '+' file -> export -> 5 m/s."""
    proc, series = env
    entry = data.find_entry("M2TMNXSLV/WIND50M")
    w = None
    for m in T:
        g = xr.Dataset({"U50M": (("time", "lat", "lon"), np.full((1, 2, 2), 3, "float32")),
                        "V50M": (("time", "lat", "lon"), np.full((1, 2, 2), 4, "float32"))},
                       coords={"time": [m.to_datetime64()], "lat": LAT, "lon": LON})
        da = pull_data.extract(g, entry)
        w = w or pull_data.IncrementalWriter(entry, LAT, LON)
        w.add(m, da)
    w.close()
    assert (proc / "M2TMNXSLV_U50M+V50M.nc").exists()
    report = export_series.export(["M2TMNXSLV/WIND50M"])
    assert report["written"] == ["WIND50M__boxa.csv"] and report["skipped"] == []
    assert np.allclose(pd.read_csv(series / "WIND50M__boxa.csv")["value"], 5.0)


def test_every_real_name_is_found(env):
    proc, series = env
    for var_id, (name, var) in REAL_NAMES.items():
        write(proc / name, var, 290.0 if var == "T2M" else 1.0)
    report = export_series.export(list(REAL_NAMES))
    assert report["skipped"] == []
    assert sorted(report["written"]) == sorted(f"{v.split('/')[1]}__boxa.csv" for v in REAL_NAMES)
    idx = {r["variable"]: r for r in presets.read_index()}
    assert idx["GLDAS_NOAH025_M/Qs_acc"]["units"] == "kg m-2"              # CSV values: stored units
    assert idx["GLDAS_NOAH025_M/Qs_acc"]["display_units"] == "mm/day"      # what the app shows
    assert "x 8" in idx["GLDAS_NOAH025_M/Qs_acc"]["display_conversion"]
    assert idx["M2TMNXSLV/WIND50M"]["display_units"] == "m/s"


def test_skip_reasons_and_list_mode_are_never_silent(env, capsys):
    proc, _ = env
    write(proc / "GLDAS_NOAH025_M_Evap_tavg.nc", "wrong_name", 1.0)              # variable missing
    write(proc / "GLDAS_NOAH025_M_Qs_acc.nc", "Qs_acc", np.nan)                  # empty (all NaN)
    report = export_series.export(["GLDAS_NOAH025_M/Evap_tavg", "GLDAS_NOAH025_M/Qs_acc",
                                   "GLDAS_NOAH025_M/SWE_inst"])                  # SWE: file missing
    reasons = {v: r for v, _, r in report["skipped"]}
    assert reasons["GLDAS_NOAH025_M/Evap_tavg"].startswith("variable missing")
    assert reasons["GLDAS_NOAH025_M/Qs_acc"].startswith("empty")
    assert reasons["GLDAS_NOAH025_M/SWE_inst"].startswith("file missing")
    out = capsys.readouterr().out
    assert "skip GLDAS_NOAH025_M/Evap_tavg: variable missing" in out and "expected 'Evap_tavg'" in out

    rows = export_series.list_status(["GLDAS_NOAH025_M/Evap_tavg", "GLDAS_NOAH025_M/SWE_inst"])
    out = capsys.readouterr().out
    assert rows[0]["exists"] and rows[0]["variables_found"] == ["wrong_name"] and rows[0]["problem"]
    assert not rows[1]["exists"] and rows[1]["problem"].startswith("file missing")
    assert "WOULD SKIP" in out and "GLDAS_NOAH025_M_SWE_inst.nc" in out
