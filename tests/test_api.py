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
    t2m = [v for v in client.get("/variables").json() if v["id"] == "M2TMNXSLV/T2M"][0]
    assert t2m["has_data"] is True
    assert client.get("/categories").status_code == 200


def test_dateline_box_and_tiny_box(client):
    e = data.find_entry("M2TMNXSLV/T2M")
    assert len(data.regional_mean(e, (170, -10, -170, 10), "2000-01", "2001-12")) == 24
    assert len(data.regional_mean(e, (10.0, 10.0, 10.01, 10.01), None, None)) == 240


def test_trend_method_parameter_and_added_fields(client):
    q = {"variable": "M2TMNXSLV/T2M", "bbox": "-115,31,-109,37"}
    default = client.get("/trend", params=q).json()
    plain = client.get("/trend", params={**q, "method": "plain"}).json()
    assert default["method"] == "corrected" and plain["method"] == "plain"
    assert default["record_years"] == 20.0                       # 240 months
    assert default["slope_per_decade"] == plain["slope_per_decade"]
    assert set(plain) == set(default)                            # same response shape
    assert client.get("/trend", params={**q, "method": "magic"}).status_code == 400


def test_non_significant_result_message_and_record_length(client, tmp_path):
    """A flat series: verdict says 'not significant yet...' and the record length is reported."""
    import pandas as pd, xarray as xr, numpy as np
    t = pd.date_range("2000-01-01", periods=120, freq="MS")
    rng = np.random.default_rng(3)
    arr = (285 + rng.normal(0, 1, 120))[:, None, None] * np.ones((120, 4, 4))
    xr.DataArray(arr.astype("float32"), coords={"time": t, "lat": [30.0, 31, 32, 33], "lon": [-112.0, -111, -110, -109]},
                 dims=("time", "lat", "lon"), name="T2M").to_dataset().to_netcdf(
        tmp_path / "M2TMNXSLV_T2M.nc", engine="h5netcdf")
    data._open.cache_clear()
    j = client.get("/trend", params={"variable": "M2TMNXSLV/T2M", "bbox": "-112,30,-109,33"}).json()
    assert j["significant"] is False
    assert j["verdict"] == "Not significant yet; a longer record may reveal a trend"
    assert j["record_years"] == 10.0 and j["method"] == "corrected"
