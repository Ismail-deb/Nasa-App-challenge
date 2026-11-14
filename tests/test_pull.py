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


def _grid(values, lat0=-0.4, lon0=10.05, step=0.1):
    values = np.asarray(values, dtype="float32")
    ny, nx = values.shape
    return xr.DataArray(values, dims=("lat", "lon"),
                        coords={"lat": lat0 + step * np.arange(ny), "lon": lon0 + step * np.arange(nx)})


def test_block_mean_values_and_coords():
    # 4x6 grid, factor 2 -> 2x3. Each 2x2 block mean checked by hand.
    a = np.arange(24, dtype="float32").reshape(4, 6)
    out = pull_data.block_mean(_grid(a), 2)
    assert out.shape == (2, 3) and out.dtype == np.float32
    assert out.values[0, 0] == (0 + 1 + 6 + 7) / 4
    assert out.values[1, 2] == (16 + 17 + 22 + 23) / 4
    assert np.allclose(out["lat"], [-0.35, -0.15]) and np.allclose(out["lon"], [10.1, 10.3, 10.5])


def test_block_mean_nan_handling():
    a = np.ones((4, 4), dtype="float32") * 2
    a[0, 0] = np.nan                       # partly-NaN block: mean of the 3 valid cells
    a[0, 1] = 8
    a[2:4, 2:4] = np.nan                   # all-NaN block stays NaN
    out = pull_data.block_mean(_grid(a), 2).values
    assert out[0, 0] == (8 + 2 + 2) / 3
    assert np.isnan(out[1, 1])
    assert out[0, 1] == 2 and out[1, 0] == 2


def test_block_mean_factor5_imerg_shape_and_identity():
    a = np.random.default_rng(0).random((10, 20)).astype("float32")
    g = _grid(a, lat0=-89.95, lon0=-179.95)
    out = pull_data.block_mean(g, 5)
    assert out.shape == (2, 4)
    assert np.isclose(out.values[1, 3], a[5:10, 15:20].mean())
    assert np.isclose(float(out["lat"][0]), -89.75)          # 0.5 degree cell centre
    assert pull_data.block_mean(g, 1) is g                    # factor 1 = untouched


def test_only_imerg_opts_into_coarsening():
    entries = [e for _, e in common.iter_entries(common.load_catalog())]
    coarse = {e["id"] for e in entries if "coarsen" in e}
    assert coarse == {"GPM_3IMERGM/precipitation"}


def test_projected_size_report():
    r = pull_data.projected_size_report(309, 5)
    assert "TOO BIG" in r.splitlines()[1] and "fits" in r.splitlines()[2]
