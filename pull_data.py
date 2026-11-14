"""Download monthly granules for one category and write processed NetCDF files (native resolution).

    python pull_data.py weather_climate [--start 2000-01] [--end 2024-12] [--keep-raw] [--force]

- Entries that share a NASA collection (e.g. all MERRA-2 SLV variables) are served by ONE
  download of each granule; every needed variable is extracted from it.
- Each raw granule is deleted after extraction (unless --keep-raw).
- No resampling: grids stay at the dataset's native resolution. Missing values -> NaN.
- Output: data/processed/<short>_<var>.nc, float32, dims (time, lat, lon), gzip-compressed,
  tiled 90x90 in space and 12 months in time. Written incrementally, so RAM use stays small.
- Existing outputs are skipped unless --force.
"""
import argparse
import os
import shutil
from collections import defaultdict

import numpy as np
import pandas as pd
import xarray as xr

from common import NC_ENGINE, PROCESSED_DIR, RAW_DIR, earthdata_login, iter_entries, load_catalog, processed_path

FILL_LIMIT = 1e15   # safety net: anything this large is a fill value, not data


def open_granule(path: str, group: str | None) -> xr.Dataset:
    return xr.open_dataset(path, engine=NC_ENGINE, group=group)


def extract(ds: xr.Dataset, entry: dict) -> xr.DataArray:
    """Return one month as a float32 (lat, lon) array for a catalog entry (handles derived vars)."""
    v = entry["variable"]
    if entry.get("derive") == "speed":
        u, w = (ds[n].isel(time=0) if "time" in ds[n].dims else ds[n] for n in v)
        da = np.hypot(u, w)
    elif isinstance(v, list):
        raise ValueError(f"Unsupported derive {entry.get('derive')!r} for {entry['id']}")
    else:
        da = ds[v]
        if "time" in da.dims:
            da = da.isel(time=0)
    da = da.transpose("lat", "lon").astype("float32")
    da = da.where(np.abs(da) < FILL_LIMIT)
    return da.drop_vars([c for c in da.coords if c not in ("lat", "lon")]).load()


def granule_month(ds: xr.Dataset, path: str) -> pd.Timestamp:
    """First day of the granule's month, whatever calendar type the file uses."""
    t = ds["time"].values.ravel()[0]
    try:
        return pd.Timestamp(t).to_period("M").to_timestamp()
    except (TypeError, ValueError):            # cftime objects
        return pd.Timestamp(t.year, t.month, 1)


class IncrementalWriter:
    """Append monthly (lat, lon) arrays to a NetCDF4 file, flushing every FLUSH months, so memory
    stays small even for 0.1 degree IMERG. Readable by xarray like any NetCDF file."""
    FLUSH = 12

    def __init__(self, entry: dict, lat, lon):
        import h5netcdf

        self.entry, self.buf, self.n = entry, [], 0
        self.name = entry["variable"] if isinstance(entry["variable"], str) else entry["id"].split("/")[1]
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        self.path = processed_path(entry)
        self.tmp = self.path.with_suffix(".part")
        self.f = h5netcdf.File(self.tmp, "w")
        self.f.dimensions = {"time": None, "lat": len(lat), "lon": len(lon)}
        for nm, vals, units in (("lat", lat, "degrees_north"), ("lon", lon, "degrees_east")):
            v = self.f.create_variable(nm, (nm,), "f8", data=np.asarray(vals, dtype="f8"))
            v.attrs["units"] = units
        t = self.f.create_variable("time", ("time",), "i8")
        t.attrs.update(units="days since 1970-01-01", calendar="standard")
        chunks = (self.FLUSH, min(len(lat), 90), min(len(lon), 90))
        self.var = self.f.create_variable(
            self.name, ("time", "lat", "lon"), "f4", chunks=chunks, fillvalue=np.nan,
            compression="gzip", compression_opts=4, shuffle=True)
        self.var.attrs.update(units=entry["units"], catalog_id=entry["id"],
                              source=f"NASA {entry['short_name']} v{entry.get('version', '?')}")
        self.times = []

    def add(self, month: pd.Timestamp, da: xr.DataArray):
        self.buf.append((month, da.values))
        if len(self.buf) >= self.FLUSH:
            self.flush()

    def flush(self):
        if not self.buf:
            return
        k = len(self.buf)
        self.f.resize_dimension("time", self.n + k)
        self.var[self.n:self.n + k, :, :] = np.stack([a for _, a in self.buf]).astype("f4")
        days = [(m - pd.Timestamp("1970-01-01")).days for m, _ in self.buf]
        self.f.variables["time"][self.n:self.n + k] = np.asarray(days, dtype="i8")
        self.n += k
        self.buf = []

    def close(self):
        self.flush()
        self.f.close()
        os.replace(self.tmp, self.path)
        print(f"  wrote {self.path.name}  {self.n} months  {self.path.stat().st_size / 1e6:.0f} MB")


