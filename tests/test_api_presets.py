"""/trend preset vs gridded routing, /presets, and friendly errors, on tiny synthetic data."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from fastapi.testclient import TestClient

import common
from app import data, presets

PRESETS = {
    "boxa": {"name": "Box A", "bbox": [-1.0, -1.0, 1.0, 61.0], "lens": "solar", "why": "test"},
    "boxb": {"name": "Box B", "bbox": [10.0, 10.0, 12.0, 12.0], "lens": "wind", "why": "test"},
}
T2M = "M2TMNXSLV/T2M"
N = 120


def write_grid(path, with_nan=False):
    """Rows at 0 and 60 deg N: 10 C and 40 C plus a 0.3 C/decade trend; cos weights 1 and 0.5."""
    t = pd.date_range("2001-01-01", periods=N, freq="MS")
    trend = 0.03 * np.arange(N) / 12
    rows = np.stack([283.15 + trend, 313.15 + trend], axis=1)            # (time, lat)
    arr = rows[:, :, None].astype("float32")
    if with_nan:
        arr[[3, 50], :, :] = np.nan                                       # two fully missing months
    xr.DataArray(arr, coords={"time": t, "lat": [0.0, 60.0], "lon": [0.0]},
                 dims=("time", "lat", "lon"), name="T2M").to_dataset().to_netcdf(path, engine="h5netcdf")


def write_series(series_dir, region, value=99.0):
    series_dir.mkdir(parents=True, exist_ok=True)
    t = pd.date_range("2001-01-01", periods=N, freq="MS")
    vals = value + 0.05 * np.arange(N) / 12
    pd.DataFrame({"date": t.strftime("%Y-%m"), "value": vals}).to_csv(series_dir / f"T2M__{region}.csv", index=False)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    proc, series = tmp_path / "processed", tmp_path / "series"
    proc.mkdir()
    monkeypatch.setattr(common, "PROCESSED_DIR", proc)
    monkeypatch.setattr(common, "SERIES_DIR", series)
    monkeypatch.setattr(presets, "load_presets", lambda: PRESETS)
    data._open.cache_clear()
    from app.main import app
    yield TestClient(app), proc, series
    data._open.cache_clear()


def trend(client, bbox, **kw):
    return client.get("/trend", params={"variable": T2M, "bbox": ",".join(map(str, bbox)), **kw})


def test_gridded_weighting_matches_hand_computation(env):
    client, proc, _ = env
    write_grid(proc / "M2TMNXSLV_T2M.nc")
    j = trend(client, (-1, -1, 1, 61)).json()                           # boxa, no series -> gridded
    assert j["source"] == "gridded" and j["region"] == "boxa"
    expected = (10 * 1.0 + 40 * 0.5) / 1.5                              # 20.0 C (plain mean: 25)
    assert abs(j["values"][0] - expected) < 1e-3
    assert abs(j["slope_per_decade"] - 0.3) < 0.01


def test_preset_bbox_served_from_series(env):
    client, proc, series = env
    write_grid(proc / "M2TMNXSLV_T2M.nc")
    write_series(series, "boxa", value=99.0)
    for bbox in [(-1, -1, 1, 61), (-1.04, -0.97, 1.03, 61.02)]:         # exact and within tolerance
        j = trend(client, bbox).json()
        assert j["source"] == "preset_series" and j["region"] == "boxa"
        assert j["values"][0] == 99.0 and len(j["values"]) == N
        assert abs(j["slope_per_decade"] - 0.5) < 0.01


def test_preset_series_used_even_without_gridded_file(env):
    client, _, series = env
    write_series(series, "boxa")
    r = trend(client, (-1, -1, 1, 61))
    assert r.status_code == 200 and r.json()["source"] == "preset_series"
    j = trend(client, (-1, -1, 1, 61), start="2003-01", end="2004-12").json()
    assert j["dates"][0] == "2003-01" and j["dates"][-1] == "2004-12" and len(j["values"]) == 24


def test_non_preset_bbox_falls_back_to_gridded(env):
    client, proc, series = env
    write_grid(proc / "M2TMNXSLV_T2M.nc")
    write_series(series, "boxa")
    j = trend(client, (-1, -1, 1, 1)).json()                            # not a preset
    assert j["source"] == "gridded" and j["region"] is None
    assert abs(j["values"][0] - 10.0) < 1e-3                            # only the 0 deg row


def test_missing_data_error_is_friendly(env):
    client, _, series = env
    write_series(series, "boxa")                                        # ready only for boxa
    r = trend(client, (10, 10, 12, 12))                                 # a preset without a series
    assert r.status_code == 404
    msg = r.json()["detail"]
    assert msg.startswith("Region/variable not available yet, try a preset.")
    assert "ready for: boxa" in msg
    r = trend(client, (-1, -1, 1, 1))                                   # not a preset: a custom region
    assert r.status_code == 404
    msg = r.json()["detail"]
    assert msg.startswith("This is a custom region")
    assert "Custom regions need the full dataset" in msg
    assert "only available on the machine that has it" in msg
    assert "ready for: boxa" in msg                                     # still says what does work
    r = client.get("/trend", params={"variable": "M2TMNXRAD/SWGDN", "bbox": "-1,-1,1,1"})
    assert r.status_code == 404 and "not ready for any preset yet" in r.json()["detail"]
    assert client.get("/timeseries", params={"variable": T2M, "bbox": "-1,-1,1,1"}).status_code == 404


def test_presets_endpoint_lists_lens_and_available_variables(env):
    client, _, series = env
    write_series(series, "boxa")
    p = {x["id"]: x for x in client.get("/presets").json()}
    assert p["boxa"]["lens"] == "solar" and p["boxa"]["variables"] == [T2M]
    assert p["boxb"]["lens"] == "wind" and p["boxb"]["variables"] == []
    assert p["boxa"]["bbox"] == [-1.0, -1.0, 1.0, 61.0]
    v = next(x for x in client.get("/variables").json() if x["id"] == T2M)
    assert v["has_data"] and v["presets_available"] == ["boxa"] and v["gridded"] is False


def test_missing_months_are_null_and_fitted_aligned(env):
    client, proc, _ = env
    write_grid(proc / "M2TMNXSLV_T2M.nc", with_nan=True)
    r = trend(client, (-1, -1, 1, 1))
    assert r.status_code == 200                                         # valid JSON despite NaN
    j = r.json()
    assert j["values"][3] is None and j["values"][50] is None
    assert len(j["fitted"]) == len(j["values"]) == len(j["dates"]) == N
    assert j["fitted"][3] is None and j["fitted"][4] is not None
    assert j["n_months"] == N - 2


def test_variables_report_real_data_period_from_index(env):
    client, _, series = env
    series.mkdir(parents=True, exist_ok=True)
    (series / "index.yml").write_text(
        "series:\n"
        "- {variable: M2TMNXSLV/T2M, region: boxa, period_start: '2000-01', period_end: '2026-09'}\n"
        "- {variable: M2TMNXSLV/T2M, region: boxb, period_start: '2001-01', period_end: '2026-07'}\n",
        encoding="utf-8")
    v = {x["id"]: x for x in client.get("/variables").json()}
    assert (v[T2M]["period_start"], v[T2M]["period_end"]) == ("2000-01", "2026-09")
    assert v["M2TMNXRAD/SWGDN"]["period_start"] is None
