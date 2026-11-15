"""Per-grid-cell trend maps for the contiguous US, precomputed from data/processed/.

    python make_trend_maps.py                      # first pass: T2M, precipitation, SWGDN
    python make_trend_maps.py --second             # second pass: TOTEXTTAU, soil moisture, evaporation, wind
    python make_trend_maps.py T2M SWGDN            # just these (series keys as in data/series)
    python make_trend_maps.py --outline-only       # just data/maps/us_outline.geojson + index.yml

Needs the full gridded files in data/processed/ (this desktop only) and the extra packages in
requirements-maps.txt (pyogrio, shapely, matplotlib). Writes, per variable, into data/maps/:
  <var>.png         RGBA overlay, one pixel per native grid cell (north up), no smoothing
  <var>.json        metadata: bounds, grid, units, scale, period, method, FDR summary, source
  <var>_cells.json  per-cell slope, raw p and FDR flag (flat, row-major, north to south)
and data/maps/index.yml, data/maps/us_outline.geojson. Previews (legend + plain background) go
to logs/maps_preview/ and the run log to logs/make_trend_maps.log (neither is committed).

METHOD (per grid cell, identical to the app's /trend default for a single series):
  1. monthly series; months that are missing in every cell are dropped;
  2. seasonal cycle removed (each calendar month's mean subtracted), as stats.remove_seasonal_cycle;
  3. Sen's slope against time in decimal years (mid-month), x10 = per decade, as stats._sen;
  4. Mann-Kendall two-sided p-value with the Hamed & Rao (1998) variance correction using the
     significant autocorrelations of lags 1..4 of the ranks of the Sen-detrended series, exactly
     as pymannkendall.hamed_rao_modification_test(lag=4) which stats.mann_kendall calls. This is
     a closed-form computation, vectorised here over cells (verified against stats.analyze);
  5. Benjamini-Hochberg FDR at q = 10% over all unmasked cells with a p-value. "Significant" on
     the map = passed FDR. The raw p and the FDR decision are both stored.
Cells with a gap in an otherwise complete record fall back to stats.analyze one by one (exact).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.special import ndtr
from scipy.stats import norm, rankdata

import common
import stats
from app import data, display, presets

MAPS_DIR = common.ROOT / "data" / "maps"
LOG_DIR = common.ROOT / "logs"
PREVIEW_DIR = LOG_DIR / "maps_preview"

US_BBOX = (-125.0, 24.0, -66.0, 50.0)           # west, south, east, north
FDR_Q = 0.10
ALPHA = stats.ALPHA                             # per-cell test level used inside Hamed-Rao (lag screening)
HR_LAGS = stats.HR_LAGS
CLIP_PERCENTILE = 98
ALPHA_SIG, ALPHA_NONSIG = 255, round(0.35 * 255)  # opacity: significant / not significant
CMAP = "RdBu_r"                                 # ColorBrewer RdBu reversed: red = increase, blue = decrease

FIRST_PASS = ["M2TMNXSLV/T2M", "GPM_3IMERGM/precipitation", "M2TMNXRAD/SWGDN"]
SECOND_PASS = ["M2TMNXAER/TOTEXTTAU", "GLDAS_NOAH025_M/SoilMoi0_10cm_inst",
               "GLDAS_NOAH025_M/Evap_tavg", "M2TMNXSLV/WIND50M"]
RELATIVE = {"M2TMNXSLV/WIND50M"}                # mapped as % of the cell's mean per decade
_GLDAS_CAVEAT = ("The map shows straight-edged rectangular blocks and north-south stripes that follow "
                 "grid lines, not geography. These are most likely artefacts of changes in the GLDAS-2.1 "
                 "model's input (forcing) data, not real trends; treat individual patterns with caution.")
CAVEATS = {"SoilMoi0_10cm_inst": _GLDAS_CAVEAT, "Evap_tavg": _GLDAS_CAVEAT}

BOUNDARY_SOURCE = {
    "name": "Natural Earth 1:110m Admin 0 - Countries (naturalearth_lowres)",
    "licence": "Public domain (Natural Earth terms of use, naturalearthdata.com/about/terms-of-use)",
    "obtained_from": "pip package pyogrio, file pyogrio/tests/fixtures/naturalearth_lowres/ (offline)",
    "note": "Contiguous US only (Alaska and Hawaii excluded). No offline pip-installable source of "
            "US state polygons was found, so state boundaries are not included.",
}

log = logging.getLogger("make_trend_maps")


# ---------------------------------------------------------------- statistics (vectorised)

def deseasonalize(y: np.ndarray, months: np.ndarray) -> np.ndarray:
    """Subtract each calendar month's mean, per cell. y: (cells, n) without NaN."""
    out = y.copy()
    for m in np.unique(months):
        sel = months == m
        out[:, sel] -= y[:, sel].mean(axis=1, keepdims=True)
    return out


