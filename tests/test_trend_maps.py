"""Synthetic-data tests for make_trend_maps.py (no data/processed needed)."""
import json

import numpy as np
import pandas as pd
import pytest

import make_trend_maps as tm
import stats

# matplotlib / shapely / pyogrio (requirements-maps.txt) are only needed to regenerate data/maps,
# not to run the app: without them, the tests that use them skip instead of failing.
MAPS_LIBS = "only needed to regenerate data/maps: pip install -r requirements-maps.txt"


def _have(module):
    try:
        __import__(module)
        return True
    except ImportError:
        return False


needs_matplotlib = pytest.mark.skipif(not _have("matplotlib"), reason=f"matplotlib not installed ({MAPS_LIBS})")
needs_shapely = pytest.mark.skipif(not (_have("shapely") and _have("pyogrio")),
                                   reason=f"shapely/pyogrio not installed ({MAPS_LIBS})")

TIMES = pd.date_range("2001-01", periods=240, freq="MS")
T = tm.decimal_years(TIMES)
MONTHS = TIMES.month.to_numpy()
SEASON = 5 * np.sin(2 * np.pi * (MONTHS - 1) / 12)


def ar1(rng, shape, phi=0.4):
    e = rng.normal(size=shape)
    for k in range(1, shape[-1]):
        e[..., k] += phi * e[..., k - 1]
    return e


def test_injected_slope_recovered_and_matches_app():
    rng = np.random.default_rng(1)
    true = np.array([0.0, 0.05, -0.08, 0.2, 0.5])          # per year
    y = true[:, None] * (T - T[0])[None, :] + SEASON[None, :] + 0.3 * ar1(rng, (5, 240))
    r = tm.trend_cells(tm.deseasonalize(y, MONTHS), T)
    assert np.allclose(r["slope"], true, atol=0.02)
    assert r["p"][-1] < 1e-6 and r["p"][-2] < 1e-4
    for c in range(5):                                      # identical to the app's own path
        a = stats.analyze(pd.Series(y[c], index=TIMES), deseasonalize=True)
        assert r["slope"][c] * 10 == pytest.approx(a["slope_per_decade"], rel=1e-12)
        assert r["p"][c] == pytest.approx(a["p_value"], abs=1e-12)
        assert r["inflation"][c] == pytest.approx(a["variance_inflation"], rel=1e-12)


def test_ties_match_app():
    rng = np.random.default_rng(2)
    y = np.round(rng.normal(size=(3, 120)), 1)              # many ties
    t = T[:120]
    r = tm.trend_cells(y, t)
    for c in range(3):
        p, infl = stats.mann_kendall(y[c])
        assert r["p"][c] == pytest.approx(p, abs=1e-12)


def test_pure_noise_raw_rate_and_fdr():
    rng = np.random.default_rng(3)
    y = rng.normal(size=(2000, 120))
    r = tm.trend_cells(y, T[:120])
    raw = np.mean(r["p"] < 0.05)
    assert 0.025 < raw < 0.08                               # about the nominal 5%
    assert tm.bh_fdr(r["p"], 0.10).mean() < 0.005           # near zero after FDR


def test_bh_fdr_known_case_and_nan():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, np.nan])
    # m = 8 tested; thresholds 0.05*k/8: 0.00625, 0.0125, 0.01875, 0.025, ...
    assert tm.bh_fdr(p, 0.05).tolist() == [True, True] + [False] * 7
    # step-up: at q=0.1 the largest k with p_(k) <= 0.1 k/8 is k=7 (0.074 <= 0.0875), so 0.06 passes too
    assert tm.bh_fdr(p, 0.10).tolist() == [True] * 7 + [False] * 2
    assert not tm.bh_fdr(np.array([np.nan, np.nan])).any()


@needs_shapely
def test_us_mask_points():
    poly = tm.contiguous_us()
    assert poly is not None
    lats = np.array([38.5, 30.0, 43.7, 19.4, 45.0])
    lons = np.array([-98.0, -140.0, -79.4, -99.1, -100.0])
    m = tm.us_mask(lats, lons, poly)
    diag = np.diag(m)
    # Kansas in; Pacific out; Toronto out; Mexico City out; South Dakota in
    assert diag.tolist() == [True, False, False, False, True]


