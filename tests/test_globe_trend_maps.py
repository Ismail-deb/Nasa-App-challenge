"""The trend-map layer on the globe (data/maps/ -> /maps/ route -> web/globe/globe.js): file, server and
text-level checks, no browser needed."""
import json
import re

import pytest
import yaml
from fastapi.testclient import TestClient

import common
from app import main

ROOT = common.ROOT
MAPS = ROOT / "data" / "maps"
GLOBE_JS = (ROOT / "web" / "globe" / "globe.js").read_text(encoding="utf-8")
TREND_JS = GLOBE_JS.split("// ------------------------------------------------------------------ per-cell trend maps")[1]


def _index():
    if not (MAPS / "index.yml").is_file():
        pytest.skip("data/maps not in this checkout")
    with open(MAPS / "index.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _meta(entry):
    return json.loads((MAPS / entry["metadata"]).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the files

def test_every_variable_has_its_png_json_and_cells():
    idx = _index()
    assert idx["variables"]
    for v in idx["variables"]:
        for f in (v["image"], v["metadata"], v["cells"]):
            assert (MAPS / f).is_file(), f
        m = _meta(v)
        assert m["key"] == v["key"] and m["image"] == v["image"] and m["cells"] == v["cells"]
        for k in ("west", "south", "east", "north"):
            assert isinstance(m["bounds"][k], (int, float))
        assert m["scale"]["min"] < m["scale"]["max"]
        assert m["description"] and m["method"]
    assert (MAPS / idx["boundaries"]["file"]).is_file()


def test_map_files_are_not_git_ignored():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "!data/maps/" in gi


# ---------------------------------------------------------------- the layer config comes from the JSON

def test_layer_reads_bounds_and_scale_from_the_json_not_from_code():
    assert "var b = meta.bounds;" in TREND_JS
    assert "C.Rectangle.fromDegrees(b.west, b.south, b.east, b.north)" in TREND_JS
    assert "url: MAPS_URL + meta.image" in TREND_JS
    assert "fmt(m.scale.min)" in TREND_JS and "fmt(m.scale.max)" in TREND_JS
    assert "getJson(MAPS_URL + 'index.json')" in TREND_JS and "getJson(MAPS_URL + e.metadata)" in TREND_JS
    # no bound or scale number from any map JSON is written into the JS
    numbers = {float(x) for x in re.findall(r"(?<![\w.#])-?\d+(?:\.\d+)?", GLOBE_JS)}
    data_numbers = set()
    for v in _index()["variables"]:
        m = _meta(v)
        data_numbers |= {float(x) for x in m["bounds"].values()}
        data_numbers |= {float(m["scale"]["min"]), float(m["scale"]["max"])}
    assert not numbers & data_numbers, f"globe.js hardcodes map numbers: {sorted(numbers & data_numbers)}"


def test_heatmap_is_drawn_nearest_neighbour():
    body = TREND_JS.split("function layerFor(C, meta) {")[1].split("\n  }")[0]
    assert "minificationFilter: C.TextureMinificationFilter.NEAREST" in body
    assert "magnificationFilter: C.TextureMagnificationFilter.NEAREST" in body
    assert "C.SingleTileImageryProvider.fromUrl(cfg.url, {rectangle: cfg.rectangle}), cfg.options)" in TREND_JS
    assert "var MAP_OPACITY = 0.85;" in TREND_JS and "op.type = 'range'" in TREND_JS


def test_experimental_layers_are_hidden_by_default():
    assert "showExperimental: false" in TREND_JS
    assert "experimental: !!(m.caveat && String(m.caveat).trim())" in TREND_JS
    assert "row.hidden = x.experimental && !trend.showExperimental;" in TREND_JS
    assert "'Show experimental layers (known data artefacts)'" in TREND_JS
    assert "t.caveat.hidden = !x.experimental;" in TREND_JS
    # the default layer is temperature, and it is not experimental
    assert "var DEFAULT_MAP = 'T2M';" in TREND_JS
    by_key = {v["key"]: _meta(v) for v in _index()["variables"]}
    assert "T2M" in by_key and not by_key["T2M"].get("caveat")
    assert by_key["SoilMoi0_10cm_inst"].get("caveat") and by_key["Evap_tavg"].get("caveat")


def test_legend_wording():
    assert "'Change per decade'" in TREND_JS
    assert ("'Faded cells are not statistically significant (FDR 10%): we can\\u2019t tell their ' +\n"
            "                   'change from natural variation.'") in TREND_JS
    assert "no trend" not in GLOBE_JS.lower()
    assert "t.method.textContent = m.method" in TREND_JS and "'How this map was made'" in TREND_JS


def test_a_failed_map_load_leaves_the_globe_working():
    assert ".catch(function () { trendNote(MAPS_NOTE); });" in TREND_JS
    assert "if (trend.layer === layer) trendNote(MAPS_NOTE);" in TREND_JS
    assert "quiet(layer.errorEvent);" in TREND_JS
    assert not re.search(r"console\.\w+\(", GLOBE_JS)
    # the regions are set up before, and independently of, the trend maps
    assert GLOBE_JS.index("setupPointer(C, v);\n    setupTrendMaps(C, v);") > 0


# ---------------------------------------------------------------- the /maps/ route

def test_maps_route_serves_the_map_files():
    idx = _index()
    c = TestClient(main.app)
    r = c.get("/maps/index.json")
    assert r.status_code == 200 and r.json()["variables"] == idx["variables"]
    v = idx["variables"][0]
    r = c.get("/maps/" + v["image"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    for f in (v["metadata"], v["cells"]):
        r = c.get("/maps/" + f)
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
        r.json()
    r = c.get("/maps/" + idx["boundaries"]["file"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/geo+json")


@pytest.mark.parametrize("path", [
    "/maps/index.yml", "/maps/missing.png", "/maps/../series/x.json", "/maps/..%2Fseries%2Fx.json",
    "/maps/%2E%2E/catalog.yml", "/maps/..%5Ccatalog.yml", "/maps/sub/T2M.png", "/maps/.gitignore",
    "/maps/T2M.py",
])
def test_maps_route_serves_nothing_else(path):
    r = TestClient(main.app).get(path)
    assert r.status_code == 404, path


def test_maps_route_rejects_other_data_files(tmp_path, monkeypatch):
    maps = tmp_path / "data" / "maps"
    maps.mkdir(parents=True)
    (tmp_path / "data" / "secret.json").write_text("{}")
    (maps / "ok.json").write_text("{}")
    monkeypatch.setattr(main, "MAPS_DIR", maps)
    c = TestClient(main.app)
    assert c.get("/maps/ok.json").status_code == 200
    assert c.get("/maps/..%2Fsecret.json").status_code == 404
    assert c.get("/maps/index.json").status_code == 404           # no index.yml there
