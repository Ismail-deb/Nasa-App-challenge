"""Download monthly granules for one category and write compact processed NetCDF files.

    python pull_data.py weather_climate [--start 2000-01] [--end 2024-12] [--keep-raw]

Each granule is downloaded, the one needed variable is extracted, and the raw file is
deleted (unless --keep-raw), so disk use stays small. Output: data/processed/<short>_<var>.nc
(float32, zlib-compressed, dims time/lat/lon). The running app reads only these files.
"""
import argparse
import os
import shutil

import xarray as xr

from common import NC_ENGINE, PROCESSED_DIR, RAW_DIR, earthdata_login, iter_entries, load_catalog, processed_path


def pull_entry(entry: dict, start: str, end: str | None, keep_raw: bool):
    import earthaccess

    temporal = (f"{start}-01", f"{end}-28" if end else None)
    kwargs = dict(short_name=entry["short_name"], temporal=temporal)
    if entry.get("version"):
        kwargs["version"] = entry["version"]
    results = earthaccess.search_data(**kwargs)
    if not results:
        raise SystemExit(f"No granules for {entry['id']} {temporal}. Run check_catalog.py.")
    print(f"{entry['id']}: {len(results)} monthly granules")

    raw = RAW_DIR / entry["short_name"]
    raw.mkdir(parents=True, exist_ok=True)
    pieces = []
    for i, g in enumerate(results, 1):
        files = earthaccess.download([g], str(raw))
        if not files:
            print("  download failed for one granule, skipping")
            continue
        with xr.open_dataset(files[0], engine=NC_ENGINE) as ds:
            pieces.append(ds[entry["variable"]].load())     # (time=1, lat, lon)
        if not keep_raw:
            for f in files:
                try:
                    os.remove(f)
                except OSError:
                    pass
        if i % 24 == 0:
            print(f"  {i}/{len(results)}")

    da = xr.concat(pieces, dim="time").sortby("time").astype("float32")
    da.name = entry["variable"]
    da.attrs = {"units": entry["units"], "source": f"NASA GES DISC {entry['short_name']}"}
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = processed_path(entry)
    da.to_dataset().to_netcdf(out, engine=NC_ENGINE, encoding={entry["variable"]: {"zlib": True, "complevel": 4}})
    print(f"  wrote {out} {dict(da.sizes)} {out.stat().st_size / 1e6:.0f} MB")
    if not keep_raw:
        shutil.rmtree(raw, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("category")
    ap.add_argument("--start", default="2000-01", help="YYYY-MM (default 2000-01)")
    ap.add_argument("--end", default=None, help="YYYY-MM (default: latest)")
    ap.add_argument("--keep-raw", action="store_true")
    args = ap.parse_args()

    entries = list(iter_entries(load_catalog(), args.category))
    if not entries:
        raise SystemExit(f"No entries for category {args.category!r}")
    earthdata_login()
    for _, e in entries:
        pull_entry(e, args.start, args.end, args.keep_raw)


if __name__ == "__main__":
    main()
