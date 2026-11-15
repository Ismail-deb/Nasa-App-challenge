"""Export small preset-region monthly series from the processed gridded files.

    python export_series.py           # export everything that is available
    python export_series.py --list    # show, for every (variable, preset), what is expected and found

For every (variable, preset region) whose gridded file exists in data/processed/, this computes
the cos(latitude)-weighted monthly regional mean with the SAME function the backend uses
(app.data.regional_mean) and writes data/series/<variable>__<region>.csv (columns: date,value)
plus data/series/index.yml. CSV values are in the stored-series units recorded as `units` in
index.yml; `display_units` / `display_conversion` say how the app shows them.

Units are never guessed: the processed file's `units` attribute (written by pull_data.py from
catalog.yml) must match the catalog, and every display conversion must be a known one
(app/display.py); otherwise the variable is refused.

Nothing is skipped silently: every skip prints its reason (file missing, variable missing, units
mismatch, or empty). Safe to re-run anywhere: for a skipped variable, previously exported series (e.g. made on
another machine) are kept. Output is deterministic: re-running on the same data gives no git diff.
"""
import argparse
import os

import xarray as xr
import yaml

import common
from app import data, display, presets

VARIABLES = [
    "M2TMNXSLV/T2M",
    "GPM_3IMERGM/precipitation",
    "M2TMNXRAD/SWGDN",
    "M2TMNXRAD/CLDTOT",
    "M2TMNXAER/TOTEXTTAU",
    "GLDAS_NOAH025_M/SoilMoi0_10cm_inst",
    "M2TMNXSLV/WIND50M",
    "GLDAS_NOAH025_M/Qs_acc",
    "GLDAS_NOAH025_M/Evap_tavg",
    "GLDAS_NOAH025_M/Snowf_tavg",
    "GLDAS_NOAH025_M/SnowDepth_inst",
    "GLDAS_NOAH025_M/SWE_inst",
]


def expected_var_name(entry: dict) -> str:
    """Variable name inside the processed file, as pull_data.IncrementalWriter names it: the
    catalog variable, or for derived entries (e.g. wind speed from U50M+V50M) the id suffix."""
    v = entry["variable"]
    return v if isinstance(v, str) else entry["id"].split("/", 1)[1]


def inspect_file(entry: dict) -> tuple[str | None, list]:
    """(problem or None, variable names found).
    problem: 'file missing' / 'variable missing' / 'units mismatch'."""
    path = common.processed_path(entry)
    if not path.exists():
        return f"file missing: {path.name} not in {path.parent}", []
    name = expected_var_name(entry)
    with xr.open_dataset(path, engine=common.NC_ENGINE) as ds:
        found = list(ds.data_vars)
        file_units = ds[name].attrs.get("units") if name in found else None
    if name not in found:
        return (f"variable missing: {path.name} has {found}, expected '{name}'"), found
    if file_units is not None and str(file_units) != str(entry["units"]):
        return (f"units mismatch: {path.name} says units={file_units!r} but catalog.yml says "
                f"{entry['units']!r}; fix the catalog (do not guess a conversion)"), found
    return None, found


def check_conversions(variables) -> None:
    """Refuse to start if any variable has an unknown display conversion (before writing anything)."""
    bad = []
    for var_id in variables:
        try:
            catalog_fields(data.find_entry(var_id))
        except ValueError as ex:
            bad.append(str(ex))
    if bad:
        raise SystemExit("export refused, unknown unit combination:\n  " + "\n  ".join(bad))


