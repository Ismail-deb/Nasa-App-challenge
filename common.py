"""Shared helpers: catalog loading, Earthdata login, paths."""
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
# h5netcdf reads/writes the same NetCDF4 files as netCDF4 but avoids its native DLL
# (blocked by Windows Application Control on some machines).
NC_ENGINE = "h5netcdf"
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"


def load_catalog() -> dict:
    with open(ROOT / "catalog.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def iter_entries(catalog: dict, category: str | None = None):
    for cat, body in catalog["categories"].items():
        if category and cat != category:
            continue
        for entry in body.get("variables", []):
            yield cat, entry


def processed_path(entry: dict) -> Path:
    return PROCESSED_DIR / f"{entry['short_name']}_{entry['variable']}.nc"


def earthdata_login():
    """Log in with env vars (EARTHDATA_USERNAME/PASSWORD) or ~/.netrc. Never prompts, never stores."""
    import earthaccess

    for strategy in ("environment", "netrc"):
        try:
            auth = earthaccess.login(strategy=strategy)
            if auth.authenticated:
                return auth
        except Exception:
            continue
    raise SystemExit(
        "No Earthdata credentials found. Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD, "
        "or create ~/.netrc (_netrc on Windows). See README."
    )
