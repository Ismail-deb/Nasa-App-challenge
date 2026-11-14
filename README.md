# Earth System Trend Detective

NASA Space Apps Challenge project. Pick an Earth-science variable measured by NASA missions or models, pick a region and time period, and see **what is changing, where, by how much, and whether the change is statistically significant**. A secondary "lens" layer translates results for renewable-energy providers and farmers (long-term regional screening only).

> Status: **Step 1 (vertical slice)** – MERRA-2 monthly 2 m temperature (T2M) for one demo region. Other categories, lenses and the globe come after Step 1 is confirmed.

## Setup

Requires Python 3.11+.

```
python -m venv venv
venv\Scripts\activate          # Windows  (source venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
```

### NASA Earthdata credentials
Create a free account at https://urs.earthdata.nasa.gov, then provide credentials **either** via environment variables
`EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD`, **or** a `~/.netrc` (`_netrc` on Windows) file:

```
machine urs.earthdata.nasa.gov login <user> password <pass>
```
Credentials are never stored in this repo (`.env`, `.netrc` are git-ignored).

## Data workflow

The running app never calls NASA. It reads pre-processed files in `data/processed/` (git-ignored).
MERRA-2 and GLDAS are kept at **native resolution**. IMERG precipitation is the one exception (below).

### IMERG coarsening (0.1° → 0.5°)
At native 0.1° the full IMERG record (~309 months) would be ~3.7 GB, over GitHub's 2 GB
per-file Release limit. `pull_data.py` therefore block-averages IMERG 5×5 cells into 0.5° cells
before writing (~150 MB). The mean is NaN-aware: a block keeps the mean of its valid cells and
stays NaN only if all 25 cells are missing. Use `--native` to keep 0.1°, or `--coarsen N` to change it.

Effect on regional means, measured on two real IMERG months (Jan and Jul 2023), boxes whose edges
do not line up with the 0.5° grid:

| Box size | Difference vs native 0.1° |
|---|---|
| Large (e.g. Great Plains, ~12°×12°) | 0.1–0.5% |
| State-sized (~5°×5°, e.g. US Southwest, Central Valley) | 0.2–6% |
| 1°×1° | 6–11% |
| 0.4°×0.4° (smaller than one 0.5° cell) | 13–34% |

So regional means are barely affected for the region sizes this app is designed for, but IMERG
results for boxes of about 1° or smaller should be treated with caution. The difference comes from
box edges cutting through 0.5° cells; it is largely the same every month, so trends are expected
to be affected less than absolute values (not yet measured).

```
python check_catalog.py                    # verify catalog.yml against NASA (needs credentials)
python pull_data.py atmosphere_solar       # also: weather_climate, hydrology, cryosphere
python -m pytest                           # unit tests (offline)
uvicorn app.main:app --reload              # then open http://127.0.0.1:8000
```

`pull_data.py` extracts the needed variables from each monthly granule and writes the result
incrementally (low RAM). Existing outputs are skipped; use `--force` to redo, `--start/--end`
(YYYY-MM) to limit the period. Exit code: 0 ok, 3 finished with gaps, 1 error.
`check_catalog.py` prints real variable names/units.

### Raw granule cache and resuming
Raw granules are kept in `data/raw/<collection>/` (git-ignored), so `weather_climate` and
`atmosphere_solar` share the MERRA-2 SLV downloads, and `hydrology` and `cryosphere` share GLDAS.
If a run is stopped, just run the same command again: cached granules are reused and only the
missing ones are downloaded. A cached file is trusted only if its size matches NASA's metadata and
every needed variable reads cleanly; a partial or corrupted file is deleted and re-downloaded.
`--cleanup` deletes the cache of the collections a category uses, after a run with no gaps.

Disk space for the cache (2000-2026, approximate): MERRA-2 SLV 17 GB, RAD 12 GB, AER 19 GB,
GLDAS 8 GB, IMERG 5 GB, about 60 GB if nothing is cleaned up.

