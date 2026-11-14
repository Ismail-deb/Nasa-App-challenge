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
