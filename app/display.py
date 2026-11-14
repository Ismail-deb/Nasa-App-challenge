"""Presentation layer: readable units, display conversions, number formatting, headline and
explanation text. It never changes the stored data or the statistics: the trend test runs on the
stored series; only what is shown is converted and worded here."""
import math

import numpy as np
import pandas as pd

MEAN_DAYS_PER_MONTH = 365.25 / 12
HOURS_PER_MEAN_MONTH = 24 * MEAN_DAYS_PER_MONTH          # 730.5

# stored-series unit (as recorded in catalog/index) -> readable label
UNIT_LABELS = {
    "degC": "°C", "°C": "°C", "K": "K",
    "m s-1": "m/s",
    "W m-2": "W/m²",
    "kg m-2": "kg/m² (= mm of water)",
    "kg m-2 s-1": "kg/m² per second (= mm of water per second)",
    "Pa": "Pa",
    "m": "m",
    "1": "unitless",
    "mm/hr": "mm/hr",
    "mm/month": "mm/month",
}


def unit_label(entry: dict) -> str:
    """Readable unit for what the user sees (after any card conversion)."""
    if entry.get("unit_label"):
        return entry["unit_label"]
    u = entry.get("card_units") or entry.get("display_units") or entry["units"]
    return UNIT_LABELS.get(u, u)


# ---------------------------------------------------------------- conversions

def _check_mm_per_hour(entry, series_units):
    if entry["units"] != "mm/hr" or series_units not in (None, "mm/hr"):
        raise ValueError(f"{entry['id']}: expected stored units mm/hr for the mm/month display, "
                         f"got file units {entry['units']!r}, series units {series_units!r}")


def convert_values(entry: dict, ser: pd.Series, series_units: str | None = None) -> pd.Series:
    """Monthly series values in display units. Precipitation (IMERG mean rate, mm/hr) becomes
    mm/month: rate x 24 x days in that calendar month."""
    if entry.get("card_units") == "mm/month":
        _check_mm_per_hour(entry, series_units)
        return ser * 24 * ser.index.days_in_month
    return ser


def slope_factor(entry: dict, series_units: str | None = None) -> float:
    """Factor turning a slope (or range end, or fitted value) from stored units into display
    units. One constant for every month, so slope, both range ends and the fitted line convert
    the same way and the significance test is untouched (mm/hr -> mm per average month)."""
    if entry.get("card_units") == "mm/month":
        _check_mm_per_hour(entry, series_units)
        return HOURS_PER_MEAN_MONTH
    return 1.0


# ---------------------------------------------------------------- formatting

def fmt_signed(x: float) -> str:
    """Signed number that never collapses to '+0.00':
    |x| >= 0.1 -> 2 decimals; 0.0001 <= |x| < 0.1 -> 2 significant figures; smaller -> 'about 0'."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    if x == 0:
        return "0"
    a = abs(x)
    sign = "+" if x > 0 else "-"
    if a >= 0.1:
        return f"{sign}{a:.2f}"
    if a < 1e-4:
        return "about 0"
    decimals = -math.floor(math.log10(a)) + 1                 # 2 significant figures
    s = f"{a:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return f"{sign}{s}"


def fmt_range(lo: float, hi: float) -> str:
    return f"{fmt_signed(lo)} to {fmt_signed(hi)}"


def lower_first(name: str) -> str:
    return name[0].lower() + name[1:] if name and not name[:2].isupper() else name


def headline(name: str, significant: bool, trend: str, region_name: str | None) -> str:
    if not significant:
        where = region_name or "the selected region"
        return f"No clear trend in {lower_first(name)} for {where}"
    return f"{name} is {trend}"


def explanation(significant: bool, years: float, slope_text: str, units: str,
                deseasonalized: bool, method: str, percent_text: str | None = None) -> str:
    change = f"{slope_text} {units} per decade" + (f" ({percent_text} of the average)" if percent_text else "")
    parts = [f"Over {years:.1f} years, the fitted change is {change}."]
    if significant:
        parts.append("Significant means a trend this large would be unlikely (p < 0.05) "
                     "if there were only random variation.")
    else:
        parts.append("Not significant means the change is within normal year-to-year variation. "
                     "It does not prove there is no trend; a longer record may reveal one.")
    if deseasonalized:
        parts.append("The seasonal cycle was removed before testing; the chart shows the raw monthly values.")
    parts.append("The test allows for month-to-month persistence in the data." if method == "corrected"
                 else "Plain test: assumes every month is independent.")
    return " ".join(parts)


# ---------------------------------------------------------------- assemble a trend result

def present(entry: dict, ser: pd.Series, fitted: pd.Series, r: dict, region_name: str | None,
            series_units: str | None = None) -> dict:
    """Display fields for /trend. `ser` and `fitted` are in stored-series units; `r` is the
    stats result (unchanged). Returns display-unit values and the text for the result card."""
    k = slope_factor(entry, series_units)
    values = convert_values(entry, ser, series_units)
    fitted_disp = fitted * k
    out = {
        "units": unit_label(entry),
        "series_units": series_units or entry.get("display_units") or entry["units"],
        "values_display": values,
        "fitted_display": fitted_disp,
    }
    for key in ("slope_per_decade", "ci_low_per_decade", "ci_high_per_decade",
                "ci_plain_low_per_decade", "ci_plain_high_per_decade"):
        out[key] = r[key] * k
    mean = float(np.nanmean(ser.to_numpy(dtype=float)))
    out["mean_value"] = float(np.nanmean(values.to_numpy(dtype=float)))
    pct = entry.get("relative_change") and mean > 0
    out["percent_per_decade"] = r["slope_per_decade"] / mean * 100 if pct else None
    out["ci_low_percent"] = r["ci_low_per_decade"] / mean * 100 if pct else None
    out["ci_high_percent"] = r["ci_high_per_decade"] / mean * 100 if pct else None

    out["slope_text"] = fmt_signed(out["slope_per_decade"])
    out["range_text"] = fmt_range(out["ci_low_per_decade"], out["ci_high_per_decade"])
    out["percent_text"] = f"{fmt_signed(out['percent_per_decade'])}%" if pct else None
    out["percent_range_text"] = (f"{fmt_signed(out['ci_low_percent'])}% to {fmt_signed(out['ci_high_percent'])}%"
                                 if pct else None)
    out["headline"] = headline(entry["name"], r["significant"], r["trend"], region_name)
    out["explanation"] = explanation(r["significant"], r["record_years"], out["slope_text"], out["units"],
                                     r["deseasonalized"], r["method"], out["percent_text"])
    return out