### Running two pulls at once
`run_stream1.ps1` (MERRA-2 categories) and `run_stream2.ps1` (GLDAS/IMERG categories) can run at
the same time in two terminals. Each category writes its own output files (a test checks that no
two catalog entries share a file). All writes are atomic: downloads go to a private temp folder
(`.dl-<pid>-<random>`) and processed files to `<name>.part-<pid>-<random>`, and each is renamed
into place only when complete, so a reader never sees a half-written file and two runs never
write the same temp file. Temp leftovers from a killed run are removed after 12 hours.

```
# terminal 1                                              # terminal 2
powershell -ExecutionPolicy Bypass -File .\run_stream1.ps1   powershell -ExecutionPolicy Bypass -File .\run_stream2.ps1
```
Each category logs to `logs\pull_<category>.log` (git-ignored); watch one with
`Get-Content logs\pull_hydrology.log -Wait`. If a category fails, the script records it and moves
on, then prints a SUCCESS/FAILURE line per category. Re-running the same script resumes: finished
categories are skipped and cached granules are reused. Add `-Cleanup` to delete the raw caches
once every category in that stream has succeeded.

### Preset demo regions (works without the big data)
`presets.yml` defines four demo regions, each with a recommended lens:

| Preset | Box (W, S, E, N) | Lens |
|---|---|---|
| `southwest`: Arizona and southern Nevada | -117.0, 31.3, -109.0, 38.0 | solar |
| `great_plains`: Texas to Iowa | -103.0, 30.0, -91.0, 43.5 | wind |
| `pacific_northwest`: US Columbia basin | -124.0, 42.0, -111.0, 49.0 | hydro |
| `central_valley`: California Central Valley | -122.6, 35.0, -118.8, 40.6 | farming |

