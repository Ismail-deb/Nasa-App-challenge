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
TIPS = _const("GUIDE_TIPS")
GREETING = _const("GUIDE_GREETING")
PAGE_IDS = set(re.findall(r'\bid="([^"]+)"', PAGE))


# ---------------------------------------------------------------- the name, defined once

def test_guide_name_is_defined_exactly_once():
    assert NAME == "Orbit"
    assert len(re.findall(r"\bGUIDE_NAME\s*=", CONFIG)) == 1
    assert "GUIDE_NAME =" not in GUIDE_JS.replace("NAME = GUIDE_NAME", "") and "GUIDE_NAME =" not in PAGE


def test_guide_name_is_hardcoded_nowhere_else():
    """The literal name appears on the one config line and in no other file the app serves or runs."""
    assert CONFIG.count(NAME) == 1 and f'const GUIDE_NAME = "{NAME}";' in CONFIG
    files = [p for p in WEB.rglob("*") if p.is_file()] + list((common.ROOT / "app").glob("*.py"))
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

def test_tutorial_has_the_seven_steps_in_order():
    assert [s["id"] for s in STEPS] == ["welcome", "demos", "lens", "chart", "result", "meaning", "region"]


@pytest.mark.parametrize("step", STEPS, ids=[s["id"] for s in STEPS])
def test_every_step_has_text_and_a_target_that_exists_in_the_page(step):
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
    start = GUIDE_JS.split("function startTour() {")[1].split("}")[0]
    assert "store.set(KEY_SEEN, '1')" in start                          # so it never starts by itself again
    assert "var enabled = store.get(KEY_ON) !== 'off';" in GUIDE_JS
    assert "store.set(KEY_ON, yes ? 'on' : 'off');" in GUIDE_JS
    assert GUIDE_JS.count("localStorage") == GUIDE_JS.count("window.localStorage.") + 1   # only inside the store (+ a comment)


def test_three_animation_states_and_reduced_motion():
    for state in ("idle", "talking", "pointing"):
        assert f'.guide[data-state="{state}"]' in GUIDE_CSS
    assert "@keyframes guide-bob" in GUIDE_CSS and "@keyframes guide-pulse" in GUIDE_CSS
    reduced = GUIDE_CSS.split("@media (prefers-reduced-motion: reduce)")[1].split("}")[0]
    assert "animation: none !important" in reduced and "transition: none !important" in reduced
    assert "(prefers-reduced-motion: reduce)" in GUIDE_JS and "if (reduced())" in GUIDE_JS
    assert "@media (max-width: 1200px)" in GUIDE_CSS                    # collapses to a small icon


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
