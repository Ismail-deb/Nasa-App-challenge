"""Globe relief, camera, US outline, cell readout and region labels (web/globe/globe.js): config and
text-level checks, plus the cell decoding checked against the documented layout of a real
data/maps/*_cells.json. No browser needed; tests/test_page_browser.py drives the same code for real."""
import json
import math
import re

import pytest
from fastapi.testclient import TestClient

import common
from app import main, presets

ROOT = common.ROOT
MAPS = ROOT / "data" / "maps"
GLOBE_JS = (ROOT / "web" / "globe" / "globe.js").read_text(encoding="utf-8")
GLOBE_CSS = (ROOT / "web" / "globe" / "globe.css").read_text(encoding="utf-8")


def _config() -> dict:
    m = re.search(r"^  var GLOBE_CONFIG = (\{.*?\});$", GLOBE_JS, re.S | re.M)
    assert m, "globe.js must define GLOBE_CONFIG as plain JSON"
    return json.loads(m.group(1))


CFG = _config()


def _body(name: str) -> str:
    return GLOBE_JS.split(f"function {name}(")[1].split("\n  }\n")[0]


# ---------------------------------------------------------------- terrain settings come from the config

def test_terrain_settings_are_read_from_the_config():
    t = CFG["terrain"]
    assert t["timeoutMs"] == 8000 and t["assetId"] == 1
    assert (t["exaggerationMin"], t["exaggerationMax"], t["exaggerationDefault"]) == (1, 3, 1.5)
    assert t["exaggerationMin"] <= t["exaggerationDefault"] <= t["exaggerationMax"] and t["exaggerationStep"] > 0
    assert "var TERRAIN_TIMEOUT_MS = GLOBE_CONFIG.terrain.timeoutMs;" in GLOBE_JS
    load = _body("loadTerrain")
    assert "fromIonAssetId(t.assetId, {requestVertexNormals: t.requestVertexNormals})" in load
    assert "scene.globe.maximumScreenSpaceError = GLOBE_CONFIG.terrain.maximumScreenSpaceError;" in GLOBE_JS
    assert "scene.requestRenderMode = !!GLOBE_CONFIG.render.requestRenderMode;" in GLOBE_JS
    # the slider's range is the config's
    panel = _body("setupTerrainPanel")
    assert "range.min = String(t.exaggerationMin); range.max = String(t.exaggerationMax); range.step = String(t.exaggerationStep);" in panel
    assert "'Terrain height'" in panel and "'Terrain'" in panel and "'Top-down'" in panel


def test_exaggeration_is_applied_only_with_real_terrain():
    relief = _body("applyRelief")
    assert "v.scene.verticalExaggeration = on ? globe.exaggeration : 1;" in relief
    assert "var on = !!globe.terrain && globe.terrainOn;" in relief
    assert "updateBoxHeights(C);" in relief                 # boxes rise with the relief: still clickable
    assert "BOX_HEIGHT * (globe.terrain && globe.terrainOn ? globe.exaggeration : 1)" in GLOBE_JS


def test_camera_tilt_collision_and_zoom_limits():
    cam = CFG["camera"]
    assert -50 <= cam["pitchDeg"] <= -30
    assert 0 < cam["minZoomM"] < 10000 and 17000000 < cam["maxZoomM"] <= 40000000    # the first view stays allowed
    for line in ("ctl.enableCollisionDetection = true;", "ctl.minimumZoomDistance = cam.minZoomM;",
                 "ctl.maximumZoomDistance = cam.maxZoomM;"):
        assert line in GLOBE_JS
    fly = _body("flyTilted")
    assert "C.Math.toRadians(GLOBE_CONFIG.camera.pitchDeg)" in fly and "flyToBoundingSphere" in fly
    assert "flyTilted(C, v, p.bbox," in GLOBE_JS                    # a preset
    assert "flyTilted(C, v, globe.outline.bbox)" in GLOBE_JS        # the whole US, from the outline's extent
    top = _body("topDown")
    assert "pitch: -C.Math.PI_OVER_TWO" in top


def test_software_rendering_gets_fewer_pixels_and_coarser_tiles():
    r = CFG["render"]
    assert 0.5 <= r["softwareResolutionScale"] < 1 and r["softwareMaximumScreenSpaceError"] >= CFG["terrain"]["maximumScreenSpaceError"]
    assert "swiftshader|llvmpipe" in _body("softwareRenderer")
    # request render mode must not stop the idle spin
    assert "if (globe.spinning || performance.now() < globe.renderUntil) v.scene.requestRender();" in GLOBE_JS
    # and a camera flight only moves while drawn: every flight keeps drawing for its length
    assert "keepDrawing(v, reduced() ? 0 : 2);" in _body("flyTilted") and "keepDrawing(v, reduced() ? 0 : 1);" in _body("topDown")


# ---------------------------------------------------------------- the offline fallback is untouched

def test_offline_fallback_is_still_chosen_without_a_token():
    assert "var mode = chooseMode(token, navigator.onLine);" in GLOBE_JS
    assert "if (mode === 'terrain') loadTerrain(C, v); else showOfflineNote();" in GLOBE_JS
    assert ".catch(function () { goOffline(C, v); });" in GLOBE_JS
    assert "var OFFLINE_NOTE = 'Globe running in offline mode, no terrain';" in GLOBE_JS
    # no terrain switch or slider in offline mode: nothing to stretch there
    assert "var can = state.mode === 'terrain';" in GLOBE_JS and "r.sw.hidden = r.height.hidden = !can;" in GLOBE_JS


