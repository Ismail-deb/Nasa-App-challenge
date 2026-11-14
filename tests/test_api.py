"""API test on a small synthetic processed file (no NASA access needed)."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from fastapi.testclient import TestClient

import common
from app import data


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path)
    t = pd.date_range("2000-01-01", periods=240, freq="MS")
    lat = np.arange(-90, 90.5, 0.5)
    lon = np.arange(-180, 180, 0.625)
    yrs = np.arange(240) / 12
    base = 285 + 8 * np.sin(2 * np.pi * t.month / 12) + 0.03 * yrs   # 0.3 K/decade
    arr = np.asarray(base)[:, None, None] * np.ones((240, len(lat), len(lon)))
    xr.DataArray(arr.astype("float32"), coords={"time": t, "lat": lat, "lon": lon},
                 dims=("time", "lat", "lon"), name="T2M").to_dataset().to_netcdf(
        tmp_path / "M2TMNXSLV_T2M.nc", engine="h5netcdf")
    data._open.cache_clear()
    from app.main import app
    return TestClient(app)


def test_trend_endpoint(client):
    r = client.get("/trend", params={"variable": "M2TMNXSLV/T2M", "bbox": "-115,31,-109,37"})
    assert r.status_code == 200, r.text
    j = r.json()
    first = 285 - 273.15 + 8 * np.sin(2 * np.pi / 12)
    assert j["units"] == "°C" and abs(j["values"][0] - first) < 1e-2
    assert abs(j["slope_per_decade"] - 0.3) < 0.02 and j["significant"]
    assert len(j["fitted"]) == len(j["values"]) == len(j["dates"])


def test_errors_and_catalog(client):
    assert client.get("/trend", params={"variable": "nope", "bbox": "0,0,1,1"}).status_code == 404
    assert client.get("/trend", params={"variable": "M2TMNXSLV/T2M", "bbox": "0,10,1,5"}).status_code == 400
    assert client.get("/variables").json()[0]["has_data"] is True
    assert client.get("/categories").status_code == 200


def test_dateline_box_and_tiny_box(client):
    e = data.find_entry("M2TMNXSLV/T2M")
    assert len(data.regional_mean(e, (170, -10, -170, 10), "2000-01", "2001-12")) == 24
    assert len(data.regional_mean(e, (10.0, 10.0, 10.01, 10.01), None, None)) == 240
