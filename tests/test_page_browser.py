"""The page driven in a real (headless) browser that is already on the machine: Edge, Chrome or
Chromium. No extra packages. Skipped when no such browser is found, or with NO_BROWSER_TESTS=1.

Each test opens tests/browser/<name>.html, which loads the real page in an iframe, clicks through
it and posts what it saw back to this process. Uses the committed preset series in data/series/.
"""
import json
import re
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
        if mode["guide"] == "fastdance":                    # the idle dance within seconds, not minutes
            js = re.sub(r"^const GUIDE_DANCE = .*;$", 'const GUIDE_DANCE = {"idleSeconds": 1, "quietSeconds": 0.5, '
                        '"repeatMinSeconds": 1, "repeatMaxSeconds": 1.5, "durationSeconds": 1.8};', js, flags=re.M)
        if mode["guide"] == "nostorage":
            js = ("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked'); }});\n" + js)
        return Response(js, media_type="text/javascript", headers=main.NO_CACHE)

    @outer.get("/static/guide/assets/{name}")
    def guide_art(name: str):
        """The guide's pictures, or nothing at all, to check that the drone takes over."""
        if mode["guide"] == "noimages":
            return Response(status_code=404)
        return FileResponse(common.ROOT / "web" / "guide" / "assets" / name, headers=main.NO_CACHE)

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
    # (the card's headline names the region only for some results, so a result card is the check here)
    assert out["typed"]["err"] in ("", NO_CHART) and out["typed"]["card"]
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
    assert [s["id"] for s in out["steps"]] == [s["id"] for s in steps]
    n = len(steps)
    for i, (seen, step) in enumerate(zip(out["steps"], steps)):
        assert seen["spoken"] == seen["typed"] == _said(step["text"], name), seen   # typed out completely
        assert seen["progress"] == f"Step {i + 1} of {n}"
        assert seen["targetVisible"] and seen["spotShown"] and seen["spotOnTarget"] and seen["targetInView"], seen
        assert seen["stateAtStart"] == "talking" and seen["typedAtStart"] != seen["typed"], seen   # typewriter
        assert seen["poseAtStart"] == "talking" and seen["poseAfter"] == "pointing", seen         # the pictures swap with the state
        assert seen["stateAfter"] == "pointing", seen
        # he points toward the highlighted element: flipped exactly when it is to his left
        assert seen["facing"] == ("left" if seen["targetLeftOfFox"] else "right"), seen
        assert seen["flip"] == ("matrix(-1, 0, 0, 1, 0, 0)" if seen["facing"] == "left" else "none"), seen
        assert seen["foxInWindow"] and seen["bubbleInWindow"] and not seen["foxOverBubble"], seen
        assert seen["skipShown"] and seen["backShown"] == (i > 0) and seen["focusOnNext"], seen
        assert seen["next"] == ("Finish" if i == n - 1 else "Next")
    assert name in out["steps"][0]["spoken"]                                # introduces itself by name
    assert not any(seen["bubbleCoversTarget"] for seen in out["steps"])     # never on top of what it explains
    after = out["afterFinish"]
    assert not after["bubbleOpen"] and after["spotHidden"] and after["state"] == "idle"
    assert after["idleAnimation"] == "guide-bob" and after["swayAnimation"] == "guide-sway" and after["pose"] == "neutral"
    assert after["guideShown"] and after["cardShown"]
    # back at the right-hand edge (slightly over it); the chart and the card now reach across the page,
    # so he stands at the nearest spot along that edge that keeps off both
    assert after["fox"]["right"] >= after["win"]["w"] and after["fox"]["bottom"] <= after["win"]["h"] + 2, after["fox"]
    assert not after["overChart"] and not after["overCard"], after
    # a cut-out: no panel, background or border, only a drop-shadow
    assert after["background"] == "rgba(0, 0, 0, 0)" and after["borderWidth"] == "0px" and "drop-shadow" in after["shadow"], after
    assert after["seen"] == "1"


