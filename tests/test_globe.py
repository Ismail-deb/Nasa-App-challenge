"""The optional globe view (web/globe/, vendored Cesium in frontend/vendor/cesium): text-level and
server checks. tests/test_page_browser.py drives it in a real browser."""
import re
import subprocess

import pytest
from fastapi.testclient import TestClient

import common
from app import main, presets

ROOT = common.ROOT
GLOBE_JS = (ROOT / "web" / "globe" / "globe.js").read_text(encoding="utf-8")
GLOBE_CSS = (ROOT / "web" / "globe" / "globe.css").read_text(encoding="utf-8")
PAGE = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
VENDOR = ROOT / "frontend" / "vendor" / "cesium"
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")   # what an ion token looks like


# ---------------------------------------------------------------- regions: one source only

def test_globe_regions_come_from_the_presets_endpoint_only():
    assert "getJson('/presets')" in GLOBE_JS
    numbers = {float(x) for x in re.findall(r"(?<![\w.#])-?\d+(?:\.\d+)?", GLOBE_JS)}
    coords = {float(c) for p in presets.load_presets().values() for c in p["bbox"]}
    assert not numbers & coords, f"globe.js hardcodes preset coordinates: {sorted(numbers & coords)}"
    assert "var b = p.bbox, w = b[0], s = b[1], e = b[2], n = b[3];" in GLOBE_JS


def test_a_region_click_runs_the_demo_button():
    assert "document.querySelector('#demos button[data-id=\"' + p.id + '\"]')" in GLOBE_JS
    assert "button.click();" in GLOBE_JS
    # boxes first; then the US outline; then a map cell (also inside the region already chosen)
    click = GLOBE_JS.split("handler.setInputAction(function (c) {")[1].split("C.ScreenSpaceEventType.LEFT_CLICK")[0]
    assert "if (info && !cell) { state.selectPreset(info.preset.id); return; }" in click
    assert click.index("selectPreset") < click.index("outlineAt(v, c.position)") < click.index("showCell(cell")
    assert "var cell = (!info || info.preset.id === globe.current) ? cellAtScreen(C, v, c.position) : null;" in click


# ---------------------------------------------------------------- token

def _repo_files():
    """Tracked files plus new files git would add (i.e. everything that is not ignored)."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [ROOT / p for p in out.split("\0") if p and (ROOT / p).is_file()]


def test_the_token_file_is_git_ignored_and_never_committed():
    files = _repo_files()
    assert "frontend/config.local.js" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ROOT / "frontend" / "config.local.js" not in files
    example = (ROOT / "frontend" / "config.local.example.js").read_text(encoding="utf-8")
    assert re.search(r'^window\.CESIUM_ION_TOKEN = "";$', example, re.M)


def test_no_token_string_in_any_committed_file():
    """No ion-token-like string in our files (the vendored Cesium.js ships Cesium's own public demo
    token, so the vendor folder is skipped here), and the local token, if there is one, is in no
    committed file at all. The token itself is never printed: only file names are reported."""
    files = _repo_files()
    ours = [p for p in files if VENDOR not in p.parents]
    with_jwt = [str(p.relative_to(ROOT)) for p in ours
                if JWT.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert not with_jwt, f"token-like strings in: {with_jwt}"
    local = ROOT / "frontend" / "config.local.js"
    if local.is_file():
        m = re.search(r'CESIUM_ION_TOKEN\s*=\s*"([^"]*)"', local.read_text(encoding="utf-8"))
        secret = m.group(1).strip() if m else ""
        if len(secret) >= 8:
            leaked = [str(p.relative_to(ROOT)) for p in files
                      if secret in p.read_text(encoding="utf-8", errors="ignore")]
            del secret
            assert not leaked, f"the local token is in: {leaked}"


# ---------------------------------------------------------------- offline fallback

def test_missing_token_file_serves_an_empty_token(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "LOCAL_CONFIG", tmp_path / "config.local.js")       # does not exist
    r = TestClient(main.app).get("/frontend/config.local.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    assert r.text == main.NO_TOKEN_JS and '|| ""' in r.text


def test_offline_mode_is_chosen_without_a_token():
    body = GLOBE_JS.split("function chooseMode(token, online) {")[1].split("\n  }")[0]
    assert "token.trim() !== ''" in body and "online !== false" in body and "'terrain' : 'offline'" in body
    assert "var mode = chooseMode(token, navigator.onLine);" in GLOBE_JS
    assert "if (mode === 'terrain') loadTerrain(C, v); else showOfflineNote();" in GLOBE_JS
    # terrain failure or timeout falls back to the ellipsoid with the same note
    assert ".catch(function () { goOffline(C, v); });" in GLOBE_JS and "TERRAIN_TIMEOUT_MS)" in GLOBE_JS
    assert "var OFFLINE_NOTE = 'Globe running in offline mode, no terrain';" in GLOBE_JS
    assert "Assets/Textures/NaturalEarthII" in GLOBE_JS                       # bundled imagery, never blank


# ---------------------------------------------------------------- cannot break the page

def test_globe_is_optional_quiet_and_loaded_last():
    assert PAGE.index("/static/guide/guide.js") < PAGE.index('<script src="/static/globe/globe.js"></script>')
    assert '<link rel="stylesheet" href="/static/globe/globe.css">' in PAGE
    assert not re.search(r"console\.\w+\(", GLOBE_JS)
    assert "http://" not in GLOBE_JS and "https://" not in GLOBE_JS            # Cesium is vendored, no CDN
    assert "prefers-reduced-motion: reduce" in GLOBE_JS and "globe.spinning = !reduced();" in GLOBE_JS
    assert "#viewToggle" in GLOBE_CSS


def test_cesium_is_vendored_and_served():
    if not (VENDOR / "Cesium.js").is_file():
        pytest.skip("Cesium not vendored in this checkout")
    for rel in ("Cesium.js", "Widgets/widgets.css", "Assets/Textures/NaturalEarthII/tilemapresource.xml"):
        assert (VENDOR / rel).is_file(), rel
    for sub in ("Workers", "ThirdParty", "Assets"):
        assert (VENDOR / sub).is_dir(), sub
    c = TestClient(main.app)
    assert c.get("/vendor/cesium/Widgets/widgets.css").status_code == 200
    assert c.get("/vendor/cesium/Assets/Textures/NaturalEarthII/tilemapresource.xml").status_code == 200
