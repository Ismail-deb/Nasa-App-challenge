"""The "Terrain map" mode of the globe (web/globe/globe.js): a second setup of the same Cesium viewer.
Config and text-level checks, no browser; tests/test_page_browser.py drives the offline fallback for real."""
import colorsys
import json
import re
import subprocess

import common

ROOT = common.ROOT
GLOBE_JS = (ROOT / "web" / "globe" / "globe.js").read_text(encoding="utf-8")
GLOBE_CSS = (ROOT / "web" / "globe" / "globe.css").read_text(encoding="utf-8")


def _config() -> dict:
    m = re.search(r"^  var GLOBE_CONFIG = (\{.*?\});$", GLOBE_JS, re.S | re.M)
    assert m, "globe.js must define GLOBE_CONFIG as plain JSON"
    return json.loads(m.group(1))


CFG = _config()
MAP = CFG["terrainMap"]


def _body(name: str) -> str:
    return GLOBE_JS.split(f"function {name}(")[1].split("\n  }\n")[0]


def _hue(css: str) -> float:
    r, g, b = (int(css[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


# ---------------------------------------------------------------- settings come from the config

def test_terrain_map_settings_are_read_from_the_config():
    assert MAP["pitchDeg"] == -40
    assert (MAP["exaggerationMin"], MAP["exaggerationMax"], MAP["exaggerationDefault"]) == (1, 4, 2)
    assert MAP["background"].upper() == "#0B2530"
    assert "var MAP = GLOBE_CONFIG.terrainMap;" in GLOBE_JS
    panel = _body("setupMapMode")
    assert "range.min = String(MAP.exaggerationMin); range.max = String(MAP.exaggerationMax); range.step = String(MAP.exaggerationStep);" in panel
    assert "'Terrain height'" in panel and "'Contours'" in panel and "'Top-down'" in panel and "'Whole US'" in panel
    assert "pitch = C.Math.toRadians(MAP.pitchDeg)" in _body("flyTilted")
    assert "MAP.minZoomM" in _body("mapLimits") and "MAP.maxZoomFactor" in _body("mapLimits")


def test_contour_spacing_adapts_to_the_camera_height():
    rows = MAP["contour"]["spacingByCameraHeight"]
    heights, steps = [r[0] for r in rows], [r[1] for r in rows]
    assert heights == sorted(heights) and steps == sorted(steps) and len(set(steps)) == len(steps)
    assert "MAP.contour.spacingByCameraHeight" in _body("contourSpacing")
    assert "contourSpacing(g ? g.height : Infinity)" in _body("updateSpacing")
    # the step is in true metres: the material divides the exaggeration back out
    assert "materialInput.height / max(tmExaggeration, 1.0)" in GLOBE_JS


def test_contour_and_ramp_colours_are_cyan_only():
    colours = [MAP["contour"]["color"], MAP["ramp"]["low"], MAP["ramp"]["high"], MAP["background"], MAP["baseColor"]]
    for c in colours:
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", c), c
        assert 170 <= _hue(c) <= 200, f"{c} is not cyan/teal (hue {_hue(c):.0f})"
    assert 0 <= MAP["ramp"]["alphaLow"] <= MAP["ramp"]["alphaHigh"] <= 0.5     # subtle, never hides the heatmap
    assert 0 <= MAP["underTrend"] < 0.5                                            # lines fade under trend cells
    mat = _body("makeMaterial")
    assert "color(c.color, c.alpha)" in mat and "color(r.low, r.alphaLow)" in mat and "color(r.high, r.alphaHigh)" in mat
    assert "TextureMagnificationFilter.NEAREST" in mat                            # heatmap cover: nearest neighbour


# ---------------------------------------------------------------- one viewer, two setups, no stale state

def test_terrain_map_reuses_the_one_viewer():
    assert GLOBE_JS.count("new C.Viewer(") == 1
    assert "state.setStage = function (s) { return s === 'map' ? enterMap(C, v) : exitMap(C, v); };" in GLOBE_JS


def test_entering_saves_and_leaving_restores_every_setting():
    enter, leave = _body("enterMap"), _body("exitMap")
    pairs = [
        ("skyAtmosphere.show = false", "skyAtmosphere.show = s.sky"),
        ("sun.show = false", "sun.show = s.sun"),
        ("moon.show = false", "moon.show = s.moon"),
        ("fog.enabled = false", "fog.enabled = s.fog"),
        ("showGroundAtmosphere = false", "showGroundAtmosphere = s.ground"),
        ("scene.backgroundColor = C.Color.fromCssColorString(MAP.background)", "scene.backgroundColor = s.background"),
        ("scene.globe.baseColor = C.Color.fromCssColorString(MAP.baseColor)", "scene.globe.baseColor = s.baseColor"),
        ("ctl.enableCollisionDetection = true", "ctl.enableCollisionDetection = s.collision"),
        ("tmap.offCamera = cam.changed.addEventListener", "tmap.offCamera(); tmap.offCamera = null;"),
        ("scene.globe.material = makeMaterial(C)", "scene.globe.material = undefined"),
        ("hideBase(v.imageryLayers.get(i))", "layer.show = true"),
        ("setTrendShow(v, s.trend)", "setTrendShow(v, s.trendShow)"),
    ]
    for on, off in pairs:
        assert on in enter, on
        assert off in leave, off
    assert "ctl.minimumZoomDistance = s.minZoom;" in leave and "ctl.maximumZoomDistance = s.maxZoom;" in leave
    assert "old.destroy()" in leave                                  # the material is freed
    assert "if (tmap.active) return applyMapRelief(C, v);" in _body("applyRelief")
    assert "applyRelief(C, v);" in leave                              # Earth's own height comes back


def test_mode_and_settings_persist():
    for key in ("estd.globe.stage", "estd.map.exaggeration", "estd.map.contours", "estd.map.trend"):
        assert f"'{key}'" in GLOBE_JS, key
    read = _body("readMapSettings")
    assert "store(KEY_MAP_CONTOURS) !== 'off'" in read and "store(KEY_MAP_TREND) !== 'off'" in read
    assert "store(KEY_STAGE) === 'map' ? 'map' : 'earth'" in read
    assert "store(KEY_STAGE, 'map')" in _body("enterMap") and "store(KEY_STAGE, 'earth')" in _body("exitMap")
    assert "store(KEY_MAP_EXAGGERATION, String(tmap.exaggeration))" in _body("setupMapMode")
    assert "Math.min(MAP.exaggerationMax, Math.max(MAP.exaggerationMin, n))" in _body("clampMapExaggeration")


def test_offline_or_no_token_disables_terrain_map_and_keeps_earth():
    assert "var MAP_OFFLINE_NOTE = 'Terrain map needs the Cesium token and an internet connection';" in GLOBE_JS
    assert "return saved === 'map' && mode === 'terrain' ? 'map' : 'earth';" in _body("chooseStage")
    bar = _body("syncStageBar")
    assert "state.mode === 'terrain' && !!globe.terrain" in bar and "ui.mapBtn.disabled = !can;" in bar
    assert "if (tmap.active || !state.mapAvailable || v.isDestroyed()) return false;" in _body("enterMap")
    assert "if (tmap.active && !v.isDestroyed()) exitMap(C, v);" in _body("goOffline")


def test_mode_switch_and_chips_are_styled_in_the_existing_system():
    assert ".stage-modes button[aria-pressed=\"true\"]" in GLOBE_CSS and ".map-chip" in GLOBE_CSS
    assert 'data-stage="earth"' in GLOBE_JS and 'data-stage="map"' in GLOBE_JS and ">Terrain map<" in GLOBE_JS


# ---------------------------------------------------------------- the Cesium token never lands in git

def test_no_cesium_token_in_tracked_files():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    assert "frontend/config.local.js" not in files
    jwt = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}")       # Cesium ion tokens are JWTs
    for name in files:
        if not name or name.startswith(("data/", "frontend/vendor/")):
            continue
        p = ROOT / name
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        assert not jwt.search(text), f"a token-like string is in {name}"
