"""The optional guide (web/guide/): its config, the page hooks it needs, and the single place
its name is defined. Text-level checks only; tests/test_page_browser.py clicks through it."""
import json
import re

import pytest
from fastapi.testclient import TestClient

import common
from app import main

WEB = common.ROOT / "web"
CONFIG = (WEB / "guide" / "config.js").read_text(encoding="utf-8")
GUIDE_JS = (WEB / "guide" / "guide.js").read_text(encoding="utf-8")
GUIDE_CSS = (WEB / "guide" / "guide.css").read_text(encoding="utf-8")
PAGE = (WEB / "index.html").read_text(encoding="utf-8")


def _const(name: str):
    """The JSON value of `const NAME = <json>;` in config.js."""
    m = re.search(rf"^const {name} = (.*?);\s*$", CONFIG, re.S | re.M)
    assert m, f"config.js must define {name}"
    return json.loads(m.group(1))


NAME = _const("GUIDE_NAME")
STEPS = _const("GUIDE_STEPS")
GLOBE_STEPS = _const("GUIDE_STEPS_GLOBE")
GLOBE_JS = (WEB / "globe" / "globe.js").read_text(encoding="utf-8")
TIPS = _const("GUIDE_TIPS")
GREETING = _const("GUIDE_GREETING")
PAGE_IDS = set(re.findall(r'\bid="([^"]+)"', PAGE))
# Globe view's elements are built by web/globe/globe.js: ids written in its markup or set as .id = '...'
GLOBE_IDS = set(re.findall(r'\bid="([^"]+)"', GLOBE_JS)) | set(re.findall(r"\.id = '([^']+)'", GLOBE_JS))
# every tutorial: (view, the ids its targets may use, its steps)
TOURS = {"classic": (PAGE_IDS, STEPS), "globe": (PAGE_IDS | GLOBE_IDS, GLOBE_STEPS)}
ALL_STEPS = [(view, step) for view, (_, steps) in TOURS.items() for step in steps]


# ---------------------------------------------------------------- the name, defined once

def test_guide_name_is_defined_exactly_once():
    assert NAME == "Comet"
    assert len(re.findall(r"\bGUIDE_NAME\s*=", CONFIG)) == 1
    assert "GUIDE_NAME =" not in GUIDE_JS.replace("NAME = GUIDE_NAME", "") and "GUIDE_NAME =" not in PAGE


def test_guide_name_is_hardcoded_nowhere_else():
    """The literal name appears on the one config line and in no other file the app serves or runs."""
    assert CONFIG.count(NAME) == 1 and f'const GUIDE_NAME = "{NAME}";' in CONFIG
    files = [p for p in WEB.rglob("*") if p.is_file() and p.suffix not in (".webp", ".woff2")] + list((common.ROOT / "app").glob("*.py"))
    files += [common.ROOT / n for n in ("lenses.yml", "presets.yml", "catalog.yml")]
    for path in files:
        if path.name == "config.js":
            continue
        assert not re.search(NAME, path.read_text(encoding="utf-8"), re.I), f"{path.name} hardcodes the guide's name"


def test_every_label_is_built_from_the_name():
    for built in ("NAME + (yes ? ': on' : ': off')",          # header toggle "<name>: on/off"
                  "'Replay with ' + NAME",                    # replay button
                  "'Ask ' + NAME + ' to explain'",            # "?" buttons
                  "q('.guide-name').textContent = NAME"):     # speech bubble
        assert built in GUIDE_JS, built
    assert "var NAME = GUIDE_NAME" in GUIDE_JS and "split('{name}').join(NAME)" in GUIDE_JS
    assert "{name}" in STEPS[0]["text"] and "{name}" in GREETING        # introduces itself by name


# ---------------------------------------------------------------- tutorial steps

def test_classic_tutorial_steps_are_unchanged_and_in_order():
    assert [s["id"] for s in STEPS] == ["welcome", "demos", "lens", "chart", "result", "meaning", "region"]


def test_globe_tutorial_is_a_separate_list_with_its_steps_in_order():
    assert [s["id"] for s in GLOBE_STEPS] == ["globe", "regions", "switch", "variables", "legend", "scenarios"]
    assert len(re.findall(r"\bGUIDE_STEPS_GLOBE\s*=", CONFIG)) == 1 and len(re.findall(r"\bGUIDE_STEPS\s*=", CONFIG)) == 1
    by_id = {s["id"]: s for s in GLOBE_STEPS}
    assert by_id["globe"]["text"] == "This is Earth. Drag to spin it and scroll to zoom."
    assert by_id["regions"]["text"] == "The cyan boxes are our demo regions. Click one to see its trend below."
    assert by_id["switch"]["text"] == "Turn the trend map on or off here."
    assert by_id["variables"]["text"] == "Pick a variable here. Temperature is the clearest one."
    assert "not statistically significant, which is not the same as no trend" in by_id["legend"]["text"]
    assert all(w in by_id["scenarios"]["text"] for w in ("solar", "wind", "hydro", "farming"))
    # the targets are the real elements: the globe, the region boxes, the switch, the list, the legend, the cards
    assert [s["target"] for s in GLOBE_STEPS] == ["#globeBox", "#globeRegions", "#trendSwitch", "#trendList", "#trendLegend", "#demos"]
    assert by_id["regions"]["globeAction"] == "showRegions" and "state.showRegions = function ()" in GLOBE_JS


