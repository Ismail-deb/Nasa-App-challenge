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

`pull_data.py` downloads each monthly granule once (shared across variables of the same
collection), extracts the needed variables, deletes the raw file, and writes the result
incrementally (low RAM). Existing outputs are skipped; use `--force` to redo, `--start/--end`
(YYYY-MM) to limit the period. `check_catalog.py` prints real variable names/units.

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