def test_header_controls_are_named_after_the_guide(guide_run):
    name, _, _ = _guide_config()
    after = guide_run["afterFinish"]
    assert after["toggle"] == f"{name}: on" and after["pressed"] == "true"
    assert after["replay"] == f"Replay with {name}"
    assert after["avatarLabel"].startswith(name)


def test_second_visit_has_no_tutorial_and_the_toggle_is_remembered(guide_run):
    name, steps, _ = _guide_config()
    out = guide_run
    assert out["secondVisit"] == {"bubbleOpen": False, "guideShown": True, "toggle": f"{name}: on"}
    assert out["off"] == {"toggle": f"{name}: off", "pressed": "false", "guideShown": False, "stored": "off"}
    assert out["offReload"] == {"toggle": f"{name}: off", "guideShown": False, "bubbleOpen": False,
                                "tipStillAnswers": True, "hiddenAgainAfterClose": True}
    assert out["replay"] == {"open": True, "progress": f"Step 1 of {len(steps)}", "toggle": f"{name}: on",
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


def test_narrow_window_collapses_him_to_his_head(guide_run):
    out = guide_run
    assert out["afterFinish"]["avatarWidth"] >= 70                       # full size in a wide window
    narrow = out["narrow"]
    assert narrow["width"] <= 400 and narrow["tucked"] == "true" and not narrow["bubbleOpen"]
    assert narrow["avatarWidth"] <= 90 and narrow["avatarHeight"] < narrow["avatarWidth"]       # just his head
    assert narrow["wideAgain"]["tucked"] == "false" and narrow["wideAgain"]["avatarWidth"] >= 100  # back in a wide window
    assert len(narrow["steps"]) == len(_guide_config()[1])
    for seen in narrow["steps"]:
        assert seen["spotShown"] and seen["spotOnTarget"] and seen["targetInView"], seen
        assert seen["foxInWindow"] and seen["bubbleInWindow"], seen
        # the bubble stays off what it explains, unless that is taller than the window has room for
        assert not seen["bubbleCoversTarget"] or not seen["targetFits"], seen
    assert not next(s for s in narrow["steps"] if s["id"] == "chart")["bubbleCoversTarget"]


def test_he_can_be_dragged_moved_by_keys_and_remembers_where_he_stands(guide_run):
    out = guide_run
    drag = out["drag"]
    assert abs(drag["during"] + 200) <= 3, drag                            # follows the pointer while dragging
    assert abs(drag["dx"] + 40) <= 3 and abs(drag["dy"] + 200) <= 3, drag    # and stays where he was dropped
    assert 0 <= drag["saved"]["x"] <= 1 and 0 <= drag["saved"]["y"] < 1 and not drag["bubbleOpen"], drag
    keys = out["keys"]
    assert abs(keys["dx"] - 16) <= 3 and abs(keys["dy"] - 16) <= 3, keys     # arrow keys: 16 px steps
    assert keys["saved"] != drag["saved"]


def test_a_saved_position_over_the_chart_is_nudged_to_a_free_edge(guide_run):
    n = guide_run["nudge"]
    assert not n["overChart"] and n["atEdge"] and n["inWindow"], n
    assert n["saved"] == '{"x":0.5,"y":0.5}', n                              # the saved position itself is not changed
    assert not n["withCard"]["overChart"] and not n["withCard"]["overCard"], n   # and he keeps off the result card too


def test_he_stays_inside_the_window_when_it_is_resized(guide_run):
    r = guide_run["resized"]
    assert r["inWindow"] and r["win"]["w"] <= 810 and r["win"]["h"] <= 510, r


def test_tuck_control_shows_only_his_head_and_is_remembered(guide_run):
    name, _, _ = _guide_config()
    t = guide_run["tuck"]
    assert t["tucked"] == "true" and t["stored"] == "yes" and t["height"] < t["width"] and t["inWindow"], t
    assert t["label"] == f"Bring {name} back" and t["pose"] == "neutral", t
    assert t["back"]["tucked"] == "false" and t["back"]["stored"] == "no" and t["back"]["height"] > t["width"], t


def test_page_works_without_the_guide(guide_run):
    f = guide_run["failures"]
    for mode in ("missing", "broken"):                                    # config.js 404 / nonsense
        assert f[mode]["card"] and f[mode]["title"], f[mode]
        assert not f[mode]["guide"] and f[mode]["controls"] == 0 and f[mode]["tipsShown"] == 0, f[mode]
    assert f["nostorage"]["card"] and f["nostorage"]["guide"]             # localStorage blocked: still fine
    assert f["noimages"]["card"] and f["noimages"]["art"] == "drone" and f["noimages"]["drone"], f["noimages"]   # pictures missing: the drone


def test_reduced_motion_means_no_animation_and_instant_text(site, tmp_path):
    name, steps, _ = _guide_config()
    out = site("guide_reduced", tmp_path / "profile", page="guide.html?reduced=1",
               extra=("--force-prefers-reduced-motion",))
    assert out["errors"] == [], out["errors"]
    r = out["reduced"]
    assert out["firstVisitStarted"] and r["matches"]
    assert r["typed"] == r["spoken"] == _said(steps[0]["text"], name) and r["state"] != "talking"
    assert r["animation"] == "none" and r["sway"] == "none" and r["beacon"] == "none"      # no bobbing, tilting or pulsing
    assert r["transition"] == "none"                                                       # no flying: he jumps
    assert r["pose"] == "pointing" and r["step2"]["pose"] == "pointing"                    # the pose swaps still happen
    assert r["step2"]["typed"] == _said(steps[1]["text"], name) and r["step2"]["state"] != "talking"


def test_idle_dance_runs_in_place_and_never_during_the_tour_or_a_bubble(site, tmp_path):
    """With short timings from the config: every pose's feet line up (placed from the manifest); he
    dances when idle (neutral, cheer, dance, flipped on alternate beats, or cheer only where the wide pose
    would reach the chart), without moving, and ends at rest; a drag cancels it; a bubble or the tutorial
    keeps it off; the header button and ?calm=1 turn it off. Nothing in the console."""
    out = site("dance", tmp_path / "profile")
    assert out["errors"] == [], out["errors"]
    a = out["align"]
    assert a["placed"] == "placed" and set(a["feet"]) == {"neutral", "talking", "pointing", "cheer", "dance"}, a
    for pose, f in a["feet"].items():
        assert abs(f["x"] - a["anchor"]) <= 1 and abs(f["bottom"] - a["box"]["bottom"]) <= 1, (pose, a)
    assert out["started"] and out["ended"], out
    first = out["first"]
    assert len(first["plans"]) == 1 and first["plans"][0] in ("full", "cheer"), first
    wanted = ["cheer", "dance", "neutral"] if first["plans"] == ["full"] else ["cheer", "neutral"]
    assert first["poses"] == wanted, first
    assert "none" in first["flips"] and any(t.startswith("matrix(-1") for t in first["flips"]), first
    assert first["places"] == [first["rest"]] and first["restAfter"] == first["rest"], first      # in place
    assert first["state"] == "idle" and first["leftover"] == [] and first["pose"] == ["neutral"], first
    assert abs(first["avatar"]["w"] - a["box"]["width"]) < 1, first                                # his box never grew
    assert first["button"] == "Idle dance: on" and first["pressed"] == "true", first
    assert out["secondStarted"] and out["cancelledByDrag"], out
    assert out["whileBubble"] == {"open": True, "started": 0, "dancing": False}, out["whileBubble"]
    assert out["whileTour"] == {"open": True, "started": 0, "dancing": False}, out["whileTour"]
    assert out["off"] == {"started": 0, "button": "Idle dance: off", "stored": "off"}, out["off"]
    assert out["backOn"] == {"button": "Idle dance: on", "stored": "on"}, out["backOn"]
    assert out["calm"] == {"started": 0, "button": "Idle dance: off", "disabled": True}, out["calm"]


# ---------------------------------------------------------------- the optional globe view

def test_globe_view_has_its_own_tutorial_and_replay_follows_the_view(site, tmp_path):
    """The first time Globe view is opened its own tutorial starts (the Classic one was seen already);
    every step highlights its element; replay gives the tutorial of the view that is shown; a step whose
    element is missing is skipped; nothing reaches the console. Without WebGL the page is back in
    Classic view and replay gives the Classic tutorial."""
    from test_guide import GLOBE_STEPS, NAME, STEPS
    out = site("globe_tour", tmp_path / "profile",
               extra=("--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--force-prefers-reduced-motion"))
    assert out["errors"] == [], out["errors"]
    assert out["counts"] == {"globe": len(GLOBE_STEPS), "classic": len(STEPS)}
    assert out["classicFirst"]["open"] is False
    classic_first = {"progress": f"Step 1 of {len(STEPS)}", "spoken": _said(STEPS[0]["text"], NAME)}
    if out["status"] != "ready":                                        # no WebGL on this machine
        assert out["view"] == "classic" and out["replayClassic"] == classic_first, out
        return
    n = len(GLOBE_STEPS)
    assert out["started"] and out["firstFlag"] == "1"
    assert [s["id"] for s in out["steps"]] == [s["id"] for s in GLOBE_STEPS], out["steps"]
    for i, (seen, step) in enumerate(zip(out["steps"], GLOBE_STEPS)):
        assert seen["spoken"] == seen["typed"] == _said(step["text"], NAME), seen
        assert seen["progress"] == f"Step {i + 1} of {n}", seen
        assert seen["spotShown"] and seen["spotOnTarget"] and seen["targetInView"], seen
        assert seen["bubbleInWindow"] and not seen["foxOverBubble"], seen
        assert seen["next"] == ("Finish" if i == n - 1 else "Next") and seen["state"] == "pointing", seen
        assert seen["usedTarget"], seen                                 # the real element, not the fallback
    after = out["afterFinish"]
    assert not after["open"] and after["spotHidden"] and after["view"] == "globe" and after["classicFlag"] == "1"
    assert out["replayGlobe"] == {"progress": f"Step 1 of {n}", "spoken": _said(GLOBE_STEPS[0]["text"], NAME)}
    assert out["leftGlobe"] == {"open": False}                           # leaving Globe view ends its tutorial
    assert out["replayClassic"] == classic_first
    assert out["secondVisit"] == {"open": False}                         # only the first time by itself
    assert out["withoutLegend"] == [s["id"] for s in GLOBE_STEPS if s["id"] != "legend"]

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
        t = out["trend"]                                                # trend map from data/maps/
        assert t["status"] == "ready" and t["panel"] and t["key"] == "T2M" and t["layerReady"], t
        assert t["nearest"] and t["onTop"] and t["alpha"] == 0.85 and not t["caveat"], t
        hidden = {k for k, shown in t["rows"] if not shown}
        assert hidden == {"SoilMoi0_10cm_inst", "Evap_tavg"}, t["rows"]   # experimental: hidden by default
        assert "Change per decade" in t["legend"] and "not statistically significant (FDR 10%)" in t["legend"]
        e = t["experimental"]
        assert e["key"] == "SoilMoi0_10cm_inst" and all(shown for _, shown in e["rows"]), e
        assert e["caveat"] and "artefacts" in e["caveat"], e
        assert t["back"] == {"key": "T2M", "caveat": False} and t["off"] == {"show": False}, t
    c = out["classic"]
    assert c["toggle"] == [["Globe", "false"], ["Classic view", "true"]] and not c["panelShown"]
    assert c["card"] and c["err"] in ("", NO_CHART)                     # Classic view still works
