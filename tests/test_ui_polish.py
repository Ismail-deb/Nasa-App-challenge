"""UI polish: the context line above the result and the trend-map legend's significance line.
Both are built from real data (the /trend response, /lenses, the map JSON) and hidden when nothing
is loaded; neither hard-codes a variable. Also: the header hero, scenario-card accents and footer."""
import json
import re

import pytest
from fastapi.testclient import TestClient

import common
from app import main, presets

ROOT = common.ROOT
client = TestClient(main.app)
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
GLOBE_JS = (ROOT / "web" / "globe" / "globe.js").read_text(encoding="utf-8")
CATALOG = common.load_catalog()
ENTRIES = [e for _, e in common.iter_entries(CATALOG)]


def _function(src: str, name: str) -> str:
    """The source of `function name(...) {...}` (brace-matched)."""
    start = src.index(f"function {name}(")
    i, depth = src.index("{", start), 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[start:j + 1]
    raise AssertionError(name)


def _no_variable_names(code: str):
    for e in ENTRIES:
        for word in (e["name"], e["id"], e["id"].split("/")[1]):
            assert word not in code, f"{word!r} is hard-coded"
    for p in presets.load_presets().values():
        assert p["name"] not in code


# ---------------------------------------------------------------- context line
@pytest.mark.parametrize("pid", list(presets.load_presets()))
def test_trend_gives_every_part_of_the_context_line(pid):
    p = presets.load_presets()[pid]
    lens = client.get("/lenses").json()
    var = next(l for l in lens if l["id"] == p["lens"])["default_variable"]
    d = client.get("/trend", params={"variable": p.get("default_variable") or var,
                                     "bbox": ",".join(map(str, p["bbox"])), "lens": p["lens"]}).json()
    entry = next(e for e in ENTRIES if e["id"] == d["variable"])
    assert d["region_label"] == p["name"]                          # from presets.yml
    assert d["data_source"] == CATALOG["sources"][entry["short_name"]]   # from catalog.yml
    assert d["data_source"].startswith("NASA ")
    assert d["name"] == entry["name"] and d["dates"][0] < d["dates"][-1]


def test_every_catalog_collection_has_a_source_label():
    for e in ENTRIES:
        assert CATALOG["sources"].get(e["short_name"]), e["id"]


def test_context_line_is_hidden_until_a_result_and_built_only_from_the_response():
    assert re.search(r'<p id="contextLine"[^>]*\bhidden\b', INDEX)
    parts = _function(INDEX, "contextParts")
    for field in ("d.region_label", "d.name", "d.dates", "d.data_source", "d.lens", "lens.name"):
        assert field in parts
    _no_variable_names(parts + _function(INDEX, "showContext"))
    assert "line.hidden = !parts.length" in _function(INDEX, "showContext")
    # cleared with every empty/loading/error state, refilled with every successful result
    assert "showContext(null)" in _function(INDEX, "showState")
    assert "showContext(d)" in _function(INDEX, "run")


def test_custom_region_context_label_comes_from_the_server(monkeypatch, tmp_path):
    """A custom region (gridded data) is labelled by the server, not by page text."""
    assert "Custom region" not in INDEX
    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert '"region_label": region_name or "Custom region' in src


# ---------------------------------------------------------------- legend significance line
def _sig_text(m):
    """Python mirror of globe.js significanceText(), to check the wording on the real map JSON."""
    pct = m.get("percent_significant_fdr")
    if pct is None:
        return ""
    share = "Under 1%" if pct < 1 else ("Over 99%" if 99 < pct < 100 else f"{round(pct)}%")
    low = int(re.search(r"var LOW_SHARE = (\d+);", GLOBE_JS).group(1))
    return (f"{share} of cells show a statistically significant change after correction."
            + (" Not significant does not mean no change." if pct < low else ""))


def test_every_map_json_has_the_share_of_significant_cells():
    index = client.get("/maps/index.json").json()
    for v in index["variables"]:
        m = client.get("/maps/" + v["metadata"]).json()
        pct = m["percent_significant_fdr"]
        assert 0 <= pct <= 100
        assert round(100 * m["n_significant_fdr"] / m["n_cells_tested"], 2) == pytest.approx(pct, abs=0.01)
        text = _sig_text(m)
        assert text.endswith(("correction.", "no change.")) and "no trend" not in text.lower()


def test_legend_line_reads_the_json_and_is_hidden_without_it():
    fn = _function(GLOBE_JS, "significanceText")
    assert "m.percent_significant_fdr" in fn and "return '';" in fn
    assert "'Under 1%'" in fn and "Not significant does not mean no change." in fn
    assert "no trend" not in fn.lower()
    _no_variable_names(fn)
    assert "sig.hidden = true;" in GLOBE_JS                       # hidden until a variable is selected
    assert "t.sig.textContent = significanceText(m);" in GLOBE_JS and "t.sig.hidden = !t.sig.textContent;" in GLOBE_JS


@pytest.mark.parametrize("pct, expected", [
    (72.4, "72% of cells show a statistically significant change after correction."),
    (0.3, "Under 1% of cells show a statistically significant change after correction. "
          "Not significant does not mean no change."),
    (99.6, "Over 99% of cells show a statistically significant change after correction."),
])
def test_legend_wording(pct, expected):
    assert _sig_text({"percent_significant_fdr": pct}) == expected


# ---------------------------------------------------------------- header, cards, footer
def test_header_hero_cards_and_footer_follow_the_design_tokens():
    css = INDEX[:INDEX.index("</style>")]
    assert "--stage: #0B2530" in css and "--stage-2: #123C4A" in css
    assert "linear-gradient(90deg, var(--orange), var(--teal))" in css     # bottom edge line
    assert "opacity: .08" in css and "%233CE0D0" in css                    # contour pattern, cyan
    for lens in ("solar", "wind", "hydro", "farming"):
        assert f'#demos button[data-lens="{lens}"] {{ --accent: var(--lens-{lens});' in css
    assert "border-top: 4px solid var(--accent)" in css
    assert "grid-template-rows: auto auto 1fr auto" in css
    # no text below 14px anywhere in the page's own CSS
    for size in re.findall(r"font-size:\s*([\d.]+)(rem|px)", css):
        px = float(size[0]) * (16 if size[1] == "rem" else 1)
        assert px >= 14, size
    foot = re.search(r'<footer class="site-foot"[^>]*>\s*<p>(.*?)</p>', INDEX, re.S).group(1)
    assert foot == ("Regional screening only, not site-level analysis. Data: NASA MERRA-2, GPM IMERG, GLDAS. "
                    "See the README for methods and limitations.")
