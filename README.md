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

## Run (Step 1)

```
python check_catalog.py --only M2TMNXSLV   # verify the catalog entry against NASA
python pull_data.py weather_climate        # download + process to data/processed/
python -m pytest                           # stats unit tests
uvicorn app.main:app --reload              # then open http://127.0.0.1:8000
```

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