def _tie_term(sorted_row: np.ndarray) -> float:
    _, tp = np.unique(sorted_row, return_counts=True)
    tp = tp.astype(float)
    return float(np.sum(tp * (tp - 1) * (2 * tp + 5)))


def trend_cells(y: np.ndarray, t: np.ndarray, alpha: float = ALPHA, lags: int = HR_LAGS,
                chunk: int = 128) -> dict:
    """Sen's slope (per unit of t) and Mann-Kendall p-values for every row of y (cells, n).

    Rows must be free of NaN. Returns arrays: slope, p (Hamed-Rao corrected), p_plain,
    inflation (= n / n_effective, the app's variance_inflation), sni_lags (number of lags used).
    """
    y = np.asarray(y, dtype=float)
    ncell, n = y.shape
    i, j = np.triu_indices(n, k=1)
    dt = (t[j] - t[i]).astype(float)
    di = (j - i).astype(float)
    var0 = n * (n - 1) * (2 * n + 5) / 18.0
    lag = min(lags, n - 2) + 1                   # pymannkendall: lag + 1, loop range(1, lag)
    bound = norm.ppf(1 - alpha / 2) / np.sqrt(n)

    out = {k: np.empty(ncell) for k in ("slope", "p", "p_plain", "inflation", "s", "var_s")}
    out["sni_lags"] = np.zeros(ncell, dtype=int)
    for a in range(0, ncell, chunk):
        b = min(a + chunk, ncell)
        yc = y[a:b]
        diff = yc[:, j] - yc[:, i]                              # (c, pairs)
        s = np.sign(diff).sum(axis=1)
        slope = np.median(diff / dt, axis=1)
        # pymannkendall detrends with the Sen slope per index step, computed separately; deriving it
        # as slope * step differs by ~1e-17 and can flip near-tied ranks (seen: p off by 2e-5).
        slope_idx = np.median(diff / di, axis=1)
        del diff

        # plain variance with tie correction (ties are rare in float data: loop only those rows)
        srt = np.sort(yc, axis=1)
        has_tie = (srt[:, 1:] == srt[:, :-1]).any(axis=1)
        var_s = np.full(b - a, var0)
        for r in np.where(has_tie)[0]:
            var_s[r] = (n * (n - 1) * (2 * n + 5) - _tie_term(srt[r])) / 18.0

        # Hamed-Rao: ACF of the ranks of the Sen-detrended series (index time 1..n)
        x_det = yc - np.arange(1, n + 1)[None, :] * slope_idx[:, None]
        ranks = rankdata(x_det, axis=1)
        rc = ranks - ranks.mean(axis=1, keepdims=True)
        acov0 = np.einsum("ij,ij->i", rc, rc) / n
        sni = np.zeros(b - a)
        used = np.zeros(b - a, dtype=int)
        for k in range(1, lag):
            acf = np.einsum("ij,ij->i", rc[:, :n - k], rc[:, k:]) / n / acov0
            sig = (acf > bound) | (acf < -bound)
            sni += np.where(sig, (n - k) * (n - k - 1) * (n - k - 2) * acf, 0.0)
            used += sig
        n_ns = 1 + (2 / (n * (n - 1) * (n - 2))) * sni
        var_hr = var_s * n_ns

        def pval(v):
            with np.errstate(invalid="ignore", divide="ignore"):
                z = np.where(s > 0, (s - 1) / np.sqrt(v), np.where(s < 0, (s + 1) / np.sqrt(v), 0.0))
            return 2 * (1 - ndtr(np.abs(z)))

        out["slope"][a:b] = slope
        out["p"][a:b] = pval(var_hr)
        out["p_plain"][a:b] = pval(var_s)
        out["inflation"][a:b] = n_ns
        out["s"][a:b] = s
        out["var_s"][a:b] = var_s
        out["sni_lags"][a:b] = used
    return out


