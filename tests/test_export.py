"""export_series.py on a tiny synthetic gridded file (no NASA data, no network)."""
import gc

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import common
import export_series
from app import data, presets

PRESETS = {
    "boxa": {"name": "Box A", "bbox": [-1.0, -1.0, 1.0, 61.0], "lens": "solar"},
    "boxb": {"name": "Box B", "bbox": [-1.0, -1.0, 1.0, 1.0], "lens": "wind"},
}


def write_grid(path, kelvin_by_lat):
    """Two latitude rows (0 and 60 deg N), one lon column, 24 months, value constant per row."""
    t = pd.date_range("2001-01-01", periods=24, freq="MS")
    lat = np.array([0.0, 60.0])
    arr = np.array(kelvin_by_lat, dtype="float32")[None, :, None] * np.ones((24, 2, 1), "float32")
    xr.DataArray(arr, coords={"time": t, "lat": lat, "lon": [0.0]}, dims=("time", "lat", "lon"),
                 name="T2M").to_dataset().to_netcdf(path, engine="h5netcdf")


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


def test_cos_latitude_weighting_matches_hand_computation(env):
    proc, series = env
    # 0 deg row = 283.15 K (10 C), 60 deg row = 313.15 K (40 C); cos weights 1 and 0.5
    write_grid(proc / "M2TMNXSLV_T2M.nc", [283.15, 313.15])
    export_series.export(["M2TMNXSLV/T2M"])
    df = pd.read_csv(series / "T2M__boxa.csv")
    expected = (10 * 1.0 + 40 * 0.5) / (1.0 + 0.5)            # = 20.0 C, not the plain mean 25
    assert list(df.columns) == ["date", "value"] and len(df) == 24
    assert np.allclose(df["value"], expected, atol=1e-4)
    assert df["date"].iloc[0] == "2001-01"
    assert np.allclose(pd.read_csv(series / "T2M__boxb.csv")["value"], 10.0, atol=1e-4)  # 0 deg row only


def test_index_contents_and_missing_sources_skipped(env, capsys):
    proc, series = env
    write_grid(proc / "M2TMNXSLV_T2M.nc", [283.15, 313.15])
    report = export_series.export()                           # all 5 variables, only T2M present
    assert sorted(report["written"]) == ["T2M__boxa.csv", "T2M__boxb.csv"]
    assert len(report["skipped"]) == 4
    assert "skip GPM_3IMERGM/precipitation" in capsys.readouterr().out
    idx = presets.read_index()
    assert len(idx) == 2
    r = next(x for x in idx if x["region"] == "boxa")
    assert r["variable"] == "M2TMNXSLV/T2M" and r["units"] == "°C" and r["origin"] == "pipeline"
    assert r["source"] == "NASA M2TMNXSLV v5.12.4" and r["bbox"] == [-1.0, -1.0, 1.0, 61.0]
    assert (r["period_start"], r["period_end"], r["n_months"]) == ("2001-01", "2002-12", 24)


def test_rerun_keeps_series_exported_elsewhere_and_is_deterministic(env):
    proc, series = env
    write_grid(proc / "M2TMNXSLV_T2M.nc", [283.15, 313.15])
    export_series.export(["M2TMNXSLV/T2M"])
    first = (series / "index.yml").read_text(encoding="utf-8")
    data._open.cache_clear()                                  # release the backend's open handle
    gc.collect()                                              # (Windows will not delete an open file)
    (proc / "M2TMNXSLV_T2M.nc").unlink()                      # e.g. a machine without gridded T2M
    report = export_series.export(["M2TMNXSLV/T2M"])
    assert report["written"] == [] and sorted(report["kept"]) == ["T2M__boxa.csv", "T2M__boxb.csv"]
    assert (series / "T2M__boxa.csv").exists()
    assert (series / "index.yml").read_text(encoding="utf-8") == first       # unchanged
    assert not list(series.glob("*.part-*"))


def test_index_carries_notes_and_refreshes_them_for_kept_series(env):
    proc, series = env
    write_grid(proc / "M2TMNXSLV_T2M.nc", [283.15, 313.15])
    export_series.export(["M2TMNXSLV/T2M"])
    r = presets.read_index()[0]
    assert r["description"].startswith("How warm the air") and "reanalysis" in r["note"]
    # a series kept from another machine with an OLD index entry (no note) gets the catalog note
    idx = (series / "index.yml").read_text(encoding="utf-8")
    import re
    (series / "index.yml").write_text(re.sub(r"\n  (description|note):.*", "", idx), encoding="utf-8")
    assert "note" not in presets.read_index()[0]
    data._open.cache_clear(); gc.collect()
    (proc / "M2TMNXSLV_T2M.nc").unlink()
    export_series.export(["M2TMNXSLV/T2M"])
    assert all("reanalysis" in r["note"] for r in presets.read_index())
