"""FastAPI backend. Reads pre-processed files only - never calls NASA."""
from pathlib import Path

import math

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import common
import stats
from app import data, display, lenses, presets

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Earth System Trend Detective")
# the browser must re-validate the page and its scripts, so an old copy is never run after an update
NO_CACHE = {"Cache-Control": "no-cache"}


def _clean(text: str | None) -> str | None:
    return " ".join(text.split()) if text else None


def _entry(variable: str) -> dict:
    try:
        return data.find_entry(variable)
    except KeyError:
        raise HTTPException(404, f"Unknown variable {variable!r}")


@app.get("/categories")
def categories():
    cats = common.load_catalog()["categories"]
    return [{"id": k, "label": v["label"], "n_variables": len(v.get("variables", []))}
            for k, v in cats.items()]


def _preset_regions_with_series(entry: dict) -> list:
    return [pid for pid in presets.load_presets() if presets.series_path(entry, pid).exists()]


def _periods() -> dict:
    """variable id -> (first month, last month) over its exported preset series."""
    out = {}
    for r in presets.read_index():
        a, b = out.get(r["variable"], (r["period_start"], r["period_end"]))
        out[r["variable"]] = (min(a, r["period_start"]), max(b, r["period_end"]))
    return out


def _lens_variables(lens: str) -> list:
    try:
        return lenses.variables(lens)
    except KeyError:
        raise HTTPException(404, f"Unknown lens {lens!r}. Lenses: {', '.join(lenses.load()['lenses'])}.")


@app.get("/lenses")
def list_lenses():
    """The lenses, their variables (and whether each has any data yet), caveat and disclaimer."""
    cfg, avail = lenses.load(), {v["id"]: v["has_data"] for v in variables()}
    return [{"id": lid, "name": l["name"], "description": l["description"],
             "caveat": lenses.caveat(lid), "disclaimer": cfg["disclaimer"],
             "default_variable": l["default_variable"],
             "variables": [{"id": v, "has_data": avail.get(v, False)} for v in l["templates"]]}
            for lid, l in cfg["lenses"].items()]


@app.get("/variables")
def variables(category: str | None = None, lens: str | None = None):
    """Catalog variables; with `lens`, only that lens's variables, in lens order."""
    out, periods = [], _periods()
    entries = list(common.iter_entries(common.load_catalog(), category))
    if lens:
        order = _lens_variables(lens)
        entries = sorted((ce for ce in entries if ce[1]["id"] in order), key=lambda ce: order.index(ce[1]["id"]))
    for c, e in entries:
        gridded, regions = common.processed_path(e).exists(), _preset_regions_with_series(e)
        start, end = periods.get(e["id"], (None, None))
        out.append({"id": e["id"], "category": c, "name": e["name"],
                    "description": _clean(e["description"]), "note": _clean(e.get("note")),
                    "units": display.unit_label(e), "has_data": gridded or bool(regions),
                    "gridded": gridded, "presets_available": regions,
                    "period_start": start, "period_end": end})
    return out


@app.get("/presets")
def list_presets():
    """Preset demo regions, their recommended lens, and which variables are ready for each."""
    entries = [e for _, e in common.iter_entries(common.load_catalog())]
    return [{"id": pid, "name": p["name"], "bbox": p["bbox"], "lens": p["lens"], "why": p.get("why"),
             "variables": [e["id"] for e in entries if presets.series_path(e, pid).exists()]}
            for pid, p in presets.load_presets().items()]


def _series(variable, bbox, start, end):
    """Monthly regional series in stored-series units. Returns (entry, series, source, region, units).

    1. bbox matches a preset (within presets.BBOX_TOLERANCE) and its series file exists
       -> precomputed series from data/series/   (source = "preset_series")
    2. else the gridded file exists -> cos(lat)-weighted regional mean (source = "gridded")
    3. else a friendly 404.
    """
    entry = _entry(variable)
    try:
        box = data.parse_bbox(bbox)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    region = presets.match_preset(box)
    ser = presets.load_series(entry, region) if region else None
    if ser is not None:
        ser = ser.loc[start:end] if (start or end) else ser
        if ser.empty:
            raise HTTPException(400, "No data in the requested period.")
        units = presets.series_units(entry, region) or data.display_units(entry)
        return entry, ser, "preset_series", region, units
    try:
        return entry, data.regional_mean(entry, box, start, end), "gridded", region, data.display_units(entry)
    except FileNotFoundError:
        ready = _preset_regions_with_series(entry)
        hint = (f"{entry['name']} is ready for: {', '.join(ready)}." if ready
                else f"{entry['name']} is not ready for any preset yet.")
        if region is None:      # not a preset: only the multi-GB gridded files can answer this
            raise HTTPException(404, "This is a custom region (it does not match a demo region). "
                                     "Custom regions need the full dataset and are only available on the "
                                     "machine that has it; this copy has the demo regions only. "
                                     f"Use a Demo button to see one. {hint}")
        raise HTTPException(404, f"Region/variable not available yet, try a preset. {hint}")
    except ValueError as ex:
        raise HTTPException(400, str(ex))