def bh_fdr(p: np.ndarray, q: float = FDR_Q) -> np.ndarray:
    """Benjamini-Hochberg: boolean array, True where the hypothesis is rejected at FDR q.
    NaN p-values are not tested (False) and do not count towards m."""
    p = np.asarray(p, dtype=float)
    ok = np.isfinite(p)
    rej = np.zeros(p.shape, dtype=bool)
    pv = p[ok]
    m = pv.size
    if m == 0:
        return rej
    order = np.argsort(pv, kind="mergesort")
    passed = pv[order] <= q * np.arange(1, m + 1) / m
    if passed.any():
        kmax = np.max(np.nonzero(passed)[0])
        r = np.zeros(m, dtype=bool)
        r[order[:kmax + 1]] = True
        rej[np.flatnonzero(ok)] = r
    return rej


# ---------------------------------------------------------------- mask and outline

def _natural_earth_path() -> Path:
    import pyogrio
    return Path(pyogrio.__file__).parent / "tests" / "fixtures" / "naturalearth_lowres" / "naturalearth_lowres.shp"


def contiguous_us():
    """Shapely (Multi)Polygon of the contiguous US from Natural Earth 1:110m, or None if unavailable."""
    try:
        import pyogrio.raw
        import shapely
    except ImportError:
        return None
    path = _natural_earth_path()
    if not path.exists():
        return None
    meta, _, geom, fields = pyogrio.raw.read(str(path))
    names = list(meta["fields"])
    iso = fields[names.index("iso_a3")]
    usa = shapely.from_wkb(geom[list(iso).index("USA")])
    w, s, e, n = US_BBOX
    box = shapely.box(w, s, e, n)
    parts = [g for g in getattr(usa, "geoms", [usa]) if g.intersects(box) and g.bounds[3] < 55]
    return shapely.union_all(parts)


def us_mask(lats: np.ndarray, lons: np.ndarray, poly=None) -> np.ndarray | None:
    """Boolean (lat, lon): True where the cell centre is inside the contiguous US polygon."""
    import shapely
    poly = contiguous_us() if poly is None else poly
    if poly is None:
        return None
    LON, LAT = np.meshgrid(lons, lats)
    return shapely.contains_xy(poly, LON, LAT)


LAND_REF = "GLDAS_NOAH025_M/SoilMoi0_10cm_inst"   # land-only 0.25 deg grid: NaN over ocean and large lakes
LAND_MIN = 0.5


def land_fraction(lats: np.ndarray, lons: np.ndarray, land_lat=None, land_lon=None, land=None) -> np.ndarray | None:
    """Share of each target cell's area covered by land cells of the GLDAS 0.25-degree grid
    (cells counted by centre; GLDAS is NaN over ocean and the Great Lakes). None if unavailable."""
    if land is None:
        try:
            da = data.load_dataarray(data.find_entry(LAND_REF))
        except (FileNotFoundError, KeyError):
            return None
        da = crop(da, (US_BBOX[0] - 1, US_BBOX[1] - 1, US_BBOX[2] + 1, US_BBOX[3] + 1))
        land = ~np.isnan(da.isel(time=0).values)
        land_lat, land_lon = da["lat"].values, da["lon"].values

    def edges(c):
        c = np.asarray(c, float)
        mid = (c[1:] + c[:-1]) / 2
        return np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])

    ey, ex = np.sort(edges(lats)), edges(lons)
    iy = np.searchsorted(ey, land_lat) - 1
    ix = np.searchsorted(ex, land_lon) - 1
    ny, nx = len(lats), len(lons)
    tot = np.zeros((ny, nx))
    cnt = np.zeros((ny, nx))
    IY, IX = np.meshgrid(iy, ix, indexing="ij")
    ok = (IY >= 0) & (IY < ny) & (IX >= 0) & (IX < nx)
    if lats[0] > lats[-1]:                    # target rows north to south
        IY = ny - 1 - IY
    np.add.at(tot, (IY[ok], IX[ok]), 1)
    np.add.at(cnt, (IY[ok], IX[ok]), land[ok])
    with np.errstate(invalid="ignore"):
        return np.where(tot > 0, cnt / tot, 0.0)


def write_outline(path: Path) -> dict:
    import shapely
    poly = contiguous_us()
    if poly is None:
        raise SystemExit("No offline boundary source (pip install pyogrio shapely).")
    poly = shapely.simplify(poly, 0.02, preserve_topology=True)
    geo = json.loads(shapely.to_geojson(shapely.set_precision(poly, 0.001)))
    fc = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"name": "Contiguous United States", "source": BOUNDARY_SOURCE["name"],
                                          "licence": BOUNDARY_SOURCE["licence"]},
        "geometry": geo}]}
    path.write_text(json.dumps(fc, separators=(",", ":")), encoding="utf-8")
    return {"file": path.name, "size_bytes": path.stat().st_size, **BOUNDARY_SOURCE}


