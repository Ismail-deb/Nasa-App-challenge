"""Lenses: lenses.yml integrity, template resolution, the API (lens filter, lens_message,
lens_caveat, errors). Synthetic series only."""
import itertools

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import common
from app import data, lenses, presets

CFG = lenses.load()
DISCLAIMER = "Long-term regional screening only. Not a substitute for site measurements or local advice."
NOT_SIG = "No significant change detected yet; a longer record may reveal a trend."
EXPECTED = {
    "solar": ["M2TMNXRAD/SWGDN", "M2TMNXRAD/CLDTOT", "M2TMNXAER/TOTEXTTAU", "M2TMNXSLV/T2M"],
    "wind": ["M2TMNXSLV/WIND50M"],
    "hydro": ["GPM_3IMERGM/precipitation", "GLDAS_NOAH025_M/Qs_acc", "GLDAS_NOAH025_M/SWE_inst"],
    "farming": ["GPM_3IMERGM/precipitation", "GLDAS_NOAH025_M/SoilMoi0_10cm_inst", "M2TMNXSLV/T2M",
                "GLDAS_NOAH025_M/Evap_tavg"],
}
ALL_KEYS = [(lid, v, d, s) for lid in CFG["lenses"] for v in lenses.variables(lid)
            for d, s in itertools.product(lenses.DIRECTIONS, lenses.SIGNIFICANCE)]


# ---------------------------------------------------------------- lenses.yml

def test_lenses_and_their_variables():
    assert {lid: lenses.variables(lid) for lid in CFG["lenses"]} == EXPECTED
    assert tuple(CFG["lenses"]) == presets.LENSES
    assert CFG["disclaimer"] == DISCLAIMER and CFG["not_significant"] == NOT_SIG
    for lid, l in CFG["lenses"].items():
        assert l["name"] and l["description"] and lenses.caveat(lid)
        assert l["default_variable"] in lenses.variables(lid)
        for v in lenses.variables(lid):
            data.find_entry(v)                                   # every variable is in catalog.yml


def test_every_preset_lens_exists():
    for p in presets.load_presets().values():
        assert p["lens"] in CFG["lenses"]


@pytest.mark.parametrize("key", ALL_KEYS, ids=lambda k: "-".join(k))
def test_every_template_key_resolves(key):
    lid, v, d, s = key
    text = lenses.template(lid, v, d, s)
    assert text and text.endswith(".") and "{" not in text
    if s == "not_significant":
        assert text == NOT_SIG
    else:
        assert text != NOT_SIG


def test_increasing_and_decreasing_templates_differ():
    for lid in CFG["lenses"]:
        for v in lenses.variables(lid):
            assert lenses.template(lid, v, "increasing", "significant") != \
                lenses.template(lid, v, "decreasing", "significant")


def test_direction_and_significance_come_from_slope_sign_and_flag():
    t = CFG["lenses"]["hydro"]["templates"]["GLDAS_NOAH025_M/SWE_inst"]
    assert lenses.message("hydro", "GLDAS_NOAH025_M/SWE_inst", -0.26, True) == f"{t['decreasing']} {DISCLAIMER}"
    assert lenses.message("hydro", "GLDAS_NOAH025_M/SWE_inst", 0.003, True) == f"{t['increasing']} {DISCLAIMER}"
    for slope in (-0.26, 0.26, 0.0):
        assert lenses.message("hydro", "GLDAS_NOAH025_M/SWE_inst", slope, False) == f"{NOT_SIG} {DISCLAIMER}"
    assert lenses.message("hydro", "GLDAS_NOAH025_M/SWE_inst", 0.0, True) == f"{NOT_SIG} {DISCLAIMER}"


@pytest.mark.parametrize("key", ALL_KEYS, ids=lambda k: "-".join(k))
def test_every_message_includes_the_disclaimer(key):
    lid, v, d, s = key
    msg = lenses.message(lid, v, 1.0 if d == "increasing" else -1.0, s == "significant")
    assert msg.endswith(DISCLAIMER) and msg.count(DISCLAIMER) == 1


def test_no_lens_message_for_low_reliability():
    for lid, v, d, s in ALL_KEYS:
        assert lenses.message(lid, v, 1.0 if d == "increasing" else -1.0, s == "significant", "low") is None


