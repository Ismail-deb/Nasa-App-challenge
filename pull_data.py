"""Download monthly granules for one category and write processed NetCDF files (native resolution).

    python pull_data.py weather_climate [--start 2000-01] [--end 2024-12] [--force] [--cleanup]
    python pull_data.py hydrology --coarsen 5      # IMERG block factor (default from catalog)
    python pull_data.py hydrology --native         # IMERG at native 0.1 degrees (large file)

- Entries that share a NASA collection (e.g. all MERRA-2 SLV variables) are served by ONE
  download of each granule; every needed variable is extracted from it.
- Raw granules are cached in data/raw/<short_name>/ (git-ignored) and reused by later runs, e.g.
  weather_climate and atmosphere_solar share the MERRA-2 SLV granules. A cached file is used only
  if it matches NASA's metadata size and every needed variable reads cleanly; otherwise it is
  deleted and re-downloaded. Downloads land in a private temp dir and are renamed into the cache
  atomically, so an interrupted run never leaves a half-written file under a real name.
  --cleanup deletes the cache for this category's collections afterwards.
- Exit code: 0 ok, 3 finished with gaps (some granules failed), 1 error.
- MERRA-2 and GLDAS keep their native grids. Entries with `coarsen: N` in catalog.yml (IMERG,
  0.1 degrees) are block-averaged NxN (NaN-aware) BEFORE writing; default N=5 gives 0.5 degrees.
  Missing values -> NaN.
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
IMERG_NATIVE_MB_PER_MONTH = 12.0   # measured: 12-month native-resolution test pull = 144 MB
RELEASE_LIMIT_MB = 2 * 1024        # GitHub Release: each file must be under 2 GiB


def block_mean(da: xr.DataArray, factor: int) -> xr.DataArray:
    """NaN-aware factor x factor block mean of a (lat, lon) array.

    Each output cell is the mean of the valid (non-NaN) native cells in its block; a block
    that is entirely NaN stays NaN. Coordinates become block centres (mean of native centres).
    Rows/columns that do not fill a whole block are trimmed (none for IMERG with factor 5).
    """
    if factor <= 1:
        return da
    ny, nx = da.sizes["lat"] // factor * factor, da.sizes["lon"] // factor * factor
    a = da.values[:ny, :nx].reshape(ny // factor, factor, nx // factor, factor)
    valid = ~np.isnan(a)
    total = np.where(valid, a, 0).sum(axis=(1, 3), dtype="f8")
    count = valid.sum(axis=(1, 3))
    out = np.full(total.shape, np.nan, dtype="f4")
    np.divide(total, count, out=out, where=count > 0, casting="unsafe")
    lat = da["lat"].values[:ny].reshape(-1, factor).mean(axis=1)
    lon = da["lon"].values[:nx].reshape(-1, factor).mean(axis=1)
    return xr.DataArray(out, coords={"lat": lat, "lon": lon}, dims=("lat", "lon"), name=da.name)


def projected_size_report(n_months: int, factor: int) -> str:
    """Projected IMERG output size (from the measured native size) vs the Release limit."""
    native = n_months * IMERG_NATIVE_MB_PER_MONTH
    coarse = native / factor ** 2
    fits = lambda mb: "fits" if mb < RELEASE_LIMIT_MB else "TOO BIG"
    lines = [f"  projected IMERG size for {n_months} months (limit {RELEASE_LIMIT_MB} MB per Release file):",
             f"    native 0.1 deg : ~{native:,.0f} MB  [{fits(native)}]"]
    if factor > 1:
        lines.append(f"    {factor}x{factor} block mean ({0.1 * factor:g} deg): ~{coarse:,.0f} MB  [{fits(coarse)}]"
                     "  (estimate; compression varies)")
    return "\n".join(lines)


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
        import uuid
        # unique per process/run, so two runs can never write the same temp file
        self.tmp = self.path.with_name(f"{self.path.name}.part-{os.getpid()}-{uuid.uuid4().hex[:8]}")
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
        f = entry.get("coarsen", 1) or 1
        if f > 1:
            self.var.attrs["resampling"] = f"NaN-aware {f}x{f} block mean of the native grid"
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

    def abort(self):
        """Interrupted run: close and delete the temp file; the real output is never touched."""
        try:
            self.f.close()
        except Exception:
            pass
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def close(self):
        self.flush()
        self.f.close()
        try:
            os.replace(self.tmp, self.path)  # atomic: readers see the old file or the new one
        except PermissionError:
            raise SystemExit(
                f"Cannot replace {self.path.name}: it is open in another program (is the app "
                f"running?). The new data is complete in {self.tmp.name}; stop the app and re-run.")
        print(f"  wrote {self.path.name}  {self.n} months  {self.path.stat().st_size / 1e6:.0f} MB")


# ---------------------------------------------------------------- raw granule cache

STALE_SECONDS = 12 * 3600   # temp files/dirs older than this are leftovers of a killed run


def granule_filename(g) -> str | None:
    """File name the granule will have on disk (basename of its data link), if known."""
    try:
        links = g.data_links()
    except Exception:
        return None
    return os.path.basename(links[0].split("?")[0]) if links else None


def expected_bytes(g) -> float | None:
    """Granule size from NASA metadata (earthaccess reports MB), or None if unknown."""
    try:
        mb = float(g.size() if callable(g.size) else g.size)
    except Exception:
        return None
    return mb * 1024 * 1024 if mb > 0 else None


def size_ok(path, g) -> bool:
    """False if the file is clearly shorter than NASA says it is (a partial download)."""
    exp = expected_bytes(g)
    return exp is None or os.path.getsize(path) >= 0.98 * exp


def read_granule(path, group, entries, g):
    """Fully read one granule: (month, {entry id: (lat, lon) array}). Raises if partial/corrupt."""
    if not size_ok(path, g):
        raise OSError(f"{os.path.basename(path)} is smaller than its NASA metadata size (partial)")
    with open_granule(str(path), group) as ds:
        month = granule_month(ds, str(path))
        # extract all before writing any; coarsen only entries that ask for it
        arrays = {e["id"]: block_mean(extract(ds, e), e.get("coarsen", 1) or 1) for e in entries}
    return month, arrays


def download_to_cache(earthaccess, g, cache_dir):
    """Download into a private temp dir, then atomically rename into the cache.

    The temp dir name is unique per process and call (pid + random), so concurrent runs never
    write to the same file. os.replace is atomic: the cache only ever holds complete downloads
    (a granule is either absent, or a whole file that may still fail validation).
    """
    import uuid

    tmp = cache_dir / f".dl-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True)
    try:
        files = earthaccess.download([g], str(tmp))
        if not files:
            raise RuntimeError("download returned no file")
        src = files[0]
        dest = cache_dir / os.path.basename(str(src))
        try:
            os.replace(src, dest)
        except PermissionError:
            # Windows: another process has an identical copy open. Theirs is complete
            # (it got there by atomic rename), so keep it and drop ours.
            if not dest.exists():
                raise
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_granule(earthaccess, g, cache_dir, group, entries):
    """Cache hit if the cached file validates; otherwise (re)download and validate.
    Returns (month, arrays, was_downloaded)."""
    name = granule_filename(g)
    if name:
        cached = cache_dir / name
        if cached.exists():
            try:
                return (*read_granule(cached, group, entries, g), False)
            except Exception as ex:
                print(f"  cached {name} unusable ({ex}); re-downloading")
                try:
                    cached.unlink()
                except OSError:
                    pass
    path = download_to_cache(earthaccess, g, cache_dir)
    try:
        return (*read_granule(path, group, entries, g), True)
    except Exception:
        try:
            path.unlink()          # never leave a bad file in the cache
        except OSError:
            pass
        raise


def remove_stale_temp(folder):
    """Delete temp dirs/files left by killed runs (older than STALE_SECONDS). A live run's
    temp files are younger, so they are never touched."""
    import time

    if not folder.exists():
        return
    now = time.time()
    for p in list(folder.glob(".dl-*")) + list(folder.glob("*.part-*")):
        try:
            if now - p.stat().st_mtime > STALE_SECONDS:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- pulling

def pull_collection(entries: list, start: str, end: str | None) -> int:
    """Pull one collection for the given entries. Returns the number of failed granules."""
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
    if "coarsen" in first:
        print(projected_size_report(len(results), first["coarsen"] or 1))

    cache = RAW_DIR / sn
    cache.mkdir(parents=True, exist_ok=True)
    remove_stale_temp(cache)
    remove_stale_temp(PROCESSED_DIR)
    writers, last, failed, downloaded = {}, None, 0, 0
    try:
        for i, g in enumerate(results, 1):
            try:
                m, arrays, fresh = load_granule(earthaccess, g, cache, group, entries)
                if last is not None and m <= last:
                    raise RuntimeError(f"granule out of order ({m:%Y-%m})")
            except Exception as ex:
                failed += 1
                print(f"  granule {i} skipped: {ex}")
                continue
            downloaded += fresh
            for e in entries:
                da = arrays[e["id"]]
                if e["id"] not in writers:
                    writers[e["id"]] = IncrementalWriter(e, da["lat"].values, da["lon"].values)
                writers[e["id"]].add(m, da)
            last = m
            if i % 24 == 0:
                print(f"  {i}/{len(results)}  ({downloaded} downloaded, {i - downloaded - failed} from cache)")
    except BaseException:
        for w in writers.values():   # interrupted: discard partial outputs, keep the cache
            w.abort()
        raise

    print(f"  granules: {downloaded} downloaded, {len(results) - downloaded - failed} from cache, {failed} failed")
    if failed:
        print(f"  WARNING: {failed} granules failed; the series has gaps. Re-run with --force to retry.")
    for w in writers.values():
        w.close()
    return failed


def cleanup_cache(entries):
    for sn in sorted({e["short_name"] for e in entries}):
        d = RAW_DIR / sn
        if d.exists():
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6
            shutil.rmtree(d, ignore_errors=True)
            print(f"cleanup: removed raw cache {d} ({size:,.0f} MB)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("category")
    ap.add_argument("--start", default="2000-01", help="YYYY-MM (default 2000-01)")
    ap.add_argument("--end", default=None, help="YYYY-MM (default: latest)")
    ap.add_argument("--force", action="store_true", help="re-process even if the output exists")
    ap.add_argument("--cleanup", action="store_true",
                    help="afterwards, delete the raw cache of the collections this category uses")
    ap.add_argument("--coarsen", type=int, default=None,
                    help="block factor for entries that have `coarsen` in catalog.yml (IMERG)")
    ap.add_argument("--native", action="store_true", help="disable coarsening (factor 1)")
    args = ap.parse_args(argv)

    entries = [e for _, e in iter_entries(load_catalog(), args.category)]
    if not entries:
        raise SystemExit(f"No pullable entries for category {args.category!r}")
    for e in entries:                      # only entries that opt in are ever coarsened
        if "coarsen" in e:
            e["coarsen"] = 1 if args.native else (args.coarsen or e["coarsen"])
    todo = [e for e in entries if args.force or not processed_path(e).exists()]
    for e in entries:
        if e not in todo:
            print(f"skip {e['id']} (already at {processed_path(e).name}; --force to redo)")

    failed = 0
    if todo:
        groups = defaultdict(list)
        for e in todo:
            groups[(e["short_name"], e.get("version"), e.get("group"))].append(e)
        earthdata_login()
        for group_entries in groups.values():
            failed += pull_collection(group_entries, args.start, args.end)

    if args.cleanup:
        if failed:
            print("cleanup skipped: some granules failed; keeping the cache so a re-run is fast")
        else:
            cleanup_cache(entries)
    return 3 if failed else 0       # 3 = finished, but with gaps


if __name__ == "__main__":
    raise SystemExit(main())