def test_step_texts_live_in_the_config_only():
    """No tutorial sentence is written in the guide's code, the globe's code or the page."""
    for _, step in ALL_STEPS:
        for text in (GUIDE_JS, GLOBE_JS, PAGE):
            assert step["text"] not in text and step["text"][:40] not in text, step["id"]


@pytest.mark.parametrize("view,step", ALL_STEPS, ids=[f"{v}:{s['id']}" for v, s in ALL_STEPS])
def test_every_step_has_text_and_a_target_that_exists_in_the_page(view, step):
    PAGE_IDS = TOURS[view][0]                                           # the ids of the view this step is shown in
    text = step["text"].strip()
    assert text and len(text) <= 240                                    # one or two short sentences
    assert 1 <= len(re.findall(r"[.!?](?:\s|\"|$)", text)) <= 4
    for key in ("target", "fallback"):
        if key == "fallback" and key not in step:
            continue
        ids = [s.strip() for s in step[key].split(",")]
        assert ids and all(re.fullmatch(r"#[A-Za-z][\w-]*", s) for s in ids), step[key]   # plain #id selectors
        assert all(s[1:] in PAGE_IDS for s in ids), f"{step[key]} is not in web/index.html"


def test_steps_say_what_was_asked_for():
    by_id = {s["id"]: s["text"] for s in STEPS}
    assert "NASA" in by_id["welcome"] and "significant" in by_id["welcome"]
    assert "lens" in by_id["demos"]
    assert all(w in by_id["lens"] for w in ("solar", "wind", "hydro", "farming"))
    assert "trend" in by_id["chart"]
    for words in ("per decade", "95% range", "p-value", "ignificant", 'does not mean \\"no trend\\"'.replace("\\", "")):
        assert words in by_id["result"], words
    assert "energy providers" in by_id["meaning"] and "farmers" in by_id["meaning"] and "regional screening" in by_id["meaning"]
    assert all(w in by_id["region"] for w in ("West", "South", "East", "North"))
    assert by_id["demos"] != "" and {"target": "#demos"}.items() <= STEPS[1].items()
    assert STEPS[6]["target"] == "#w, #s, #e, #n"
    assert all(STEPS[i].get("needsResult") for i in (3, 4, 5))          # these explain a result


# ---------------------------------------------------------------- tips

def test_the_four_tips_have_text_and_a_button_in_the_page():
    assert {t["label"] for t in TIPS.values()} == {"p-value", "95% range", "significant", "not enough variation"}
    for key, tip in TIPS.items():
        assert tip["text"].strip() and len(tip["text"]) <= 240
    for key in ("pvalue", "ci95", "significant"):
        assert f'class="tip" data-tip="{key}" hidden>?</button>' in PAGE or f'data-tip="{key}" hidden>?</button>' in PAGE
    # "not enough variation" replaces "significant" next to the verdict of a low-reliability result
    assert "$('verdictTip').dataset.tip = d.reliability === 'low' ? 'variation' : 'significant';" in PAGE
    assert PAGE.count('class="tip"') == 3
    assert all(tag.endswith("hidden>") for tag in re.findall(r'<button type="button" class="tip"[^>]*>', PAGE))


# ---------------------------------------------------------------- first visit, toggle, motion

