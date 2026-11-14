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
- `stats.py` – Sen's slope per decade, Mann-Kendall p-value (pymannkendall), optional seasonal-cycle removal.
- `app/main.py` – FastAPI: cos(lat) area-weighted regional means, unit conversion, `/trend`.
- `web/index.html` – single page with Plotly chart and result card.

## Data sources
- NASA GES DISC, MERRA-2 `M2TMNXSLV` (monthly single-level diagnostics), accessed with `earthaccess`.

## Limitations
- Monthly data only; linear trends (Sen's slope) over a limited record.
- Reanalysis (MERRA-2) is model output assimilating observations – indicative, not station truth.
- Regional screening only; not site-level feasibility or irrigation scheduling.

## Credits
- Data: NASA GES DISC / Earthdata. MERRA-2: GMAO, NASA.
- Learning material: NASA GES DISC tutorials, https://github.com/nasa/gesdisc-tutorials (read-only reference; not modified or included).
