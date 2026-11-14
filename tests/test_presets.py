"""Preset config and bbox matching (no data needed)."""
from app import presets


def test_presets_file_is_valid():
    p = presets.load_presets()
    assert set(p) == {"southwest", "great_plains", "pacific_northwest", "central_valley"}
    assert {v["lens"] for v in p.values()} == {"solar", "wind", "hydro", "farming"}
    for v in p.values():
        w, s, e, n = v["bbox"]
        assert -180 <= w < e <= 180 and -90 <= s < n <= 90 and v["name"]


def test_match_preset_exact_tolerance_and_miss():
    p = presets.load_presets()
    sw = p["southwest"]["bbox"]
    assert presets.match_preset(sw, p) == "southwest"
    assert presets.match_preset([x + 0.04 for x in sw], p) == "southwest"      # within 0.05
    assert presets.match_preset([sw[0] + 0.2] + sw[1:], p) is None            # one edge off
    assert presets.match_preset((0, 0, 1, 1), p) is None


WIND_LABEL = ("50 m wind speed computed from monthly-mean wind components (speed of the mean vector); "
              "it underestimates average wind speed and is useful for relative change over time, not "
              "for absolute wind resource")


def _catalog_entry(var_id):
    import common
    return next(e for _, e in common.iter_entries(common.load_catalog()) if e["id"] == var_id)


def test_wind_is_labelled_honestly_in_catalog():
    e = _catalog_entry("M2TMNXSLV/WIND50M")
    clean = lambda s: " ".join(s.split())
    assert WIND_LABEL in clean(e["description"]) and WIND_LABEL in clean(e["note"])


def test_soil_moisture_units_explained():
    e = _catalog_entry("GLDAS_NOAH025_M/SoilMoi0_10cm_inst")
    assert "millimetres of water" in " ".join(e["description"].split())