def test_unknown_lens_or_variable_raises():
    with pytest.raises(KeyError):
        lenses.template("solar", "M2TMNXSLV/WIND50M", "increasing", "significant")
    with pytest.raises(KeyError):
        lenses.variables("nuclear")


def test_physical_direction_wording():
    """Spot-checks of the reasoning the templates must get right."""
    tpl = lambda l, v, d: lenses.template(l, v, d, "significant")
    assert "less efficiently" in tpl("solar", "M2TMNXSLV/T2M", "increasing")
    assert "does not itself reduce the sunlight" in tpl("solar", "M2TMNXSLV/T2M", "increasing")
    assert "less sunlight" in tpl("solar", "M2TMNXRAD/CLDTOT", "increasing")
    assert "less sunlight" in tpl("solar", "M2TMNXAER/TOTEXTTAU", "increasing")
    assert "not river flow" in tpl("hydro", "GLDAS_NOAH025_M/Qs_acc", "decreasing")
    assert "reduce spring and summer inflow" in tpl("hydro", "GLDAS_NOAH025_M/SWE_inst", "decreasing")
    assert "irrigation needs" in tpl("farming", "GLDAS_NOAH025_M/Evap_tavg", "increasing")
    w = tpl("wind", "M2TMNXSLV/WIND50M", "increasing")
    assert "below the height of modern turbine hubs (typically 80 to 120 m)" in w and "relative change only" in w
    for lid, v, d, s in ALL_KEYS:                               # never site-level or scheduling claims
        text = lenses.template(lid, v, d, s).lower()
        assert "feasib" not in text and "schedul" not in text and "yield" not in text


# ---------------------------------------------------------------- API

IDX = pd.date_range("2000-01-01", periods=240, freq="MS")
PRESETS = {"boxa": {"name": "Box A", "bbox": [-1.0, -1.0, 1.0, 1.0], "lens": "hydro", "why": "t"}}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    series = tmp_path / "series"
    series.mkdir()
    monkeypatch.setattr(common, "PROCESSED_DIR", tmp_path / "none")
    monkeypatch.setattr(common, "SERIES_DIR", series)
    monkeypatch.setattr(presets, "load_presets", lambda: PRESETS)
    rows = []

    def put(var_key, var_id, units, values):
        pd.DataFrame({"date": IDX.strftime("%Y-%m"), "value": values}).to_csv(
            series / f"{var_key}__boxa.csv", index=False)
        rows.append(f"- {{variable: {var_id}, region: boxa, units: '{units}', "
                    f"period_start: '2000-01', period_end: '2019-12'}}")
        (series / "index.yml").write_text("series:\n" + "\n".join(rows) + "\n", encoding="utf-8")
    from app.main import app
    return TestClient(app), put


Q = {"bbox": "-1,-1,1,1"}


def test_api_lens_message_and_caveat(client):
    c, put = client
    rng = np.random.default_rng(3)
    swe = np.where(np.isin(IDX.month, [11, 12, 1, 2, 3, 4]), np.linspace(80, 30, 240) + rng.normal(0, 2, 240), 0.0)
    put("SWE_inst", "GLDAS_NOAH025_M/SWE_inst", "kg m-2", swe)
    j = c.get("/trend", params={**Q, "variable": "GLDAS_NOAH025_M/SWE_inst", "lens": "hydro"}).json()
    assert j["reliability"] == "ok" and j["significant"] and j["slope_per_decade"] < 0
    assert j["lens"] == "hydro"
    assert j["lens_message"] == (CFG["lenses"]["hydro"]["templates"]["GLDAS_NOAH025_M/SWE_inst"]["decreasing"]
                                 + " " + DISCLAIMER)
    assert j["lens_caveat"] == lenses.caveat("hydro") and "not river flow" in j["lens_caveat"]
    plain = c.get("/trend", params={**Q, "variable": "GLDAS_NOAH025_M/SWE_inst"}).json()
    assert plain["lens"] is None and plain["lens_message"] is None and plain["lens_caveat"] is None


def test_api_not_significant_lens_message(client):
    c, put = client
    put("WIND50M", "M2TMNXSLV/WIND50M", "m s-1", 5 + np.random.default_rng(1).normal(0, 0.3, 240))
    j = c.get("/trend", params={**Q, "variable": "M2TMNXSLV/WIND50M", "lens": "wind"}).json()
    assert not j["significant"] and j["lens_message"] == f"{NOT_SIG} {DISCLAIMER}"