# ---------------------------------------------------------------- data

def crop(da, bbox=US_BBOX):
    """Native-grid subset with the same edge rule as app.data.regional_mean (inclusive)."""
    w, s, e, n = bbox
    da = da.sel(lat=slice(s, n)) if da["lat"][0] < da["lat"][-1] else da.sel(lat=slice(n, s))
    lon = ((da["lon"] + 180) % 360) - 180
    da = da.assign_coords(lon=lon)
    da = da.isel(lon=np.flatnonzero(((lon >= w) & (lon <= e)).values))
    return da.sortby("lat", ascending=False).sortby("lon")   # north to south, west to east


def to_series_units(entry: dict, values: np.ndarray) -> np.ndarray:
    """Stored file units -> the app's series units (only K -> degC exists; a constant offset)."""
    conv = data.CONVERSIONS.get((entry["units"], entry.get("display_units", entry["units"])))
    return conv(values) if conv else values


def decimal_years(times: pd.DatetimeIndex) -> np.ndarray:
    return (times.year + (times.month - 0.5) / 12).to_numpy(dtype=float)


def box_mean_series(entry: dict, da, bbox) -> pd.Series:
    """cos(lat)-weighted, NaN-aware box mean computed here (not via app.data), series units."""
    sub = crop(da, bbox)
    v = sub.values.astype(float)                            # (time, lat, lon)
    w = np.cos(np.deg2rad(sub["lat"].values))[None, :, None] * np.ones_like(v)
    w = np.where(np.isnan(v), 0.0, w)
    with np.errstate(invalid="ignore"):
        m = np.nansum(v * w, axis=(1, 2)) / w.sum(axis=(1, 2))
    idx = pd.to_datetime(sub["time"].values).to_period("M").to_timestamp()
    return pd.Series(to_series_units(entry, m), index=idx)


# ---------------------------------------------------------------- per-variable computation

def compute_grid(values: np.ndarray, times: pd.DatetimeIndex, mask: np.ndarray | None,
                 relative: bool = False) -> dict:
    """values (time, lat, lon) in series units. Returns per-cell slope_per_decade (series units,
    or % of the cell mean if relative), p, p_plain, fdr, plus bookkeeping."""
    nt, ny, nx = values.shape
    keep_t = ~np.isnan(values).all(axis=(1, 2))
    v = values[keep_t]
    tt = times[keep_t]
    flat = v.reshape(v.shape[0], -1).T                      # (cells, n)
    has_data = ~np.isnan(flat).all(axis=1)
    complete = ~np.isnan(flat).any(axis=1)
    inside = np.ones(ny * nx, bool) if mask is None else mask.ravel()
    use = inside & has_data

    slope = np.full(ny * nx, np.nan)
    p = np.full(ny * nx, np.nan)
    p_plain = np.full(ny * nx, np.nan)
    infl = np.full(ny * nx, np.nan)
    mean = np.full(ny * nx, np.nan)
    t = decimal_years(tt)
    months = tt.month.to_numpy()

    vec = np.flatnonzero(use & complete)
    if vec.size:
        y = deseasonalize(flat[vec], months)
        r = trend_cells(y, t)
        slope[vec], p[vec], p_plain[vec], infl[vec] = r["slope"] * 10, r["p"], r["p_plain"], r["inflation"]
        mean[vec] = flat[vec].mean(axis=1)
    gaps = np.flatnonzero(use & ~complete)
    for c in gaps:                                          # exact per-cell fallback
        ser = pd.Series(flat[c], index=tt)
        try:
            r = stats.analyze(ser, deseasonalize=True)
        except ValueError:
            continue
        slope[c], p[c], infl[c] = r["slope_per_decade"], r["p_value"], r["variance_inflation"]
        p_plain[c] = stats.mann_kendall_p(stats.remove_seasonal_cycle(ser.dropna()).to_numpy(), "plain")
        mean[c] = float(np.nanmean(flat[c]))
    if relative:
        with np.errstate(invalid="ignore", divide="ignore"):
            slope = np.where(mean > 0, slope / mean * 100, np.nan)
    tested = use & np.isfinite(p) & np.isfinite(slope)
    fdr = np.zeros(ny * nx, bool)
    fdr[tested] = bh_fdr(p[tested])
    shape = (ny, nx)
    return {"slope": slope.reshape(shape), "p": p.reshape(shape), "p_plain": p_plain.reshape(shape),
            "inflation": infl.reshape(shape), "fdr": fdr.reshape(shape), "tested": tested.reshape(shape),
            "n_months": int(keep_t.sum()), "n_dropped_months": int((~keep_t).sum()),
            "n_vectorised": int(vec.size), "n_gap_cells": int(gaps.size),
            "period": (f"{tt[0]:%Y-%m}", f"{tt[-1]:%Y-%m}")}