`python export_series.py` computes each preset's monthly regional mean from the gridded files
(using the backend's own function) and writes small CSVs plus `index.yml` to `data/series/`, which
**is committed to git** (about 9 KB per series). Re-run it after new gridded files arrive; on a
machine without some gridded files it skips them and keeps the series exported elsewhere.

`/trend` serves a request whose box matches a preset (within 0.05°) from `data/series/`, anything
else from the gridded files, and otherwise answers "Region/variable not available yet, try a
preset". `GET /presets` lists the presets, their lens and the variables ready for each. So a fresh
clone can run the demo for the preset regions with no NASA download at all.

### Moving data between machines
Pull on a fast machine, then publish the processed files as a GitHub Release (not in git history):

```
winget install GitHub.cli ; gh auth login
gh release create data-v1 data/processed/*.nc --title "Processed data v1" --notes "Native-resolution monthly data"
# later additions:  gh release upload data-v1 data/processed/NEWFILE.nc --clobber
```
On any other machine: `python fetch_data.py` (no NASA account needed). GitHub limits each
release file to under 2 GB.

## Architecture (text)

- `catalog.yml` – variables, grouped in 5 categories, with plain-language descriptions.
- `check_catalog.py` – searches NASA CMR via `earthaccess`; reports what resolves and the real variable names/units.
- `pull_data.py` – downloads monthly granules and writes compact NetCDF to `data/processed/`. The running app never downloads from NASA.
- `stats.py` – Sen's slope per decade, autocorrelation-corrected Mann-Kendall p-value (pymannkendall), optional seasonal-cycle removal.
- `app/main.py` – FastAPI: cos(lat) area-weighted regional means, unit conversion, `/trend`.
- `web/index.html` – single page with Plotly chart and result card.

## Statistical method

**How big is the change?** We draw the trend line with *Sen's slope*: the middle value of the
slopes between every pair of months. One freak month cannot drag it around, unlike an ordinary
best-fit line. It is reported per decade, with a **95% range (adjusted for autocorrelation)**:
the span of slopes that fit the data reasonably well.

**Is the change real?** Weather wobbles from month to month, so even a region with no long-term
change will show some slope by luck. The *Mann-Kendall test* asks: if there were no real trend,
how often would wobbles alone produce a trend this consistent? That chance is the **p-value**.
When it is below 0.05 (less than 1 in 20) we call the trend "significant". A p-value is *not* the
chance that the trend is wrong, and "not significant" does not mean "no change"; it means the
record is too short or too noisy to tell yet.

**The correction for autocorrelation.** *Autocorrelation* means each month tends to resemble the
month before it: a warm, dry spell often lasts for several months. The basic test assumes every
month is a fresh, independent measurement, so it treats 300 months as 300 separate pieces of
evidence when they are really fewer, and it becomes overconfident. We use the *Hamed-Rao*
correction: it measures how strongly each month resembles the previous 1 to 4 months and widens
the uncertainty to match. The same adjustment is applied to both the p-value and the 95% range.

How well it works, checked on 200 computer-made series that have this month-to-month memory but
**no** trend:

| | Basic test | Corrected (what the app uses) |
|---|---|---|
| False alarms ("significant" when there is no trend; target 5%) | 31% | 7% |
| 95% range contains the true slope (target 95%) | 69% | 93% |

With a real trend added, the corrected test still detected it 82% of the time (basic test: 96%,
but the basic test also cries wolf far more often). On series with no month-to-month memory the
correction usually changes nothing. Example: for 2 m temperature over the US Southwest
(31-37°N, 115-109°W, 2000-2026) the trend is +0.49 °C per decade either way; the 95% range widens from +0.28 to +0.69
to **+0.25 to +0.72**, and the trend stays significant (p = 0.00005). `method=plain` in the API
selects the basic test; the unadjusted range is also returned as `ci_plain_low/high_per_decade`.

**Limitations.**
- The corrected test is still slightly generous: about 7% false alarms instead of 5%, and more for
  very persistent data or records shorter than about 10 years.
- A straight line is a simplification: it cannot describe a change that speeds up, reverses, or
  happens as a sudden step.
- Slow natural cycles lasting years (such as El Niño) can look like a trend in a short record.
- Removing the seasonal cycle (on by default) matters: without it, the yearly swing swamps the test.
- A significant trend says the change is unlikely to be chance. It does not say what caused it.

## Data sources
- NASA GES DISC, accessed with `earthaccess`: MERRA-2 `M2TMNXSLV` (temperature, 50 m wind),
  GPM IMERG `GPM_3IMERGM` v07 (precipitation), GLDAS Noah `GLDAS_NOAH025_M` v2.1 (soil moisture).

## Limitations
- Monthly data only; linear trends (Sen's slope) over a limited record.
- Reanalysis (MERRA-2) is model output assimilating observations – indicative, not station truth.
- Regional screening only; not site-level feasibility or irrigation scheduling.
- **Wind:** this is 50 m wind speed computed from monthly-mean wind components (speed of the mean
  vector); it underestimates average wind speed and is useful for relative change over time, not
  for absolute wind resource. Because winds change direction during a month, the mean vector is
  shorter than the average speed; the preset regions show about 2-3 m/s, well below real 50 m
  averages. Do not use these values to size turbines or estimate energy yield.
- **Soil moisture** (GLDAS) is a land-surface model estimate driven by observations, not a direct
  measurement, averaged over the whole region; shown in kg/m², the same as mm of water in the top 10 cm.
- **Different record lengths:** each variable ends when its NASA product does. Currently
  temperature and wind run 2000-01 to 2026-09, soil moisture to 2026-07, and precipitation to
  2025-09 (IMERG's final product lags by about a year). The app shows each variable's real period;
  trends for different variables cover slightly different years.

## Credits
- Data: NASA GES DISC / Earthdata. MERRA-2: GMAO, NASA.
- Learning material: NASA GES DISC tutorials, https://github.com/nasa/gesdisc-tutorials (read-only reference; not modified or included).