def test_api_no_lens_message_when_reliability_low(client):
    c, put = client
    put("SWE_inst", "GLDAS_NOAH025_M/SWE_inst", "kg m-2",
        np.where(np.isin(IDX.month, [12, 1, 2]), np.linspace(1.0, 0.2, 240), 0.0))   # peak < 2 mm
    j = c.get("/trend", params={**Q, "variable": "GLDAS_NOAH025_M/SWE_inst", "lens": "hydro"}).json()
    assert j["reliability"] == "low" and j["lens_message"] is None
    assert j["verdict"] == "Not enough snow in this region to test a trend reliably"


def test_api_variable_not_in_lens_is_a_clear_error(client):
    c, put = client
    put("WIND50M", "M2TMNXSLV/WIND50M", "m s-1", np.full(240, 5.0))
    r = c.get("/trend", params={**Q, "variable": "M2TMNXSLV/WIND50M", "lens": "solar"})
    assert r.status_code == 400
    assert r.json()["detail"].startswith("Variable 'M2TMNXSLV/WIND50M' is not in the solar lens.")
    assert "M2TMNXRAD/SWGDN" in r.json()["detail"]
    r = c.get("/trend", params={**Q, "variable": "M2TMNXSLV/WIND50M", "lens": "nuclear"})
    assert r.status_code == 404 and "Unknown lens 'nuclear'" in r.json()["detail"]


def test_api_lens_filter_on_variables(client):
    c, _ = client
    for lid, expected in EXPECTED.items():
        assert [v["id"] for v in c.get("/variables", params={"lens": lid}).json()] == expected
    assert len(c.get("/variables").json()) > len(EXPECTED["solar"])          # no lens: everything
    assert c.get("/variables", params={"lens": "nuclear"}).status_code == 404


def test_api_lenses_endpoint(client):
    c, put = client
    put("WIND50M", "M2TMNXSLV/WIND50M", "m s-1", np.full(240, 5.0))
    out = {l["id"]: l for l in c.get("/lenses").json()}
    assert list(out) == ["solar", "wind", "hydro", "farming"]
    assert out["wind"]["variables"] == [{"id": "M2TMNXSLV/WIND50M", "has_data": True}]
    assert out["solar"]["variables"][0] == {"id": "M2TMNXRAD/SWGDN", "has_data": False}
    assert all(l["disclaimer"] == DISCLAIMER and l["caveat"] and l["default_variable"] for l in out.values())