def test_first_visit_logic_and_persisted_toggle():
    assert "var KEY_ON = 'estd.guide.enabled';" in GUIDE_JS and "var KEY_SEEN = 'estd.guide.tutorialSeen';" in GUIDE_JS
    assert "if (enabled && store.get(KEY_SEEN) === null) return startTour();" in GUIDE_JS
    # Globe view has its own first-visit flag and its own list; replay follows the view that is shown
    assert "var KEY_SEEN_GLOBE = 'estd.guide.globeTutorialSeen';" in GUIDE_JS
    globe_start = GUIDE_JS.split("function startGlobeTour() {")[1].split("}")[0]
    assert "STEPS = GLOBE;" in globe_start and "store.set(KEY_SEEN_GLOBE, '1')" in globe_start
    assert "if (store.get(KEY_SEEN_GLOBE) !== null) return undefined;" in GUIDE_JS
    assert "if (globeActive()) return startGlobeTour();" in GUIDE_JS.split("function startTour() {")[1].split("}")[0]
    assert "on(replayBtn, 'click', function () { setEnabled(true); return startTour(); });" in GUIDE_JS
    # only a globe that is running counts: a failed globe (back in Classic view) gets the Classic tutorial
    assert "return GLOBE.length > 0 && b.view === 'globe' && b.globe === 'ready';" in GUIDE_JS
    assert "flag('globe', 'failed');" in GLOBE_JS and "document.body.dataset.view = view;" in GLOBE_JS
    # a step whose element is missing is skipped
    assert "if (STEPS[i].needsResult || targetOf(STEPS[i])) return i;" in GUIDE_JS
    start = GUIDE_JS.split("function startTour() {")[1].split("}")[0]
    assert "store.set(KEY_SEEN, '1')" in start                          # so it never starts by itself again
    assert "var enabled = store.get(KEY_ON) !== 'off';" in GUIDE_JS
    assert "store.set(KEY_ON, yes ? 'on' : 'off');" in GUIDE_JS
    assert GUIDE_JS.count("localStorage") == GUIDE_JS.count("window.localStorage.") + 1   # only inside the store (+ a comment)


def test_three_animation_states_and_reduced_motion():
    for state in ("idle", "talking", "pointing"):
        assert f'.guide[data-state="{state}"]' in GUIDE_CSS
    assert "@keyframes guide-bob" in GUIDE_CSS and "@keyframes guide-sway" in GUIDE_CSS      # bob + occasional tilt
    assert "@keyframes guide-pulse" in GUIDE_CSS                                            # the drone fallback's light
    reduced = GUIDE_CSS.split("@media (prefers-reduced-motion: reduce)")[1].split("}")[0]
    assert "animation: none !important" in reduced and "transition: none !important" in reduced
    assert "(prefers-reduced-motion: reduce)" in GUIDE_JS and "if (reduced())" in GUIDE_JS
    assert "@media (max-width: 700px)" in GUIDE_CSS                     # starts as just his head


def test_no_voice_no_video_no_third_party_code():
    for text in (GUIDE_JS, CONFIG, GUIDE_CSS):
        for banned in ("speechSynthesis", "<video", "<audio", "new Audio", "http://", "https://", "import ", "require("):
            assert banned not in text, banned
    guide_tags = [t for t in re.findall(r"<(?:script|link)[^>]*>", PAGE) if "guide" in t]
    assert guide_tags == ['<link rel="stylesheet" href="/static/guide/guide.css">',
                          '<script src="/static/guide/config.js">', '<script src="/static/guide/guide.js">']


def test_guide_cannot_break_the_page():
    """Loaded after the page's own script, everything wrapped, and nothing written to the console."""
    assert PAGE.index("init().catch(") < PAGE.index("/static/guide/config.js") < PAGE.index("/static/guide/guide.js")
    assert not re.search(r"console\.\w+\(", GUIDE_JS)                # no console.error / warn / log calls
    assert GUIDE_JS.rstrip().endswith("safe(init)();\n})();")
    assert "typeof GUIDE_NAME !== 'string'" in GUIDE_JS and "typeof GUIDE_STEPS === 'undefined'" in GUIDE_JS
    inline = PAGE.split("<script>")[-1].split("</script>")[0]
    assert "GUIDE_" not in inline and "guide" not in inline.lower().replace("guidecontrols", "")


