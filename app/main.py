"""FastAPI backend. Reads pre-processed files only - never calls NASA."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import common
import stats
from app import data

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Earth System Trend Detective")


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


@app.get("/variables")
def variables(category: str | None = None):
    return [{"id": e["id"], "category": c, "name": e["name"],
             "description": _clean(e["description"]), "note": _clean(e.get("note")),
             "units": data.display_units(e), "has_data": common.processed_path(e).exists()}
            for c, e in common.iter_entries(common.load_catalog(), category)]


def _series(variable, bbox, start, end):
    entry = _entry(variable)
    try:
        ser = data.regional_mean(entry, data.parse_bbox(bbox), start, end)
    except FileNotFoundError as ex:
        raise HTTPException(503, str(ex))
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    return entry, ser


@app.get("/timeseries")
def timeseries(variable: str, bbox: str, start: str | None = None, end: str | None = None):
    """bbox = west,south,east,north ; start/end = YYYY-MM"""
    entry, ser = _series(variable, bbox, start, end)
    return {"variable": variable, "units": data.display_units(entry),
            "dates": [d.strftime("%Y-%m") for d in ser.index], "values": ser.round(4).tolist()}


@app.get("/trend")
def trend(variable: str, bbox: str, start: str | None = None, end: str | None = None,
          deseasonalize: bool = True):
    entry, ser = _series(variable, bbox, start, end)
    try:
        r = stats.analyze(ser, deseasonalize=deseasonalize)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    fitted = r.pop("fitted")
    return {
        "variable": variable, "name": entry["name"], "units": data.display_units(entry),
        "description": _clean(entry["description"]), "note": _clean(entry.get("note")),
        "dates": [d.strftime("%Y-%m") for d in ser.index], "values": ser.round(4).tolist(),
        "fitted": fitted.round(4).tolist(),
        **{k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()},
        "verdict": stats.verdict(r["significant"]),
        "lens_message": None,   # lenses arrive after Step 1 is confirmed
    }


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