def _values(ser) -> list:
    """Rounded values with NaN as null (NaN is not valid JSON)."""
    return [None if (v is None or math.isnan(v)) else round(float(v), 4) for v in ser.tolist()]


@app.get("/timeseries")
def timeseries(variable: str, bbox: str, start: str | None = None, end: str | None = None):
    """bbox = west,south,east,north ; start/end = YYYY-MM"""
    entry, ser, source, region, units = _series(variable, bbox, start, end)
    return {"variable": variable, "units": display.unit_label(entry),
            "dates": [d.strftime("%Y-%m") for d in ser.index],
            "values": _values(display.convert_values(entry, ser, units)),
            "source": source, "region": region}


def _reliability(entry: dict, ser, units: str) -> dict | None:
    """Reliability check for zero-inflated variables (snow); None (= ok, not checked) otherwise.
    The catalog threshold is in display units; the series is in stored units."""
    if not entry.get("zero_inflated"):
        return None
    peak_min = entry.get("min_seasonal_peak")
    if peak_min is not None:
        peak_min = peak_min / display.slope_factor(entry, units)
    return stats.reliability(ser, peak_min)


@app.get("/trend")
def trend(variable: str, bbox: str, start: str | None = None, end: str | None = None,
          deseasonalize: bool = True, method: str = "corrected", lens: str | None = None):
    """method = corrected (autocorrelation-corrected Mann-Kendall, default) or plain.
    lens = solar | wind | hydro | farming (optional): adds lens_message and lens_caveat."""
    if lens and variable not in _lens_variables(lens):
        raise HTTPException(400, f"Variable {variable!r} is not in the {lens} lens. "
                                 f"Its variables are: {', '.join(lenses.variables(lens))}.")
    entry, ser, source, region, units = _series(variable, bbox, start, end)
    try:
        r = stats.analyze(ser, deseasonalize=deseasonalize, method=method)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    fitted = r.pop("fitted")
    region_name = presets.load_presets()[region]["name"] if region else None
    try:
        rel = _reliability(entry, ser, units)
        shown = display.present(entry, ser, fitted, r, region_name, units, rel)
    except ValueError as ex:                      # unexpected stored units: refuse, do not guess
        raise HTTPException(500, str(ex))
    values, fitted_shown = shown.pop("values_display"), shown.pop("fitted_display")
    r.update({k: shown.pop(k) for k in list(shown) if k in r})   # slope/ranges in display units
    return {
        "variable": variable, "name": entry["name"],
        "description": _clean(entry["description"]), "note": _clean(entry.get("note")),
        "dates": [d.strftime("%Y-%m") for d in ser.index], "values": _values(values),
        "fitted": _values(fitted_shown.reindex(ser.index)),   # same length as values; gaps -> null
        **{k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()},
        **{k: (round(v, 5) if isinstance(v, float) else v) for k, v in shown.items()},
        "lens": lens,
        # template sentence + disclaimer; None without a lens or when reliability is "low"
        "lens_message": (lenses.message(lens, variable, r["slope_per_decade"], r["significant"],
                                        shown["reliability"]) if lens else None),
        "lens_caveat": lenses.caveat(lens) if lens else None,
        "source": source,       # "preset_series" (data/series/) or "gridded" (data/processed/)
        "region": region,       # preset id when the bbox matches one, else null
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """No icon: answer 204 so browsers stop logging a 404 for it."""
    return Response(status_code=204)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers=NO_CACHE)


class _FreshStatic(StaticFiles):
    """Static files that the browser re-checks on every load (never a stale page script)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE)
        return response


app.mount("/static", _FreshStatic(directory=WEB), name="static")


# ---------------------------------------------------------------- optional 3D globe (web/globe/)
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
LOCAL_CONFIG = FRONTEND / "config.local.js"     # git-ignored; holds the Cesium ion token, if any
# served when there is no config.local.js: no token, so the globe runs in offline mode
NO_TOKEN_JS = 'window.CESIUM_ION_TOKEN = window.CESIUM_ION_TOKEN || "";\n'


@app.get("/frontend/config.local.js", include_in_schema=False)
def local_config():
    """The local token file, or an empty-token stand-in: never a 404 (no console noise)."""
    path = LOCAL_CONFIG
    js = path.read_text(encoding="utf-8") if path.is_file() else NO_TOKEN_JS
    return Response(js, media_type="text/javascript", headers=NO_CACHE)


# vendored CesiumJS (frontend/vendor/cesium); missing directory -> 404s, and the globe falls back to Classic
app.mount("/vendor/cesium", StaticFiles(directory=FRONTEND / "vendor" / "cesium", check_dir=False),
          name="cesium")
