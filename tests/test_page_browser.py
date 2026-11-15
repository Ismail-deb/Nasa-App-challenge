"""The page driven in a real (headless) browser that is already on the machine: Edge, Chrome or
Chromium. No extra packages. Skipped when no such browser is found, or with NO_BROWSER_TESTS=1.

Each test opens tests/browser/<name>.html, which loads the real page in an iframe, clicks through
it and posts what it saw back to this process. Uses the committed preset series in data/series/.
"""
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response

import common
from app import lenses, main, presets

HARNESS = Path(__file__).parent / "browser"
WAIT_SECONDS = 90
# the only message allowed after a preset click: the chart library comes from a CDN, so offline there is no chart
NO_CHART = "The chart library could not be loaded (check the internet connection); results are shown below."


def _find_browser() -> str | None:
    if os.environ.get("NO_BROWSER_TESTS"):
        return None
    candidates = [os.environ.get("BROWSER_BIN")]
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates += [rf"{base}\Microsoft\Edge\Application\msedge.exe",
                           rf"{base}\Google\Chrome\Application\chrome.exe"]
    candidates += [shutil.which(n) for n in ("msedge", "microsoft-edge", "google-chrome", "chrome",
                                             "chromium", "chromium-browser")]
    candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return next((c for c in candidates if c and Path(c).exists()), None)


