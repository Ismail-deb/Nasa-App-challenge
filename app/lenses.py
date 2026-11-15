"""Lenses (lenses.yml): plain-language template sentences for a trend result. Templates only."""
import yaml

import common

DIRECTIONS = ("increasing", "decreasing")
SIGNIFICANCE = ("significant", "not_significant")


def load() -> dict:
    """The parsed lenses.yml: {"disclaimer", "not_significant", "lenses": {id: {...}}}."""
    with open(common.ROOT / "lenses.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def variables(lens_id: str) -> list:
    """Catalog variable ids in this lens, in lenses.yml order. KeyError for an unknown lens."""
    return list(load()["lenses"][lens_id]["templates"])


def direction(slope: float) -> str | None:
    """From the sign of Sen's slope; None for exactly zero (treated as not significant)."""
    return "increasing" if slope > 0 else "decreasing" if slope < 0 else None


def template(lens_id: str, var_id: str, direction_: str | None, significance: str) -> str:
    """The sentence for one (lens, variable, direction, significance) key, without disclaimer.
    KeyError if the lens or the variable in that lens is unknown."""
    cfg = load()
    templates = cfg["lenses"][lens_id]["templates"][var_id]
    if significance == "significant" and direction_ in DIRECTIONS:
        return templates[direction_]
    if significance not in SIGNIFICANCE:
        raise KeyError(significance)
    return cfg["not_significant"]


def message(lens_id: str, var_id: str, slope: float, significant: bool,
            reliability: str = "ok") -> str | None:
    """Lens sentence plus the disclaimer, or None when reliability is 'low' (no lens sentence)."""
    if reliability == "low":
        return None
    sig = "significant" if significant else "not_significant"
    return f"{template(lens_id, var_id, direction(slope), sig)} {load()['disclaimer']}"


def caveat(lens_id: str) -> str:
    return " ".join(load()["lenses"][lens_id]["caveat"].split())