def pull_collection(entries: list, start: str, end: str | None, keep_raw: bool):
    import earthaccess

    first = entries[0]
    sn, group = first["short_name"], first.get("group")
    temporal = (f"{start}-01", f"{end}-28" if end else None)
    kwargs = dict(short_name=sn, temporal=temporal)
    if first.get("version"):
        kwargs["version"] = first["version"]
    results = earthaccess.search_data(**kwargs)
    if not results:
        raise SystemExit(f"No granules for {sn} {temporal}. Run check_catalog.py.")
    print(f"{sn}: {len(results)} monthly granules -> {[e['id'] for e in entries]}")

    raw = RAW_DIR / sn
    raw.mkdir(parents=True, exist_ok=True)
    writers, last, failed = {}, None, 0
    for i, g in enumerate(results, 1):
        try:
            files = earthaccess.download([g], str(raw))
            if not files:
                raise RuntimeError("no file returned")
            with open_granule(files[0], group) as ds:
                m = granule_month(ds, files[0])
                if last is not None and m <= last:
                    raise RuntimeError(f"granule out of order ({m:%Y-%m})")
                arrays = {e["id"]: extract(ds, e) for e in entries}   # extract all before writing any
        except Exception as ex:
            failed += 1
            print(f"  granule {i} skipped: {ex}")
            continue
        for e in entries:
            da = arrays[e["id"]]
            if e["id"] not in writers:
                writers[e["id"]] = IncrementalWriter(e, da["lat"].values, da["lon"].values)
            writers[e["id"]].add(m, da)
        last = m
        if not keep_raw:
            for f in files:
                try:
                    os.remove(f)
                except OSError:
                    pass
        if i % 24 == 0:
            print(f"  {i}/{len(results)}")

    if failed:
        print(f"  WARNING: {failed} granules failed; the series has gaps. Re-run with --force to retry.")
    for w in writers.values():
        w.close()
    if not keep_raw:
        shutil.rmtree(raw, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("category")
    ap.add_argument("--start", default="2000-01", help="YYYY-MM (default 2000-01)")
    ap.add_argument("--end", default=None, help="YYYY-MM (default: latest)")
    ap.add_argument("--keep-raw", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-pull even if the output exists")
    args = ap.parse_args()

    entries = [e for _, e in iter_entries(load_catalog(), args.category)]
    if not entries:
        raise SystemExit(f"No pullable entries for category {args.category!r}")
    todo = [e for e in entries if args.force or not processed_path(e).exists()]
    for e in entries:
        if e not in todo:
            print(f"skip {e['id']} (already at {processed_path(e).name}; --force to redo)")
    if not todo:
        return

    groups = defaultdict(list)
    for e in todo:
        groups[(e["short_name"], e.get("version"), e.get("group"))].append(e)
    earthdata_login()
    for group_entries in groups.values():
        pull_collection(group_entries, args.start, args.end, args.keep_raw)


if __name__ == "__main__":
    main()