# ---------------------------------------------------------------- the switch and the slider are saved

def test_terrain_switch_and_exaggeration_persist():
    assert "var KEY_TERRAIN = 'estd.globe.terrain';" in GLOBE_JS
    assert "var KEY_EXAGGERATION = 'estd.globe.exaggeration';" in GLOBE_JS
    assert "store(KEY_TERRAIN, yes ? 'on' : 'off');" in GLOBE_JS
    assert "store(KEY_EXAGGERATION, String(globe.exaggeration));" in GLOBE_JS
    read = _body("readSettings")
    assert "terrainOn: store(KEY_TERRAIN) !== 'off'" in read and "clampExaggeration(store(KEY_EXAGGERATION))" in read
    # storage may be blocked: then the defaults
    assert "} catch (e) { /* storage blocked */ }" in _body("store")
    assert "return t.exaggerationDefault;" in _body("clampExaggeration")


# ---------------------------------------------------------------- heatmap on terrain

def test_heatmap_stays_nearest_neighbour_and_on_top():
    assert "minificationFilter: C.TextureMinificationFilter.NEAREST" in GLOBE_JS
    assert "v.imageryLayers.raiseToTop(trend.layer)" in GLOBE_JS


# ---------------------------------------------------------------- cell readout: the documented layout

def _decode(cells, lon, lat):
    """The layout the file's "decode" field documents (and globe.js decodeCell follows)."""
    row = round((cells["lat"][0] - lat) / abs(cells["lat"][1] - cells["lat"][0]))
    col = round((lon - cells["lon"][0]) / abs(cells["lon"][1] - cells["lon"][0]))
    if not (0 <= row < cells["nlat"] and 0 <= col < cells["nlon"]):
        return None
    idx = row * cells["nlon"] + col
    flag = cells["flag"][idx]
    if flag == "-":
        return None
    k = idx - cells["flag"][:idx].count("-")
    return {"slope": cells["slope"][k], "p": cells["p"][k], "significant": flag == "1"}


def _cells(key="T2M"):
    path = MAPS / f"{key}_cells.json"
    if not path.is_file():
        pytest.skip("data/maps not in this checkout")
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_decode_field_documents_the_layout_globe_js_uses():
    for path in MAPS.glob("*_cells.json"):
        d = json.loads(path.read_text(encoding="utf-8"))["decode"]
        for words in ("row-major", "row 0 = north", "row * nlon + col", "'-' = masked", "'1' = significant after FDR",
                      "'0' = not significant", "k-th non-'-' character of flag is slope[k], p[k]", "raw"):
            assert words in d, (path.name, words)
    dec = _body("decodeCell")
    assert "var idx = row * cells.nlon + col, f = cells.flag.charAt(idx);" in dec
    assert "if (f !== '0' && f !== '1') return null;" in dec and "significant: f === '1'" in dec
    assert "at[i] = flag.charAt(i) === '-' ? -1 : k++;" in _body("cellIndex")


def test_a_known_cell_decodes_to_its_documented_values():
    c = _cells("T2M")
    # row 17, col 63: 41.5 N, 85.625 W (northern Indiana)
    assert c["lat"][17] == 41.5 and c["lon"][63] == -85.625
    assert _decode(c, -85.625, 41.5) == {"slope": 0.424, "p": 0.0043, "significant": True}
    assert _decode(c, c["lon"][0], c["lat"][0]) is None          # the north-west corner: Pacific, masked
    assert _decode(c, 10.0, 10.0) is None                         # outside the US grid
    assert c["slope_units"] == "°C per decade"
    # the card: change in the file's units, raw p, FDR verdict, cell size
    card = _body("showCell")
    for part in ("fmtSlope(cell.slope) + ' ' + cell.units", "String(cell.p) + ' (raw)'", "'Significant'", "'Grid cell'"):
        assert part in card, part
    assert "if (ev.key === 'Escape') closeCell();" in GLOBE_JS


# ---------------------------------------------------------------- the US outline

def test_the_outline_is_served_and_drawn_with_its_tooltip():
    r = TestClient(main.app).get("/maps/us_outline.geojson")
    assert r.status_code == 200 and r.json()["features"][0]["properties"]["name"] == "Contiguous United States"
    assert "var OUTLINE_TIP = ['Contiguous United States.', 'Click for a tilted view of the whole country.'];" in GLOBE_JS
    out = _body("setupOutline")
    assert "getJson(MAPS_URL + file)" in out and "index.boundaries.file" in out and "clampToGround: ground" in out
    assert "width: 2" in out and "C.Color.fromCssColorString(CYAN)" in out


# ---------------------------------------------------------------- region labels

def test_only_the_crowded_label_waits_for_zoom():
    cfg = CFG["labels"]
    centres = {k: ((p["bbox"][0] + p["bbox"][2]) / 2, (p["bbox"][1] + p["bbox"][3]) / 2,
                   (p["bbox"][2] - p["bbox"][0]) * (p["bbox"][3] - p["bbox"][1])) for k, p in presets.load_presets().items()}
    near = {a for a, (x, y, area) in centres.items()
            if any(o != a and oa > area and math.hypot(ox - x, oy - y) < cfg["clearDeg"] for o, (ox, oy, oa) in centres.items())}
    assert near == {"central_valley"}
    assert "distanceDisplayCondition: info.near" in GLOBE_JS
    assert "info.box.label.distanceDisplayCondition = undefined;" in GLOBE_JS          # hovered: always labelled
