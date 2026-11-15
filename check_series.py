"""Check the committed preset series in data/series/ for calendar problems.

    python check_series.py            # report; exit code 1 if any problem is found

For every CSV it reports:
  * ABSENT months: calendar months between the first and last date that have no row at all
    (index.yml's n_missing only counts rows with an empty value, so it shows 0 for these);
  * EMPTY months: rows whose value is empty (NaN), for comparison with index.yml n_missing;
  * DUPLICATE dates and dates out of order or not in YYYY-MM form;
  * series that END EARLY: last month before the latest last month of other series from the same
    source dataset (e.g. one MERRA-2 region ending 2026-08 while the others reach 2026-09);
  * index.yml mismatches: period_start/period_end/n_months/n_missing disagreeing with the file.
Reads only; never modifies anything.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml

SERIES_DIR = Path(__file__).parent / "data" / "series"


def check_file(path: Path) -> dict:
    df = pd.read_csv(path, dtype={"date": str, "value": str}, keep_default_na=False)
    r = {"file": path.name, "problems": []}
    dates = pd.to_datetime(df["date"], format="%Y-%m", errors="coerce")
    bad = df["date"][dates.isna()].tolist()
    if bad:
        r["problems"].append(f"unparseable dates: {bad[:5]}")
    dates = dates.dropna()
    if dates.empty:
        r["problems"].append("no dates")
        return r
    per = dates.dt.to_period("M")
    dup = per[per.duplicated()].astype(str).unique().tolist()
    if dup:
        r["problems"].append(f"duplicate dates: {dup}")
    if not per.is_monotonic_increasing:
        r["problems"].append("dates not in increasing order")
    full = pd.period_range(per.min(), per.max(), freq="M")
    absent = sorted(set(full) - set(per))
    if absent:
        r["problems"].append(f"{len(absent)} absent month(s): {[str(a) for a in absent[:12]]}")
    empty = df["date"][df["value"].str.strip() == ""].tolist()
    r.update(start=str(per.min()), end=str(per.max()), n_rows=len(df), n_absent=len(absent),
             n_empty=len(empty), empty=empty)
    return r


def main(series_dir: Path = SERIES_DIR) -> int:
    files = sorted(series_dir.glob("*.csv"))
    index = {}
    if (series_dir / "index.yml").exists():
        doc = yaml.safe_load((series_dir / "index.yml").read_text(encoding="utf-8")) or {}
        index = {r["file"]: r for r in doc.get("series", [])}
    results = [check_file(f) for f in files]

    # series ending earlier than others from the same source dataset (short_name)
    by_source = defaultdict(list)
    for r in results:
        src = index.get(r["file"], {}).get("source") or r["file"].split("__")[0]
        by_source[src].append(r)
    for src, rs in by_source.items():
        latest = max(r["end"] for r in rs if "end" in r)
        for r in rs:
            if r.get("end") and r["end"] < latest:
                r["problems"].append(f"ends early: {r['end']} while other {src} series reach {latest}")

    for r in results:
        rec = index.get(r["file"])
        if rec is None:
            r["problems"].append("not listed in index.yml")
            continue
        for k, v in (("period_start", r.get("start")), ("period_end", r.get("end")),
                     ("n_months", r.get("n_rows")), ("n_missing", r.get("n_empty"))):
            if str(rec.get(k)) != str(v):
                r["problems"].append(f"index.yml {k}={rec.get(k)} but file has {v}")
    for name in sorted(set(index) - {f.name for f in files}):
        results.append({"file": name, "problems": ["listed in index.yml but file missing"]})

    n_bad = 0
    for r in results:
        status = "OK " if not r["problems"] else "BAD"
        n_bad += bool(r["problems"])
        span = f"{r.get('start')}..{r.get('end')} rows={r.get('n_rows')} absent={r.get('n_absent')} empty={r.get('n_empty')}"
        print(f"{status} {r['file']:42s} {span}")
        for p in r["problems"]:
            print(f"      - {p}")
    print(f"\n{len(results)} series checked, {n_bad} with problems.")
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else SERIES_DIR))
