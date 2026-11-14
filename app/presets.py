"""Preset demo regions (presets.yml) and their precomputed series in data/series/."""
from pathlib import Path

import pandas as pd
import yaml

import common

BBOX_TOLERANCE = 0.05   # degrees: a request bbox within this of a preset (every edge) uses the preset
LENSES = ("solar", "wind", "hydro", "farming")


def load_presets() -> dict:
    with open(common.ROOT / "presets.yml", encoding="utf-8") as f:
        presets = yaml.safe_load(f)["presets"]
    for pid, p in presets.items():
        if len(p["bbox"]) != 4 or p["lens"] not in LENSES:
            raise ValueError(f"presets.yml: bad entry {pid!r}")
    return presets


def match_preset(bbox, presets: dict | None = None, tol: float = BBOX_TOLERANCE) -> str | None:
    """Id of the preset whose bbox equals `bbox` (west, south, east, north) within tol, else None."""
    presets = load_presets() if presets is None else presets
    for pid, p in presets.items():
        if all(abs(float(a) - float(b)) <= tol for a, b in zip(bbox, p["bbox"])):
            return pid
    return None


def var_key(entry: dict) -> str:
    """Short variable name used in series file names, e.g. T2M, WIND50M, precipitation."""
    return entry["id"].split("/", 1)[1]


def series_path(entry: dict, region: str) -> Path:
    return common.SERIES_DIR / f"{var_key(entry)}__{region}.csv"


def load_series(entry: dict, region: str) -> pd.Series | None:
    """Precomputed monthly series (display units), or None if it does not exist."""
    p = series_path(entry, region)
    if not p.exists():
        return None
    df = pd.read_csv(p, dtype={"date": str, "value": float})
    idx = pd.to_datetime(df["date"], format="%Y-%m")
    return pd.Series(df["value"].to_numpy(), index=pd.DatetimeIndex(idx), name=var_key(entry))


def read_index() -> list:
    p = common.SERIES_DIR / "index.yml"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("series", [])
