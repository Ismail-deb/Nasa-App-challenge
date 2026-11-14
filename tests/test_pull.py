"""Offline tests for the extraction/processing helpers in pull_data (no NASA access)."""
import numpy as np
import pandas as pd
import xarray as xr

import common
import pull_data


def granule(var, arr, dims=("time", "lat", "lon"), lat=None, lon=None):
    lat = np.arange(4.0) if lat is None else lat
    lon = np.arange(5.0) if lon is None else lon
    return xr.Dataset({var: (dims, arr)}, coords={"time": [np.datetime64("2001-03-01")],
                                                   "lat": lat, "lon": lon})


def test_extract_plain_masks_fill_values():
    arr = np.ones((1, 4, 5), dtype="float32")
    arr[0, 0, 0] = 9.9e20
    da = pull_data.extract(granule("T2M", arr), {"id": "X/T2M", "variable": "T2M"})
    assert da.dims == ("lat", "lon") and da.dtype == np.float32
    assert np.isnan(da.values[0, 0]) and da.values[1, 1] == 1


def test_extract_transposes_imerg_order():
    arr = np.arange(5 * 4, dtype="float32").reshape(1, 5, 4)    # (time, lon, lat)
    da = pull_data.extract(granule("precipitation", arr, dims=("time", "lon", "lat")),
                           {"id": "X/p", "variable": "precipitation"})
    assert da.dims == ("lat", "lon") and da.shape == (4, 5)
    assert da.values[2, 3] == arr[0, 3, 2]


def test_extract_wind_speed():
    ds = granule("U50M", np.full((1, 4, 5), 3, "float32"))
    ds["V50M"] = (("time", "lat", "lon"), np.full((1, 4, 5), 4, "float32"))
    da = pull_data.extract(ds, {"id": "X/W", "variable": ["U50M", "V50M"], "derive": "speed"})
    assert np.allclose(da.values, 5)


def test_granule_month_and_incremental_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(pull_data, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(pull_data, "processed_path", lambda e: tmp_path / "S_T2M.nc")
    ds = granule("T2M", np.ones((1, 4, 5), "float32"))
    assert pull_data.granule_month(ds, "f") == pd.Timestamp("2001-03-01")
    entry = {"id": "S/T2M", "short_name": "S", "variable": "T2M", "units": "K", "version": "1"}
    w = pull_data.IncrementalWriter(entry, np.arange(4.0), np.arange(5.0))
    w.FLUSH = 5                                        # force several flushes
    for k, m in enumerate(pd.date_range("2001-01-01", periods=13, freq="MS")):
        w.add(m, pull_data.extract(ds, entry) * k)
    w.close()
    out = xr.open_dataset(tmp_path / "S_T2M.nc", engine="h5netcdf")
    assert out["T2M"].dims == ("time", "lat", "lon") and out.sizes["time"] == 13
    assert out["time"].dt.strftime("%Y-%m").values[[0, 12]].tolist() == ["2001-01", "2002-01"]
    assert out["T2M"].isel(time=7).values[1, 1] == 7 and out["T2M"].attrs["units"] == "K"
