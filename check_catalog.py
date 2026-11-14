"""Check catalog.yml against NASA's catalog (CMR) and the real files.

For each entry: does the collection resolve? how many granules? what variables/units
do the files really contain? Use the output to correct catalog.yml.

    python check_catalog.py                       # everything
    python check_catalog.py --only M2TMNXSLV      # one short_name
"""
import argparse

from common import NC_ENGINE, RAW_DIR, earthdata_login, iter_entries, load_catalog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="restrict to one short_name")
    ap.add_argument("--category")
    args = ap.parse_args()

    import earthaccess
    import xarray as xr

    earthdata_login()
    catalog = load_catalog()
    probed = {}  # (short_name, version) -> variable listing (one probe per collection)
    found = {}   # short_name -> (versions, chosen version, results) or None

    for cat, e in iter_entries(catalog, args.category, include_planned=True):
        if args.only and e.get("short_name") != args.only:
            continue
        print(f"\n=== [{cat}] {e['id']}  ({e['name']})")
        if "short_name" not in e:
            print("  - planned / TODO (no NASA collection assigned yet)")
            continue
        sn = e["short_name"]
        if sn not in found:
            colls = earthaccess.search_datasets(short_name=sn)
            if not colls:
                found[sn] = None
            else:
                versions = sorted({c.summary.get("version", "?") for c in colls})
                ver = e.get("version") if e.get("version") in versions else versions[-1]
                found[sn] = (versions, ver, earthaccess.search_data(short_name=sn, version=ver))
        if found[sn] is None:
            print("  X collection NOT FOUND for short_name")
            continue
        versions, ver, results = found[sn]
        ok = "OK" if e.get("version") in (None, ver) else f"VERSION DIFFERS (catalog {e.get('version')!r})"
        print(f"  collection found; versions on CMR: {versions}; using {ver} [{ok}]")
        print(f"  {len(results)} granules")
        if not results:
            continue
        for label, g in (("first", results[0]), ("last", results[-1])):
            print(f"    {label}:", g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"])

        key = (sn, ver)
        if key not in probed:
            probe_dir = RAW_DIR / "_probe" / sn
            probe_dir.mkdir(parents=True, exist_ok=True)
            files = earthaccess.download(results[:1], str(probe_dir))
            with xr.open_dataset(files[0], engine=NC_ENGINE) as ds:
                if not ds.data_vars:   # e.g. IMERG (HDF5) keeps its data in a 'Grid' group
                    ds = xr.open_dataset(files[0], engine=NC_ENGINE, group="Grid")
                probed[key] = {
                    v: (ds[v].attrs.get("units"), ds[v].attrs.get("long_name"), ds[v].dims)
                    for v in ds.data_vars
                }
        listing = probed[key]
        for var in (e["variable"] if isinstance(e["variable"], list) else [e["variable"]]):
            if var in listing:
                u, ln, dims = listing[var]
                flag = "OK" if u == e["units"] else f"UNITS DIFFER (catalog says {e['units']!r})"
                print(f"  variable {var} found: units={u!r} [{flag}] long_name={ln!r} dims={dims}")
            else:
                print(f"  X variable {var!r} NOT in file. Real variables:")
                for v, (u, ln, _) in listing.items():
                    print(f"      {v:24s} {u!s:12s} {ln}")


if __name__ == "__main__":
    main()
