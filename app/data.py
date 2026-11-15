"""Reads processed NetCDF files; area-weighted regional means; unit conversion."""
from functools import lru_cache

import numpy as np
import pandas as pd

import common
from common import iter_entries, load_catalog

# (stored units, display units) -> conversion function
CONVERSIONS = {
    ("K", "degC"): lambda x: x - 273.15,
}
UNIT_LABEL = {"degC": "°C", "K": "K"}


def find_entry(var_id: str) -> dict:
    for _, e in iter_entries(load_catalog()):
        if e["id"] == var_id:
            return e
    raise KeyError(var_id)


@lru_cache(maxsize=8)
def _open(path: str, mtime: float):
    # imported here, not at the top: the hosted app serves preset series only and does not
    # install xarray/h5netcdf (requirements-data.txt); only gridded custom regions need them
    import xarray as xr

    ds = xr.open_dataset(path, engine=common.NC_ENGINE)
    return ds[list(ds.data_vars)[0]]


def load_dataarray(entry: dict):
    p = common.processed_path(entry)
    if not p.exists():
        raise FileNotFoundError(
            f"No processed data for {entry['id']}. Run: python pull_data.py <category>")
    return _open(str(p), p.stat().st_mtime)


def parse_bbox(s: str):
    try:
        w, so, e, n = (float(x) for x in s.split(","))
    except ValueError:
        raise ValueError("bbox must be west,south,east,north (four numbers)")
    if not (-90 <= so < n <= 90):
        raise ValueError("bbox needs south < north, within -90..90")
    return w, so, e, n


def regional_mean(entry: dict, bbox, start: str | None, end: str | None) -> pd.Series:
    """cos(lat)-weighted mean over bbox=(west,south,east,north), longitudes -180..180.
    A box crossing the antimeridian (west > east) is supported. Returned in display units."""
    da = load_dataarray(entry)
    w, s, e, n = bbox
    lat = da["lat"]
    sub = da.sel(lat=slice(s, n)) if lat[0] < lat[-1] else da.sel(lat=slice(n, s))
    lon = ((sub["lon"] + 180) % 360) - 180
    sub = sub.assign_coords(lon=lon)
    mask = (lon >= w) & (lon <= e) if w <= e else (lon >= w) | (lon <= e)
    sub = sub.where(mask, drop=True)
    if sub.sizes["lat"] == 0 or sub.sizes["lon"] == 0:   # region smaller than one grid cell
        cy = (s + n) / 2
        cx = (w + e) / 2 if w <= e else ((w + e + 360) / 2 + 180) % 360 - 180
        sub = da.sel(lat=cy, lon=cx, method="nearest").expand_dims(["lat", "lon"])
    sub = sub.sel(time=slice(start, end))
    if sub.sizes["time"] == 0:
        raise ValueError("No data in the requested period.")

    weights = np.cos(np.deg2rad(sub["lat"]))
    mean = sub.weighted(weights).mean(dim=("lat", "lon"), skipna=True)
    ser = pd.Series(mean.values.astype(float),
                    index=pd.to_datetime(mean["time"].values).to_period("M").to_timestamp())
    conv = CONVERSIONS.get((entry["units"], entry.get("display_units", entry["units"])))
    return conv(ser) if conv else ser


def display_units(entry: dict) -> str:
    u = entry.get("display_units", entry["units"])
    return UNIT_LABEL.get(u, u)
