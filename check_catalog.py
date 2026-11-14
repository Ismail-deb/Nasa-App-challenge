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
    probed = {}  # short_name -> variable listing (one probe per collection)

    for cat, e in iter_entries(catalog, args.category):
        if args.only and e["short_name"] != args.only:
            continue
        print(f"\n=== [{cat}] {e['id']}  ({e['name']})")
        colls = earthaccess.search_datasets(short_name=e["short_name"])
        if not colls:
            print("  X collection NOT FOUND for short_name")
            continue
        versions = sorted({c.summary.get("version", "?") for c in colls})
        print(f"  OK collection found; versions on CMR: {versions}; catalog says {e.get('version')}")
        ver = e.get("version") if e.get("version") in versions else versions[-1]
        results = earthaccess.search_data(short_name=e["short_name"], version=ver)
        print(f"  OK {len(results)} granules (version {ver})")
        if not results:
            continue
        for label, g in (("first", results[0]), ("last", results[-1])):
            print(f"    {label}:", g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"])

        if e["short_name"] not in probed:
            probe_dir = RAW_DIR / "_probe" / e["short_name"]
            probe_dir.mkdir(parents=True, exist_ok=True)
            files = earthaccess.download(results[:1], str(probe_dir))
            with xr.open_dataset(files[0], engine=NC_ENGINE) as ds:
                probed[e["short_name"]] = {
                    v: (ds[v].attrs.get("units"), ds[v].attrs.get("long_name"), ds[v].dims)
                    for v in ds.data_vars
                }
        listing = probed[e["short_name"]]
        if e["variable"] in listing:
            u, ln, dims = listing[e["variable"]]
            flag = "OK" if u == e["units"] else f"UNITS MISMATCH (catalog says {e['units']})"
            print(f"  OK variable {e['variable']} found: units={u!r} [{flag}] long_name={ln!r} dims={dims}")
        else:
            print(f"  X variable {e['variable']!r} NOT in file. Real variables:")
            for v, (u, ln, _) in listing.items():
                print(f"      {v:16s} {u!s:12s} {ln}")


if __name__ == "__main__":
    main()