def test_land_fraction_aggregates_fine_grid():
    lats = np.array([1.0, 0.0])                             # target 1-degree cells, north first
    lons = np.array([0.0, 1.0])
    fl = np.arange(-0.375, 1.5, 0.25)                       # 0.25-degree centres covering both cells
    land = np.zeros((fl.size, fl.size), bool)
    land[:, fl < 0.5] = True                                # western target column all land
    land[fl < 0.5, :] |= False
    frac = tm.land_fraction(lats, lons, fl, fl, land)
    assert frac[:, 0].tolist() == [1.0, 1.0] and frac[:, 1].tolist() == [0.0, 0.0]


@needs_matplotlib
def test_compute_and_write_outputs(tmp_path):
    rng = np.random.default_rng(4)
    ny, nx = 4, 5
    slope = np.linspace(-0.1, 0.1, ny * nx).reshape(ny, nx)
    vals = (slope[None] * (T - T[0])[:, None, None] + SEASON[:, None, None]
            + 0.05 * rng.normal(size=(240, ny, nx)))
    vals[:, 0, 0] = np.nan                                  # no data
    vals[10, 1, 1] = np.nan                                 # one gap -> exact fallback path
    mask = np.ones((ny, nx), bool)
    mask[3, 4] = False                                      # outside the US
    res = tm.compute_grid(vals, TIMES, mask)
    assert not res["tested"][0, 0] and not res["tested"][3, 4] and res["tested"][1, 1]
    assert res["n_gap_cells"] == 1
    assert np.allclose(res["slope"][res["tested"]], 10 * slope[res["tested"]], atol=0.02)

    entry = {"id": "TEST/X", "name": "Test value", "units": "K", "display_units": "degC",
             "short_name": "TEST", "version": "1"}
    lats, lons = np.array([49.5, 49.0, 48.5, 48.0]), np.array([-120.0, -119.4, -118.8, -118.2, -117.6])
    meta = tm.write_variable(entry, "X", res, lats, lons, tmp_path, masked="test mask")
    for f in ("X.png", "X.json", "X_cells.json"):
        assert (tmp_path / f).exists()
    m = json.loads((tmp_path / "X.json").read_text())
    for k in ("bounds", "grid", "units", "display_units", "slope_units", "scale", "period", "method",
              "autocorrelation_method", "fdr_level", "n_significant_fdr", "percent_significant_fdr",
              "source", "description", "mask"):
        assert k in m, k
    assert m["scale"]["min"] == -m["scale"]["max"]
    assert m["bounds"]["north"] == pytest.approx(49.75) and m["bounds"]["west"] == pytest.approx(-120.3)
    cells = json.loads((tmp_path / "X_cells.json").read_text())
    flag = cells["flag"]
    assert len(flag) == ny * nx and set(flag) <= set("-01")
    assert flag[0] == "-" and flag[ny * nx - 1] == "-"            # no data / outside the US
    assert len(cells["slope"]) == len(cells["p"]) == sum(c != "-" for c in flag) == res["tested"].sum()
    k = sum(c != "-" for c in flag[:6])                         # cell (1, 1) -> k-th listed value
    assert cells["slope"][k] == pytest.approx(res["slope"][1, 1], rel=1e-2)
    assert (flag.count("1")) == m["n_significant_fdr"]

    import matplotlib.image
    img = (matplotlib.image.imread(tmp_path / "X.png") * 255).round().astype(int)
    assert img.shape == (ny, nx, 4)
    assert img[0, 0, 3] == 0 and img[3, 4, 3] == 0          # masked / no data: transparent
    a = img[..., 3][res["tested"]]
    assert set(np.unique(a)) <= {tm.ALPHA_SIG, tm.ALPHA_NONSIG}

    tm.write_index(tmp_path, {"file": "us_outline.geojson"})
    import yaml
    idx = yaml.safe_load((tmp_path / "index.yml").read_text())
    assert idx["variables"][0]["key"] == "X" and idx["boundaries"]["file"] == "us_outline.geojson"
