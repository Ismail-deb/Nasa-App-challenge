# Progress report: Earth System Trend Detective

_Last updated: 2026-11-14_

## Where we are
Step 1 is working: the vertical slice for MERRA-2 2 m temperature, from NASA download through to a
chart and result card. The data layer for the other categories is built and tested. Lenses, the
globe and the other variables' display conversions are not started.

## Done
**Repo and setup**
- README, `.gitignore` (data, credentials, caches, venv).
- Earthdata login via `_netrc`, which sits outside the repo.

**Catalog (`catalog.yml`, `check_catalog.py`)**
- `catalog.yml` covers all 5 categories, with plain-language descriptions and honest proxy notes
  (GLDAS runoff is not river flow; reanalysis wind is indicative).
- `check_catalog.py` found every NASA-sourced entry on NASA's servers and confirmed variable names
  and units. Corrections it led to: IMERG units (`mm/hr`), the IMERG `Grid` group, GLDAS pinned to
  version 2.1 (2.0 stops in 2014).
- Still `planned` (need other archives or a decision): heavy-rain days, groundwater, the 3 ocean
  variables.

**Statistics (`stats.py`)**
- Sen's slope per decade with a confidence interval, Mann-Kendall p-value, 0.05 significance flag,
  optional seasonal-cycle removal.
- Tests: known trend, pure noise, missing months.

**Backend and frontend**
- FastAPI: `/categories`, `/variables`, `/timeseries`, `/trend`.
- Regional means are cos(latitude)-weighted; boxes crossing the antimeridian or smaller than one
  grid cell are handled; K converts to °C.
- Page: variable dropdown with description, bounding-box and date controls, Plotly chart with trend
  line, result card, US Southwest demo button.

**Data pipeline**
- `pull_data.py`: downloads each granule once even when several variables share it, keeps native
  resolution, writes incrementally in 12-month blocks (low RAM), masks fill values, computes wind
  speed from U50M/V50M.
- `fetch_data.py` downloads finished files from a GitHub Release.
- Test pulls of IMERG and GLDAS worked on real files.

**Real result:** T2M for the US Southwest, 2000-2026: **+0.49 °C per decade** (95% range +0.28 to
+0.69, p < 0.001, significant).

**Tests:** 12 pass, all offline.

## Not yet done
- Lenses: `lenses.yml`, interpretation templates, the lens sentence on the result card.
- Globe region selection, `/lenses`, filter by lens and category.
- Display conversions for new variables (e.g. evaporation to mm/day).
- Demo scenario buttons beyond the Southwest.
- Data for the 4 pullable categories (desktop job).
- Browser testing of the page.

## Open risks
1. **IMERG file size:** a 12-month test measured 12 MB per month at native 0.1°, so the full
   2000-2025 record is about 3.7 GB, over GitHub's 2 GB per-file Release limit. GLDAS is about
   0.8 MB per month per variable.
2. **Autocorrelation:** monthly data is autocorrelated, so Mann-Kendall p-values can be somewhat
   optimistic. Seasonal removal is on by default.
3. **Different record lengths:** MERRA-2 runs to 2026-09, IMERG ends 2025-09, GLDAS 2.1 has 319
   granules. The app should show each variable's real period.
4. **Windows DLL block:** `netCDF4` is blocked on the laptop, so everything uses `h5netcdf`.

## Next
1. Pull each category on the desktop and publish a Release.
2. `fetch_data.py` on the laptop, then build lenses and the globe.