@pytest.fixture(scope="module")
def site():
    """The real app on a free local port, plus the harness pages and a place to post results."""
    browser = _find_browser()
    if not browser:
        pytest.skip("no Edge/Chrome/Chromium found (or NO_BROWSER_TESTS is set)")
    results, done, mode = {}, {}, {"guide": "normal"}
    outer = FastAPI()
    config = common.ROOT / "web" / "guide" / "config.js"

    @outer.post("/__harness/mode/{name}")
    def set_mode(name: str):
        mode["guide"] = name
        return {"ok": True}

    @outer.get("/static/guide/config.js")
    def guide_config():
        """The guide's config, or a missing / broken one, to check that the page survives it."""
        js = config.read_text(encoding="utf-8")
        if mode["guide"] == "missing":
            return Response(status_code=404)
        if mode["guide"] == "broken":
            js = 'const GUIDE_NAME = "X"; const GUIDE_STEPS = null; const GUIDE_TIPS = 5;'
        if mode["guide"] == "nostorage":
            js = ("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked'); }});\n" + js)
        return Response(js, media_type="text/javascript", headers=main.NO_CACHE)

    @outer.get("/frontend/config.local.js")
    def no_token():
        """Never the real token in tests: the globe always sees an empty one (offline mode)."""
        return Response(main.NO_TOKEN_JS, media_type="text/javascript", headers=main.NO_CACHE)

    @outer.get("/__harness/{name}.html")
    def page(name: str):
        return FileResponse(HARNESS / f"{name}.html", headers=main.NO_CACHE)

    @outer.post("/__harness/result/{name}")
    async def result(name: str, request: Request):
        results[name] = await request.json()
        done.setdefault(name, threading.Event()).set()
        return {"ok": True}

    outer.mount("/", main.app)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(outer, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    assert server.started, "test server did not start"

    def run(name: str, profile: Path, lang: str = "de-DE", size: str = "1400,950",
            page: str | None = None, extra: tuple = ()) -> dict:
        """Open a harness page in a fresh browser profile and return what it posted as `name`."""
        done[name] = threading.Event()
        results.pop(name, None)
        mode["guide"] = "normal"
        proc = subprocess.Popen(
            [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--lang={lang}", f"--user-data-dir={profile}", f"--window-size={size}",
             # --dump-dom makes the browser exit by itself, once the (virtual) time budget is used up
             f"--virtual-time-budget={WAIT_SECONDS * 1000}", "--dump-dom", *extra,
             f"http://127.0.0.1:{port}/__harness/{page or name + '.html'}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            assert done[name].wait(WAIT_SECONDS), f"the browser never reported back for {name}"
        finally:
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if os.environ.get("HARNESS_DUMP"):                 # debugging aid: keep what the browser reported
            Path(os.environ["HARNESS_DUMP"], f"{name}.json").write_text(json.dumps(results[name], indent=1))
        return results[name]

    yield run
    server.should_exit = True
    thread.join(10)


def test_every_preset_sets_all_four_bounds_lens_and_variable_in_any_order_with_comma_decimals(site, tmp_path):
    """Step 0 bug report: after a preset click the South field kept "31,3". Every preset, in every
    order (all 24 orders of the 4 presets, so every preset follows every other one), with all four
    fields first filled with comma-decimal text as a comma-locale user would type it."""
    out = site("presets", tmp_path / "profile")
    assert out["errors"] == [], out["errors"]
    wanted = presets.load_presets()
    assert out["n_buttons"] == len(wanted) == 4
    assert len(out["clicks"]) == 24 * 4
    for c in out["clicks"]:
        p = wanted[c["id"]]
        assert c["before"] == ["12,5", "31,3", "-7,25", "44,0"]          # what was "typed" before the click
        assert [float(x) for x in c["fields"]] == [float(x) for x in p["bbox"]], c
        assert not any("," in x for x in c["fields"]), c                # written back with dots
        assert c["lens"] == p["lens"], c
        assert c["variable"] in lenses.variables(p["lens"]), c
        assert c["err"] in ("", NO_CHART), c                            # no "not available" message
        assert c["card"], c                                             # a result card was shown
    # typed comma decimals are read as numbers: the Central Valley box typed with commas is the preset
    assert out["typed"]["err"] in ("", NO_CHART) and "California Central Valley" in out["typed"]["card"]
    assert out["typed"]["fields_after_change"] == ["-122.6", "35", "-118.8", "40.6"]      # dots, as numbers
    # a custom region without the full dataset says so (only when the gridded files are absent here)
    if not any(common.PROCESSED_DIR.glob("*.nc")):
        assert "Custom regions need the full dataset" in out["custom"]["err"]
        assert "only available on the machine that has it" in out["custom"]["err"]


# ---------------------------------------------------------------- the guide

def _guide_config():
    from test_guide import NAME, STEPS, TIPS
    return NAME, STEPS, TIPS


def _said(text: str, name: str) -> str:
    return text.replace("{name}", name)


@pytest.fixture(scope="module")
def guide_run(site, tmp_path_factory):
    out = site("guide", tmp_path_factory.mktemp("guide") / "profile")
    assert out["errors"] == [], out["errors"]          # nothing thrown, nothing in the console, at any point
    return out


def test_first_visit_starts_the_tutorial_and_every_step_highlights_its_element(guide_run):
    name, steps, _ = _guide_config()
    out = guide_run
    assert out["name"] == name and out["firstVisitStarted"]
    assert [s["id"] for s in out["steps"]] == [s["id"] for s in steps] and len(steps) == 7
    for i, (seen, step) in enumerate(zip(out["steps"], steps)):
        assert seen["spoken"] == seen["typed"] == _said(step["text"], name), seen   # typed out completely
        assert seen["progress"] == f"Step {i + 1} of 7"
        assert seen["targetVisible"] and seen["spotShown"] and seen["spotOnTarget"] and seen["targetInView"], seen
        assert seen["stateAtStart"] == "talking" and seen["typedAtStart"] != seen["typed"], seen   # typewriter
        assert seen["stateAfter"] == "pointing" and seen["tilt"].endswith("deg"), seen
        assert seen["skipShown"] and seen["backShown"] == (i > 0) and seen["focusOnNext"], seen
        assert seen["next"] == ("Finish" if i == 6 else "Next")
    assert name in out["steps"][0]["spoken"]                                # introduces itself by name
    assert not any(seen["bubbleCoversTarget"] for seen in out["steps"])     # never on top of what it explains
    after = out["afterFinish"]
    assert not after["bubbleOpen"] and after["spotHidden"] and after["state"] == "idle"
    assert after["idleAnimation"] == "guide-bob" and after["guideShown"] and after["cardShown"]
    assert after["seen"] == "1"


def test_header_controls_are_named_after_the_guide(guide_run):
    name, _, _ = _guide_config()
    after = guide_run["afterFinish"]
    assert after["toggle"] == f"{name}: on" and after["pressed"] == "true"
    assert after["replay"] == f"Replay with {name}"
    assert after["avatarLabel"].startswith(name)


def test_second_visit_has_no_tutorial_and_the_toggle_is_remembered(guide_run):
    name, _, _ = _guide_config()
    out = guide_run
    assert out["secondVisit"] == {"bubbleOpen": False, "guideShown": True, "toggle": f"{name}: on"}
    assert out["off"] == {"toggle": f"{name}: off", "pressed": "false", "guideShown": False, "stored": "off"}
    assert out["offReload"] == {"toggle": f"{name}: off", "guideShown": False, "bubbleOpen": False,
                                "tipStillAnswers": True, "hiddenAgainAfterClose": True}
    assert out["replay"] == {"open": True, "progress": "Step 1 of 7", "toggle": f"{name}: on",
                             "stored": "on", "skipped": True}


def test_question_mark_tips_make_the_guide_explain(guide_run):
    name, _, tips = _guide_config()
    out = guide_run
    assert set(out["tips"]) == set(tips)
    for key, seen in out["tips"].items():
        assert seen["found"] and seen["shown"] and seen["opened"], (key, seen)
        assert seen["label"] == f"Ask {name} to explain: {tips[key]['label']}"
        assert seen["spoken"] == seen["typed"] == _said(tips[key]["text"], name)
        assert seen["stateAtStart"] == "talking" and seen["stateAfter"] == "pointing"
        assert seen["closeShown"] and not seen["nextShown"] and seen["spotHidden"]
        assert seen["closedByEscape"] and seen["focusBack"]              # keyboard: Esc closes, focus returns
    assert out["greeting"]["open"] and name in out["greeting"]["spoken"] and out["greeting"]["closed"]


def test_narrow_window_collapses_the_guide_to_a_small_icon(guide_run):
    out = guide_run
    assert out["afterFinish"]["avatarWidth"] >= 70                       # full size in a wide window
    narrow = out["narrow"]
    assert narrow["width"] <= 400 and narrow["avatarWidth"] <= 48 and not narrow["bubbleOpen"]
    assert narrow["bodyPadding"] == "60px"                               # room to scroll content clear of the icon
    assert len(narrow["steps"]) == 7
    for seen in narrow["steps"]:
        assert seen["spotShown"] and seen["spotOnTarget"] and seen["targetInView"], seen
        # the bubble stays off what it explains, unless that is taller than the window has room for
        assert not seen["bubbleCoversTarget"] or not seen["targetFits"], seen
    assert not next(s for s in narrow["steps"] if s["id"] == "chart")["bubbleCoversTarget"]


def test_page_works_without_the_guide(guide_run):
    f = guide_run["failures"]
    for mode in ("missing", "broken"):                                    # config.js 404 / nonsense
        assert f[mode]["card"] and f[mode]["title"], f[mode]
        assert not f[mode]["guide"] and f[mode]["controls"] == 0 and f[mode]["tipsShown"] == 0, f[mode]
    assert f["nostorage"]["card"] and f["nostorage"]["guide"]             # localStorage blocked: still fine


def test_reduced_motion_means_no_animation_and_instant_text(site, tmp_path):
    name, steps, _ = _guide_config()
    out = site("guide_reduced", tmp_path / "profile", page="guide.html?reduced=1",
               extra=("--force-prefers-reduced-motion",))
    assert out["errors"] == [], out["errors"]
    r = out["reduced"]
    assert out["firstVisitStarted"] and r["matches"]
    assert r["typed"] == r["spoken"] == _said(steps[0]["text"], name) and r["state"] != "talking"
    assert r["animation"] == "none" and r["beacon"] == "none"
    assert r["step2"]["typed"] == _said(steps[1]["text"], name) and r["step2"]["state"] != "talking"


# ---------------------------------------------------------------- the optional globe view

def test_globe_without_a_token_runs_offline_and_its_regions_run_the_demo_buttons(site, tmp_path):
    """Classic view is the default and does not load Cesium. With no token the globe is in offline
    mode with its note; without WebGL it falls back to Classic view with a note. Either way nothing
    reaches the console, and each region box runs exactly its preset's Demo button."""
    out = site("globe", tmp_path / "profile", extra=("--enable-unsafe-swiftshader", "--use-angle=swiftshader"))
    assert out["errors"] == [], out["errors"]
    assert out["initial"] == {"toggle": [["Globe", "false"], ["Classic view", "true"]], "panelShown": False,
                              "cesiumLoaded": False, "view": "classic"}
    g = out["globe"]
    assert g["mode"] == "offline", g                                   # no token -> offline, always
    if g["status"] == "failed":                                         # no WebGL on this machine
        assert g["view"] == "classic" and not g["panelShown"] and g["viewNote"], g
    else:
        assert g["status"] == "ready" and g["view"] == "globe" and g["panelShown"] and g["canvas"], g
        assert g["globeNote"] == "Globe running in offline mode, no terrain"
        wanted = presets.load_presets()
        assert g["regions"] == list(wanted)
        assert len(out["selects"]) == len(wanted)
        for s in out["selects"]:
            p = wanted[s["id"]]
            assert s["ok"] and [float(x) for x in s["fields"]] == [float(x) for x in p["bbox"]], s
            assert s["lens"] == p["lens"] and s["variable"] in lenses.variables(p["lens"]), s
            assert s["err"] in ("", NO_CHART) and s["card"], s
        assert out["unknown"] is False                                  # only presets are clickable
    c = out["classic"]
    assert c["toggle"] == [["Globe", "false"], ["Classic view", "true"]] and not c["panelShown"]
    assert c["card"] and c["err"] in ("", NO_CHART)                     # Classic view still works