def test_guide_files_are_served_fresh():
    c = TestClient(main.app)
    for path in ("/static/guide/config.js", "/static/guide/guide.js", "/static/guide/guide.css", "/"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    assert f'const GUIDE_NAME = "{NAME}";' in c.get("/static/guide/config.js").text


# ---------------------------------------------------------------- the character (three transparent poses)

POSES = ("neutral", "talking", "pointing")
IMAGES = _const("GUIDE_IMAGES")


def _webp_info(path):
    """(width, height, has_alpha) of a WebP file, read from its VP8X header (no image library needed)."""
    import struct
    b = path.read_bytes()
    assert b[:4] == b"RIFF" and b[8:12] == b"WEBP", f"{path.name} is not a WebP file"
    assert b[12:16] == b"VP8X", f"{path.name} has no extended header, so no transparency"
    return (1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little"), bool(b[20] & 0x10))


def test_three_poses_are_configured_once_and_the_files_exist():
    assert set(IMAGES) == set(POSES)
    assert len(re.findall(r"\bGUIDE_IMAGES\s*=", CONFIG)) == 1
    for pose in POSES:
        url = IMAGES[pose]
        assert url.startswith("/static/guide/assets/") and url.endswith(".webp"), url
        assert (WEB / url.removeprefix("/static/")).is_file(), url
    for path in (GUIDE_JS, GUIDE_CSS, PAGE):                           # the addresses live in config.js only
        assert "assets/" not in path


def test_poses_are_transparent_and_share_one_canvas_size():
    """Same width and height for all three, with an alpha channel: swapping them cannot make him jump
    and nothing (no panel, no background) is baked into the picture."""
    infos = {pose: _webp_info(WEB / IMAGES[pose].removeprefix("/static/")) for pose in POSES}
    assert len({(w, h) for w, h, _ in infos.values()}) == 1, infos
    assert all(alpha for _, _, alpha in infos.values()), infos


def test_he_is_free_floating_with_no_panel_and_only_a_drop_shadow():
    block = GUIDE_CSS.split(".guide-avatar {")[1].split("}")[0]
    assert "background: none" in block and "border: 0" in block and "box-shadow: none" in block
    assert "drop-shadow(" in GUIDE_CSS.split(".guide-flip {")[1].split("}")[0]
    root = GUIDE_CSS.split(".guide { position: fixed;")[1].split("}")[0]
    assert "pointer-events: none" in root and "z-index" in root           # only he (and his bubble) take clicks
    assert ".guide > * { pointer-events: auto; }" in GUIDE_CSS
    assert "touch-action: none" in block                                  # touch dragging


def test_poses_are_preloaded_stacked_and_flip_toward_the_target():
    assert "POSES.map(function (p)" in GUIDE_JS and "data-pose=" in GUIDE_JS        # all three are in the page from the start
    assert "grid-area: 1 / 1" in GUIDE_CSS                                          # stacked in one cell
    for state, pose in (("idle", "neutral"), ("talking", "talking"), ("pointing", "pointing")):
        assert f'.guide[data-state="{state}"] .guide-img[data-pose="{pose}"]' in GUIDE_CSS
    assert 'root.dataset.facing = r && (r.left + r.right) / 2 < fox.x + d.w / 2 ? \'left\' : \'right\';' in GUIDE_JS
    assert '.guide[data-art="fox"][data-facing="left"] .guide-flip { transform: scaleX(-1); }' in GUIDE_CSS


def test_drone_is_the_fallback_when_a_picture_fails():
    assert "root.dataset.art = haveArt ? 'fox' : 'drone';" in GUIDE_JS
    assert "on(img, 'error', function () { root.dataset.art = 'drone';" in GUIDE_JS
    assert 'class="guide-drone-svg"' in GUIDE_JS and '.guide[data-art="drone"] .guide-img { display: none; }' in GUIDE_CSS


def test_position_is_saved_clamped_and_movable_by_mouse_touch_and_keys():
    assert "var KEY_POS = 'estd.guide.pos';" in GUIDE_JS and "store.set(KEY_POS," in GUIDE_JS
    assert "clamp(+p.x, 0, 1)" in GUIDE_JS and "OVER" in GUIDE_JS                    # shares of the free area: always inside the window
    for event in ("pointerdown", "pointermove", "pointerup", "pointercancel"):       # one path for mouse, touch and pen
        assert f"'{event}'" in GUIDE_JS, event
    assert "e.key === 'ArrowLeft'" in GUIDE_JS and "e.key === 'ArrowDown'" in GUIDE_JS
    assert "on(window, 'resize'" in GUIDE_JS


def test_he_keeps_off_the_chart_card_and_globe_while_idle():
    assert "var AVOID = ['#chart', '#card', '#globePanel', '#viewToggle'];" in GUIDE_JS
    assert 'id="chart"' in PAGE and 'id="card"' in PAGE
    assert "nudge(toPx(saved, d), d)" in GUIDE_JS                                    # the saved position itself is not changed
    assert "new MutationObserver(" in GUIDE_JS


def test_tuck_control_and_narrow_default():
    assert "var NARROW = 700;" in GUIDE_JS and "vw() <= NARROW" in GUIDE_JS
    assert 'class="guide-tuck" id="guideTuck"' in GUIDE_JS and "var KEY_TUCK = 'estd.guide.tucked';" in GUIDE_JS
    assert '[data-tucked="true"] .guide-avatar { aspect-ratio: 460 / 290; overflow: hidden; }' in GUIDE_CSS   # head only


def test_he_flies_during_the_tour_and_jumps_with_reduced_motion():
    assert ".guide.guide-fly { transition: left .45s ease, top .45s ease; }" in GUIDE_CSS
    reduced = GUIDE_CSS.split("@media (prefers-reduced-motion: reduce)")[1].split("}")[0]
    assert ".guide *" in reduced and "transition: none !important" in reduced and "animation: none !important" in reduced
    assert "planTour(r, d)" in GUIDE_JS and "closeBubble" in GUIDE_JS


def test_readme_credits_the_artwork_and_documents_the_name():
    readme = (common.ROOT / "README.md").read_text(encoding="utf-8")
    assert "Guide artwork generated with AI" in readme
    assert "Orbit" not in readme