def test_frontend_has_lens_selector_and_no_duplicate_demo_buttons():
    html = (common.ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="lens"' in html and "/lenses" in html and "lens_message" in html and "lens_caveat" in html
    assert html.count("Demo: ") == 1                            # one button template, one per preset
    assert "data not available yet" in html


# ---------------------------------------------------------------- page robustness and locale
# pytest cannot run the page's JavaScript (the behaviour was checked in a real browser); these pin
# the structure that makes it robust, and the server-side half of the locale problem.

def _page() -> str:
    return (common.ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_bbox_fields_are_text_inputs_not_locale_dependent_number_inputs():
    html = _page()
    for field in ("w", "s", "e", "n"):
        tag = next(l for l in html.splitlines() if f'id="{field}"' in l and "<input" in l)
        assert 'type="text"' in tag and 'inputmode="decimal"' in tag and "type=\"number\"" not in tag
    assert "type=\"number\"" not in html


def test_page_normalises_comma_decimals_and_fills_fields_with_dots():
    html = _page()
    assert ".replace(',', '.')" in html and "function parseCoord" in html
    assert "parseCoord" in html.split("async function run()")[1]          # used when building the request
    assert "function fmtCoord(x) { return String(x).trim().replace(',', '.'); }" in html   # written with dots
    assert "toLocaleString" not in html and "Intl.NumberFormat" not in html   # nothing locale-dependent
    assert "The region needs four numbers" in html                        # a bad value gets a message


def test_page_loads_variables_first_and_survives_a_missing_endpoint():
    html = _page()
    init = html.split("async function init()")[1].split("async function demo")[0]
    assert init.index("await loadVars()") < init.index("api('/lenses')") < init.index("api('/presets')")
    for what in ("Couldn't load variables - is the server running the latest code?",
                 "Couldn't load lenses", "Couldn't load the demo regions"):
        assert what in html
    assert '<button id="go" disabled>' in html and "function updateGo()" in html
    assert "$('go').disabled = !$('variable').value" in html


def test_comma_decimal_bbox_is_a_clear_400_not_a_crash(client):
    c, put = client
    put("WIND50M", "M2TMNXSLV/WIND50M", "m s-1", np.full(240, 5.0))
    for bad in ("-117,31,3,-109,38", "-117,31,3,-109,38,0"):                # "31,3" pasted unnormalised
        r = c.get("/trend", params={"variable": "M2TMNXSLV/WIND50M", "bbox": bad})
        assert r.status_code == 400 and "four numbers" in r.json()["detail"]
    ok = c.get("/trend", params={"variable": "M2TMNXSLV/WIND50M", "bbox": "-1,-1,1,1"})
    assert ok.status_code == 200


# ---------------------------------------------------------------- page <-> /lenses contract

def test_page_lens_code_matches_the_lenses_response_shape():
    """Every field the page reads from a /lenses entry exists in the real response."""
    import re
    html = _page()
    c = TestClient(__import__("app.main", fromlist=["app"]).app)
    body = c.get("/lenses").json()
    assert isinstance(body, list) and body
    used = set()
    script = html.split("<script>")[-1]
    for chunk in (script.split("async function init()")[1].split("async function demo")[0],
                  script.split("async function demo")[1].split("async function run")[0]):
        used |= set(re.findall(r"\bl\.(\w+)", chunk))                 # l = a lens entry
    assert {"id", "name", "description", "variables", "default_variable"} <= used
    for lens in body:
        assert used <= set(lens), used - set(lens)
        assert all({"id", "has_data"} <= set(v) for v in lens["variables"])   # page maps v.id, filters ready ids
    assert "lensList.find(l => l.id === id)" in html and "l.variables.map(v => v.id)" in html


def test_every_preset_lens_exists_in_the_lenses_response_and_in_the_presets_response():
    c = TestClient(__import__("app.main", fromlist=["app"]).app)
    lens_ids = {l["id"] for l in c.get("/lenses").json()}
    by_id = {l["id"]: l for l in c.get("/lenses").json()}
    presets_resp = c.get("/presets").json()
    assert presets_resp and all(p["lens"] in lens_ids for p in presets_resp)
    for p in presets_resp:                                              # what a demo button needs
        lens = by_id[p["lens"]]
        assert lens["default_variable"] in [v["id"] for v in lens["variables"]]
        assert c.get("/variables", params={"lens": p["lens"]}).json()    # the filtered list is non-empty


def test_demo_selects_region_lens_and_variable_together():
    demo = _page().split("async function demo")[1].split("async function run")[0]
    assert "$('lens').value = p.lens" in demo and "await loadVars(want)" in demo
    assert demo.index("$('lens').value = p.lens") < demo.index("await loadVars(want)") < demo.index("await run()")
    assert "setBounds(p.bbox)" in demo and demo.index("setBounds(p.bbox)") < demo.index("await loadVars(want)")


def test_presets_write_all_four_bounds_field_by_field():
    html = _page()
    assert "const BOUNDS = ['w', 's', 'e', 'n'];" in html               # bbox order: west, south, east, north
    body = html.split("function setBounds(bbox) {")[1].split("\n}")[0]
    assert "BOUNDS.forEach((id, i) => { $(id).value = fmtCoord(bbox[i]); });" in body
    assert "BOUNDS.every(" in body                                      # ... and reads them back
    assert "BOUNDS.map(id => parseCoord($(id).value))" in html.split("async function run()")[1]


def test_lens_load_failure_message_is_persistent_and_next_to_the_control():
    html = _page()
    assert 'id="lensStatus"' in html and "Couldn't load lenses" in html
    assert "$('lensStatus').textContent" in html.split("async function init()")[1]
    run = html.split("async function run()")[1].split("async function")[0]
    assert "lensStatus" not in run                                      # run() must not clear it


def test_favicon_request_is_not_a_404():
    r = TestClient(__import__("app.main", fromlist=["app"]).app).get("/favicon.ico")
    assert r.status_code == 204 and not r.content