def write_csv(ser, path):
    """Atomic write: temp file then rename, so a reader never sees a half-written CSV."""
    tmp = path.with_name(f"{path.name}.part-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("date,value\n")
        for d, v in ser.items():
            f.write(f"{d:%Y-%m},{'' if v != v else repr(float(v))}\n")   # full precision; NaN -> empty
    os.replace(tmp, path)


def catalog_fields(entry) -> dict:
    """Index fields that come from catalog.yml (refreshed on every run, even for kept series)."""
    clean = lambda s: " ".join(s.split()) if s else None
    return {"units": data.display_units(entry),
            "display_units": display.unit_label(entry),
            "display_conversion": display.conversion_note(entry),
            "source": f"NASA {entry['short_name']} v{entry.get('version', '?')}",
            "description": clean(entry.get("description")), "note": clean(entry.get("note"))}


def index_record(entry, region, preset, ser):
    valid = ser.dropna()
    f = catalog_fields(entry)
    return {
        "variable": entry["id"],
        "file": presets.series_path(entry, region).name,
        "region": region,
        "region_name": preset["name"],
        "bbox": [float(x) for x in preset["bbox"]],
        "units": f["units"],                       # units of the values in the CSV
        "display_units": f["display_units"],       # what the app shows
        "display_conversion": f["display_conversion"],
        "source": f["source"],
        "period_start": f"{ser.index[0]:%Y-%m}",
        "period_end": f"{ser.index[-1]:%Y-%m}",
        "n_months": int(len(ser)),
        "n_missing": int(len(ser) - len(valid)),
        "origin": "pipeline",
        "description": f["description"],
        "note": f["note"],
    }


def _keep_old(var_id, entry, region, old, new, report):
    key = (var_id, region)
    if key in old and presets.series_path(entry, region).exists():
        new[key] = {**old[key], **catalog_fields(entry)}
        report["kept"].append(old[key]["file"])
        print(f"      keeping {old[key]['file']} exported earlier")


def export(variables=VARIABLES) -> dict:
    """Run the export. Returns {"written": [...], "skipped": [(var, region|None, reason)], "kept": [...]}."""
    check_conversions(variables)
    regions = presets.load_presets()
    common.SERIES_DIR.mkdir(parents=True, exist_ok=True)
    old = {(r["variable"], r["region"]): r for r in presets.read_index()}
    new, report = {}, {"written": [], "skipped": [], "kept": []}

    for var_id in variables:
        entry = data.find_entry(var_id)
        problem, _ = inspect_file(entry)
        if problem:
            print(f"skip {var_id}: {problem}")
            report["skipped"].append((var_id, None, problem))
            for region in regions:                       # keep series exported elsewhere
                _keep_old(var_id, entry, region, old, new, report)
            continue
        for region, p in regions.items():
            ser = data.regional_mean(entry, tuple(p["bbox"]), None, None)
            if ser.dropna().empty:
                reason = f"empty: every month is missing for region {region}"
                print(f"skip {var_id} / {region}: {reason}")
                report["skipped"].append((var_id, region, reason))
                _keep_old(var_id, entry, region, old, new, report)
                continue
            path = presets.series_path(entry, region)
            write_csv(ser, path)
            new[(var_id, region)] = index_record(entry, region, p, ser)
            report["written"].append(path.name)
            print(f"wrote {path.name}: {len(ser)} months, {ser.index[0]:%Y-%m} to {ser.index[-1]:%Y-%m}")

    records = [new[k] for k in sorted(new)]
    tmp = common.SERIES_DIR / f"index.yml.part-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Generated by export_series.py - do not edit by hand.\n")
        yaml.safe_dump({"series": records}, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp, common.SERIES_DIR / "index.yml")
    print(f"index.yml: {len(records)} series ({len(report['written'])} written, "
          f"{len(report['kept'])} kept from earlier runs, {len(report['skipped'])} skips)")
    return report


def list_status(variables=VARIABLES) -> list:
    """Print and return one row per (variable, preset): expected file, exists, variable found,
    and whether a series CSV is already exported. Reads files only; writes nothing."""
    rows, regions = [], presets.load_presets()
    print(f"processed dir: {common.PROCESSED_DIR}\nseries dir:    {common.SERIES_DIR}\n")
    for var_id in variables:
        entry = data.find_entry(var_id)
        path = common.processed_path(entry)
        problem, found = inspect_file(entry)
        print(f"{var_id}  (expects variable '{expected_var_name(entry)}' in {path.name})")
        print(f"   gridded file exists: {path.exists()}   variables found: {found or '-'}"
              f"{'   -> WOULD SKIP: ' + problem if problem else ''}")
        for region in regions:
            csv = presets.series_path(entry, region)
            row = {"variable": var_id, "region": region, "expected_file": str(path),
                   "exists": path.exists(), "variables_found": found, "problem": problem,
                   "series_csv": csv.name, "series_exported": csv.exists()}
            rows.append(row)
            print(f"   {region:18s} series {csv.name:42s} exported: {csv.exists()}")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="show what is expected and found; write nothing")
    args = ap.parse_args()
    list_status() if args.list else export()
