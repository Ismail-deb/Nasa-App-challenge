"""Hosting readiness: vendored chart library, /health, the env-var Cesium token, the Vercel config,
the runtime-only requirements and the custom-region message. Fast, no network, no browser."""
import json
import re
import tomllib

import pytest
from fastapi.testclient import TestClient

import common
from app import main, presets

ROOT = common.ROOT
client = TestClient(main.app)
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- vendored Plotly
def test_plotly_is_vendored_with_its_licence_and_loaded_locally():
    vendored = ROOT / "web" / "vendor" / "plotly"
    js = (vendored / "plotly.min.js").read_text(encoding="utf-8", errors="replace")[:400]
    assert "plotly.js v2.35.2" in js
    assert "MIT License" in (vendored / "LICENSE").read_text(encoding="utf-8")
    assert '<script src="/static/vendor/plotly/plotly.min.js"></script>' in INDEX
    assert not re.search(r"<script[^>]+src=\"https?://", INDEX), "no chart library from a CDN"
    r = client.get("/static/vendor/plotly/plotly.min.js")
    assert r.status_code == 200 and len(r.content) > 1_000_000


def test_page_shows_a_note_when_the_chart_library_fails():
    assert "if (window.Plotly)" in INDEX
    assert "The chart library (web/vendor/plotly) could not be loaded" in INDEX


# ---------------------------------------------------------------- /health
def test_health_is_200_with_a_small_json_body():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["presets"] == len(presets.load_presets())
    assert len(r.content) < 200


# ---------------------------------------------------------------- Cesium token via the environment
def test_env_token_is_served_through_the_config_route(monkeypatch):
    fake = "test-token-not-real-123"
    monkeypatch.setenv(main.TOKEN_ENV, fake)
    r = client.get("/frontend/config.local.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert r.text == f"window.CESIUM_ION_TOKEN = {json.dumps(fake)};\n"


def test_env_token_is_escaped_as_a_js_string(monkeypatch):
    monkeypatch.setenv(main.TOKEN_ENV, 'a"; alert(1); "')
    assert client.get("/frontend/config.local.js").text == 'window.CESIUM_ION_TOKEN = "a\\"; alert(1); \\"";\n'


def test_without_the_env_var_behaviour_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv(main.TOKEN_ENV, raising=False)
    monkeypatch.setattr(main, "LOCAL_CONFIG", tmp_path / "missing.js")
    assert client.get("/frontend/config.local.js").text == main.NO_TOKEN_JS
    local = tmp_path / "config.local.js"
    local.write_text('window.CESIUM_ION_TOKEN = "from-file";\n', encoding="utf-8")
    monkeypatch.setattr(main, "LOCAL_CONFIG", local)
    assert "from-file" in client.get("/frontend/config.local.js").text


# ---------------------------------------------------------------- custom regions on a preset-only host
def test_custom_region_gets_the_full_dataset_message_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path / "no-processed-data")
    r = client.get("/trend", params={"variable": "M2TMNXSLV/T2M", "bbox": "10,10,11,11"})
    assert r.status_code == 404
    assert "Custom regions need the full dataset" in r.json()["detail"]


# ---------------------------------------------------------------- config files
def _requirements(name):
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def test_runtime_requirements_are_pinned_minimal_and_match_pyproject():
    reqs = _requirements("requirements.txt")
    assert all("==" in r for r in reqs), reqs
    names = {r.split("==")[0].lower() for r in reqs}
    for heavy in ("pytest", "httpx", "matplotlib", "shapely", "pyogrio", "earthaccess", "xarray", "netcdf4"):
        assert heavy not in names
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["dependencies"] == reqs
    assert project["tool"]["vercel"]["entrypoint"] == "app.main:app"
    assert (ROOT / ".python-version").read_text().strip() == "3.12"


def test_vercel_json_keeps_dev_files_out_and_data_in():
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    exclude = cfg["functions"]["app/main.py"]["excludeFiles"]
    for pattern in ("tests/**", "design/**", "logs/**", "venv/**", "data/raw/**", "data/processed/**",
                    "**/__pycache__/**", ".pytest_cache/**"):
        assert pattern in exclude
    for needed in ("data/series", "data/maps", "web", "frontend", ".yml"):
        assert needed not in exclude


def test_the_app_imports_without_xarray():
    """The hosted install has no xarray: app.data must import it only when a gridded file is read."""
    src = (ROOT / "app" / "data.py").read_text(encoding="utf-8")
    assert not re.search(r"^import xarray|^from xarray", src, re.M)


@pytest.mark.parametrize("path", ["/", "/categories", "/lenses", "/presets", "/maps/index.json", "/health"])
def test_hosted_routes_answer(path):
    assert client.get(path).status_code == 200