def scale_limit(slope: np.ndarray, tested: np.ndarray) -> float:
    a = np.abs(slope[tested])
    v = float(np.percentile(a, CLIP_PERCENTILE)) if a.size else 1.0
    return v if v > 0 else 1.0


def rgba_image(slope, fdr, tested, vmax) -> np.ndarray:
    import matplotlib
    cmap = matplotlib.colormaps[CMAP]
    x = np.clip((np.nan_to_num(slope) + vmax) / (2 * vmax), 0, 1)
    img = (cmap(x) * 255).round().astype(np.uint8)
    img[..., 3] = np.where(fdr, ALPHA_SIG, ALPHA_NONSIG)
    img[..., 3][~tested] = 0
    img[~tested, :3] = 0
    return img


def _sig3(x: float):
    return None if not math.isfinite(x) else float(f"{x:.3g}")


def write_variable(entry: dict, key: str, res: dict, lats, lons, outdir: Path, masked: bool,
                   relative: bool = False, runtime_s: float | None = None) -> dict:
    """Write <key>.png, <key>.json, <key>_cells.json. Returns the metadata dict."""
    import matplotlib.image
    outdir.mkdir(parents=True, exist_ok=True)
    k = display.slope_factor(entry)                          # series units -> display units
    slope = res["slope"] if relative else res["slope"] * k
    tested, fdr = res["tested"], res["fdr"]
    vmax = scale_limit(slope, tested)
    img = rgba_image(slope, fdr, tested, vmax)
    matplotlib.image.imsave(outdir / f"{key}.png", img)

    dlat = float(abs(lats[0] - lats[1])) if len(lats) > 1 else 0.0
    dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 0.0
    unit = display.unit_label(entry)
    slope_units = "% of the cell's mean per decade" if relative else f"{unit} per decade"
    n_t, n_sig = int(tested.sum()), int((fdr & tested).sum())
    n_raw = int(((res["p"] < 0.05) & tested).sum())
    meta = {
        "variable": entry["id"], "key": key, "name": entry["name"],
        "description": (f"Change in {display.lower_first(entry['name'])} per decade in each grid cell, "
                        f"{res['period'][0]} to {res['period'][1]}; solid colour = significant after "
                        f"correcting for testing many cells at once (FDR {FDR_Q:.0%}), faded = not significant."),
        "image": f"{key}.png", "cells": f"{key}_cells.json",
        "bounds": {"west": float(lons[0] - dlon / 2), "south": float(lats[-1] - dlat / 2),
                   "east": float(lons[-1] + dlon / 2), "north": float(lats[0] + dlat / 2)},
        "bounds_note": "outer edges of the edge cells (cell centres +- half a cell); image row 0 = north",
        "crop_bbox": list(US_BBOX),
        "grid": {"nlat": int(len(lats)), "nlon": int(len(lons)), "dlat": dlat, "dlon": dlon,
                 "lat_first": float(lats[0]), "lon_first": float(lons[0])},
        "units": data.display_units(entry), "display_units": unit, "slope_units": slope_units,
        "relative_change": bool(relative),
        "display_conversion": None if relative else display.conversion_note(entry),
        "scale": {"min": -vmax, "max": vmax, "clip_percentile_abs": CLIP_PERCENTILE, "colormap": CMAP,
                  "colors": "red = increase, blue = decrease, white = no change",
                  "opacity_significant": ALPHA_SIG / 255, "opacity_not_significant": round(ALPHA_NONSIG / 255, 3),
                  "rendering": "nearest-neighbour; one pixel per grid cell"},
        "period": {"start": res["period"][0], "end": res["period"][1], "n_months": res["n_months"],
                   "months_dropped_missing_everywhere": res["n_dropped_months"]},
        "method": ("Per cell: monthly series, seasonal cycle removed (calendar-month means subtracted); "
                   "Sen's slope vs time in years, x10 per decade; two-sided Mann-Kendall test with the "
                   f"Hamed & Rao (1998) variance correction using the significant autocorrelations "
                   f"(at {ALPHA:g}) of lags 1-{HR_LAGS} of the ranks of the Sen-detrended series - the "
                   "same computation as the app's /trend default (stats.analyze, method='corrected'), "
                   "vectorised over cells; cells with gaps use stats.analyze directly. Multiple testing: "
                   f"Benjamini-Hochberg FDR at q={FDR_Q:g} across all unmasked cells; 'significant' = passed FDR."
                   + (" Relative change = Sen's slope / the cell's mean over the period x 100." if relative else "")),
        "autocorrelation_method": f"Hamed-Rao (1998), lags 1-{HR_LAGS}, exact (pymannkendall-equivalent)",
        "fdr_level": FDR_Q,
        "mask": masked if isinstance(masked, str) else (
            "cell centre inside the Natural Earth 1:110m contiguous-US polygon" if masked else "none"),
        "n_cells_tested": n_t, "n_significant_fdr": n_sig,
        "percent_significant_fdr": round(100 * n_sig / n_t, 2) if n_t else 0.0,
        "n_raw_p_below_0.05": n_raw, "percent_raw_p_below_0.05": round(100 * n_raw / n_t, 2) if n_t else 0.0,
        "slope_range": [_sig3(float(np.nanmin(slope[tested]))), _sig3(float(np.nanmax(slope[tested])))] if n_t else None,
        "source": f"NASA {entry['short_name']} v{entry.get('version', '?')}",
        "generated_by": "make_trend_maps.py",
    }
    if runtime_s is not None:
        meta["runtime_seconds"] = round(runtime_s, 1)

    if key in CAVEATS:
        meta["caveat"] = CAVEATS[key]
    # Compact, sparse: one flag character per grid cell; slope and p only for tested cells.
    tv = tested.ravel()
    flag = "".join("-" if not t else ("1" if f else "0") for f, t in zip(fdr.ravel(), tv))
    cells = {"key": key,
             "decode": ("flag has one character per grid cell, row-major, row 0 = north (same as the PNG), "
                        "cell index = row * nlon + col: '-' = masked or no data, '1' = significant after FDR, "
                        "'0' = not significant. slope and p list only the non-'-' cells, in the same order "
                        "(the k-th non-'-' character of flag is slope[k], p[k]). p = raw Hamed-Rao "
                        "Mann-Kendall p-value (2 significant figures); slope 3 significant figures."),
             "nlat": int(len(lats)), "nlon": int(len(lons)),
             "lat": [round(float(x), 4) for x in lats], "lon": [round(float(x), 4) for x in lons],
             "slope_units": slope_units, "flag": flag,
             "slope": [_sig3(float(x)) for x in slope.ravel()[tv]],
             "p": [float(f"{x:.2g}") for x in res["p"].ravel()[tv]]}
    (outdir / f"{key}_cells.json").write_text(json.dumps(cells, separators=(",", ":")), encoding="utf-8")
    meta["file_bytes"] = {f: (outdir / f).stat().st_size for f in (f"{key}.png", f"{key}.json", f"{key}_cells.json")
                          if (outdir / f).exists()}
    (outdir / f"{key}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    meta["file_bytes"][f"{key}.json"] = (outdir / f"{key}.json").stat().st_size
    return meta


def write_index(outdir: Path, outline: dict | None = None) -> None:
    entries = []
    for f in sorted(outdir.glob("*.json")):
        if f.name.endswith("_cells.json"):
            continue
        m = json.loads(f.read_text(encoding="utf-8"))
        entries.append({k: m.get(k) for k in ("key", "variable", "name", "image", "cells", "slope_units",
                                               "period", "percent_significant_fdr", "description")}
                       | {"metadata": f.name})
    old = {}
    if (outdir / "index.yml").exists():
        old = yaml.safe_load((outdir / "index.yml").read_text(encoding="utf-8")) or {}
    doc = {"generated_by": "make_trend_maps.py", "fdr_level": FDR_Q, "crop_bbox": list(US_BBOX),
           "variables": entries,
           "boundaries": outline or old.get("boundaries")}
    with open(outdir / "index.yml", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Generated by make_trend_maps.py - do not edit by hand.\n")
        yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True)


def preview(key: str, meta: dict, outline_poly, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    img = matplotlib.image.imread(MAPS_DIR / meta["image"])
    b = meta["bounds"]
    fig, ax = plt.subplots(figsize=(11, 5.6), dpi=110)
    ax.set_facecolor("#e8e8e8")
    ax.imshow(img, extent=(b["west"], b["east"], b["south"], b["north"]), interpolation="nearest")
    if outline_poly is not None:
        for g in getattr(outline_poly, "geoms", [outline_poly]):
            x, y = g.exterior.xy
            ax.plot(x, y, color="k", lw=0.6)
    sm = plt.cm.ScalarMappable(norm=Normalize(meta["scale"]["min"], meta["scale"]["max"]), cmap=CMAP)
    fig.colorbar(sm, ax=ax, shrink=0.8, label=meta["slope_units"])
    ax.set_title(f"{meta['name']} {meta['period']['start']}..{meta['period']['end']}: "
                 f"{meta['percent_significant_fdr']}% of cells significant (FDR {FDR_Q:.0%}); faded = not significant",
                 fontsize=9)
    ax.set_xlim(US_BBOX[0] - 1, US_BBOX[2] + 1)
    ax.set_ylim(US_BBOX[1] - 1, US_BBOX[3] + 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- checks

def consistency_check(entry: dict, da, region: str = "southwest", relative: bool = False) -> dict:
    """Trend of the box mean computed with this module vs stats.analyze on the committed CSV."""
    bbox = tuple(presets.load_presets()[region]["bbox"])
    mine = box_mean_series(entry, da, bbox).dropna()
    csv = presets.load_series(entry, region)
    out = {"variable": entry["id"], "region": region, "csv": None}
    t = decimal_years(mine.index)
    y = deseasonalize(mine.to_numpy()[None, :], mine.index.month.to_numpy())
    r = trend_cells(y, t)
    out.update(map_slope_per_decade=float(r["slope"][0] * 10), map_p=float(r["p"][0]))
    if csv is not None:
        ref = stats.analyze(csv, deseasonalize=True)
        a, b = mine.align(csv.dropna(), join="outer")
        out.update(csv=presets.series_path(entry, region).name,
                   csv_slope_per_decade=ref["slope_per_decade"], csv_p=ref["p_value"],
                   max_abs_value_diff=float(np.nanmax(np.abs(a - b))),
                   n_month_mismatch=int((a.isna() != b.isna()).sum()))
        out["slope_diff"] = out["map_slope_per_decade"] - ref["slope_per_decade"]
        out["p_diff"] = out["map_p"] - ref["p_value"]
        scale = max(abs(ref["slope_per_decade"]), 1e-12)
        out["ok"] = bool(abs(out["slope_diff"]) <= 1e-6 * scale + 1e-12 and abs(out["p_diff"]) <= 1e-6
                         and out["n_month_mismatch"] == 0)
    return out


def spot_check(values, times, res, n: int = 25, seed: int = 0) -> dict:
    """Compare random tested cells with stats.analyze (the app's own code path)."""
    rng = np.random.default_rng(seed)
    idx = np.argwhere(res["tested"])
    pick = idx[rng.choice(len(idx), size=min(n, len(idx)), replace=False)]
    ds, dp = [], []
    for r, c in pick:
        ser = pd.Series(values[:, r, c], index=times)
        a = stats.analyze(ser, deseasonalize=True)
        ds.append(abs(a["slope_per_decade"] - res["slope"][r, c]) / max(abs(a["slope_per_decade"]), 1e-12))
        dp.append(abs(a["p_value"] - res["p"][r, c]))
    return {"cells": int(len(pick)), "max_rel_slope_diff": float(max(ds)), "max_abs_p_diff": float(max(dp))}


# ---------------------------------------------------------------- driver

def run_variable(var_id: str, poly, outdir: Path = MAPS_DIR) -> dict:
    t0 = time.time()
    entry = data.find_entry(var_id)
    key = presets.var_key(entry)
    relative = var_id in RELATIVE
    da_full = data.load_dataarray(entry)
    da = crop(da_full)
    lats, lons = da["lat"].values.astype(float), da["lon"].values.astype(float)
    times = pd.DatetimeIndex(pd.to_datetime(da["time"].values).to_period("M").to_timestamp())
    values = to_series_units(entry, da.values.astype(float))
    t_load = time.time() - t0
    mask = us_mask(lats, lons, poly) if poly is not None else None
    lf = land_fraction(lats, lons)
    if lf is not None:
        mask = (lf >= LAND_MIN) if mask is None else (mask & (lf >= LAND_MIN))
    else:
        log.warning("%s: GLDAS land grid unavailable; lakes and coastal water cells are not masked", key)
    mask_text = " and ".join(
        ([f"cell centre inside the Natural Earth 1:110m contiguous-US polygon"] if poly is not None else [])
        + ([f"at least {LAND_MIN:.0%} of the cell is land on the GLDAS 0.25-degree land grid "
            "(removes ocean, Great Lakes and mostly-water coastal cells)"] if lf is not None else [])) or "none"

    cc = consistency_check(entry, da_full, relative=relative)
    log.info("%s consistency (southwest box mean, this code vs committed CSV): %s", key, json.dumps(cc))
    if cc.get("csv") and not cc["ok"]:
        raise SystemExit(f"STOP: consistency check failed for {key}: {cc}")

    t1 = time.time()
    res = compute_grid(values, times, mask, relative=False)
    t_stats = time.time() - t1
    spot = spot_check(values, times, res)
    log.info("%s spot check vs stats.analyze on %d cells: max rel slope diff %.2e, max |p diff| %.2e",
             key, spot["cells"], spot["max_rel_slope_diff"], spot["max_abs_p_diff"])
    if relative:
        res = compute_grid(values, times, mask, relative=True)
    meta = write_variable(entry, key, res, lats, lons, outdir, masked=mask_text,
                          relative=relative, runtime_s=time.time() - t0)
    preview(key, meta, poly, PREVIEW_DIR / f"{key}.png")
    meta.update(consistency=cc, spot_check=spot, t_load=t_load, t_stats=t_stats,
                n_vectorised=res["n_vectorised"], n_gap_cells=res["n_gap_cells"])
    infl = res["inflation"][res["tested"]]
    log.info("%s: grid %dx%d, %d months %s..%s, tested %d cells (%d vectorised, %d gap fallback), "
             "FDR-significant %d (%.1f%%), raw p<0.05 %.1f%%, slope %s..%s %s, scale +-%.4g, "
             "median inflation %.2f, load %.1fs, stats %.1fs, total %.1fs, files %s",
             key, len(lats), len(lons), res["n_months"], *res["period"], meta["n_cells_tested"],
             res["n_vectorised"], res["n_gap_cells"], meta["n_significant_fdr"], meta["percent_significant_fdr"],
             meta["percent_raw_p_below_0.05"], *meta["slope_range"], meta["slope_units"], meta["scale"]["max"],
             float(np.median(infl)) if infl.size else float("nan"), t_load, t_stats, time.time() - t0,
             meta["file_bytes"])
    return meta


def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(LOG_DIR / "make_trend_maps.log", encoding="utf-8"), logging.StreamHandler()):
        h.setFormatter(fmt)
        log.addHandler(h)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("keys", nargs="*", help="series keys (e.g. T2M precipitation); default: first pass")
    ap.add_argument("--second", action="store_true", help="run the second-pass variables")
    ap.add_argument("--outline-only", action="store_true")
    args = ap.parse_args(argv)
    setup_logging()
    MAPS_DIR.mkdir(parents=True, exist_ok=True)

    poly = contiguous_us()
    if poly is None:
        log.warning("No offline US boundary (pip install -r requirements-maps.txt); maps are NOT masked.")
    outline = write_outline(MAPS_DIR / "us_outline.geojson") if poly is not None else None
    if args.outline_only:
        write_index(MAPS_DIR, outline)
        return
    if args.keys:
        allv = {presets.var_key(data.find_entry(v)): v for v in FIRST_PASS + SECOND_PASS}
        todo = [allv[k] for k in args.keys]
    else:
        todo = SECOND_PASS if args.second else FIRST_PASS
    log.info("run: %s | method: seasonal cycle removed, Sen's slope, Mann-Kendall + Hamed-Rao lags 1-%d "
             "(vectorised, exact), BH FDR q=%.2f, mask=%s", todo, HR_LAGS, FDR_Q,
             "Natural Earth 110m contiguous US" if poly is not None else "none")
    t0 = time.time()
    for v in todo:
        run_variable(v, poly)
    write_index(MAPS_DIR, outline)
    total = sum(f.stat().st_size for f in MAPS_DIR.iterdir() if f.is_file())
    log.info("done %s in %.1fs; data/maps total %.2f MB", todo, time.time() - t0, total / 1e6)


if __name__ == "__main__":
    main()
