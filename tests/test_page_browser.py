"""The page driven in a real (headless) browser that is already on the machine: Edge, Chrome or
Chromium. No extra packages. Skipped when no such browser is found, or with NO_BROWSER_TESTS=1.

Each test opens tests/browser/<name>.html, which loads the real page in an iframe, clicks through
it and posts what it saw back to this process. Uses the committed preset series in data/series/.
"""
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
from fastapi.responses import FileResponse

import common
from app import lenses, main, presets

HARNESS = Path(__file__).parent / "browser"
WAIT_SECONDS = 90


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
    results, done = {}, {}
    outer = FastAPI()

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

    def run(name: str, profile: Path, lang: str = "de-DE", size: str = "1200,900") -> dict:
        """Open a harness page in a fresh browser profile and return what it posted."""
        done[name] = threading.Event()
        results.pop(name, None)
        proc = subprocess.Popen(
            [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--lang={lang}", f"--user-data-dir={profile}", f"--window-size={size}",
             # --dump-dom makes the browser exit by itself, once the (virtual) time budget is used up
             f"--virtual-time-budget={WAIT_SECONDS * 1000}", "--dump-dom",
             f"http://127.0.0.1:{port}/__harness/{name}.html"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            assert done[name].wait(WAIT_SECONDS), f"the browser never reported back for {name}"
        finally:
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
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
        assert c["err"] == "", c                                        # no "not available" message
        assert c["card"], c                                             # a result card was shown
    # typed comma decimals are read as numbers: the Central Valley box typed with commas is the preset
    assert out["typed"]["err"] == "" and "California Central Valley" in out["typed"]["card"]
    assert out["typed"]["fields_after_change"] == ["-122.6", "35", "-118.8", "40.6"]      # dots, as numbers
    # a custom region without the full dataset says so (only when the gridded files are absent here)
    if not any(common.PROCESSED_DIR.glob("*.nc")):
        assert "Custom regions need the full dataset" in out["custom"]["err"]
        assert "only available on the machine that has it" in out["custom"]["err"]
