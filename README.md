# Climate Data Harmonization Agent

Autonomous pipeline for acquiring, harmonizing, validating, and diagnosing climate datasets across East Africa — built for impact modelling at ILRI Climate Services.

---

## Purpose

Impact modellers working on food security, livestock productivity, and drought risk in East Africa need consistent, analysis-ready climate grids that span both the observed past and projected future. Producing those grids from raw sources (ERA5-based reanalysis, CHIRPS rainfall, ISIMIP multi-model projections) involves dozens of steps — merging fragmented yearly files, regridding to a common resolution, masking by country boundary, validating units and temporal coverage — repeated across multiple countries, variables, and scenarios.

This agent automates the entire sequence. A single command specifies what you need (country, variable, scenario, year range); the agent plans the DAG, downloads missing source data, runs the processing pipeline, validates every output, and saves a structured manifest of everything that happened.

---

## Supported Domain

| Dimension  | Values |
|------------|--------|
| Countries  | Ethiopia (`eth`), Kenya (`ken`), Somalia (`som`) |
| Variables  | `tas` (temperature, K), `rh` (relative humidity, %), `vpd` (vapour pressure deficit, hPa), `pr` (precipitation, mm/day) |
| Scenarios  | `historical`, `ssp245`, `ssp585` |
| Resolution | 0.25° final output grid |
| Period     | Any contiguous year range within available source data |

---

## Architecture — Four Planes

```
┌─────────────────────────────────────────────────────────────┐
│  Control Plane          agent/router.py · agent/planner.py  │
│  Parse request → select workflow template → build DAG        │
├─────────────────────────────────────────────────────────────┤
│  Data Plane             connectors/ · scripts/              │
│  Download → merge → regrid → clip (subprocess calls only)   │
├─────────────────────────────────────────────────────────────┤
│  Quality Plane          validation/                         │
│  Schema · time · spatial · anomaly checks after each stage  │
├─────────────────────────────────────────────────────────────┤
│  Observability Plane    agent/state_store.py · runs/        │
│  Run manifest · per-stage logs · QA diagnostics             │
└─────────────────────────────────────────────────────────────┘
```

### Key modules

| Module | Role |
|--------|------|
| `agent/router.py` | Maps a request to a workflow template (historical / projection / future_vpd / diagnostics) |
| `agent/planner.py` | Builds the ordered DAG of pipeline stages with explicit dependencies |
| `agent/orchestrator.py` | Executes the DAG via `subprocess.run()`, handles retry, validation, and manifest recording |
| `agent/policy.py` | Naming rules, compression levels, retry backoff, fast-mode skip list |
| `agent/state_store.py` | Reads/writes run manifests; powers idempotent `--resume` |
| `agent/artifact_manager.py` | Single source of truth for all file paths — never hardcoded elsewhere |
| `agent/preflight.py` | Checks packages, scripts, boundaries, and source data before any stage runs |
| `connectors/agera5_connector.py` | Command builder for AgERA5 downloads |
| `connectors/chirps_connector.py` | Command builder for CHIRPS downloads |
| `connectors/isimip_connector.py` | Command builder for ISIMIP projection data |
| `validation/schema_checks.py` | Variable presence, units, non-NaN coverage |
| `validation/time_checks.py` | Time coverage, daily axis continuity |
| `validation/spatial_checks.py` | Grid match, spatial bounds, cross-file grid consistency |
| `validation/anomaly_checks.py` | Outlier detection, flat/saturated field detection |

---

## Workflow Templates

### Historical (AgERA5 + CHIRPS)
```
Download missing source years → Merge yearly files → Regrid to 0.05° reference
→ Clip time window → Clip by country shapefile → Validate → Diagnostics
```

### Projection (ISIMIP SSP245 / SSP585)
```
Locate ISIMIP source → Rename variables / regrid → Clip time window
→ Aggregate hourly→daily if needed → Clip by shapefile → Validate → Diagnostics
```

### Future VPD (derived)
```
Resolve projected tas + rh inputs → Compute VPD via Tetens equation
vpd = 6.1078 × exp(17.27×T / (T + 237.3)) × (1 − rh/100)   [T in °C, result in hPa]
→ Write with metadata → Validate → Diagnostics
```

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/YonSci/climate-agent.git
cd climate-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure CDS API credentials

AgERA5 downloads require a Copernicus Climate Data Store account. Place your key in `~/.cdsapirc`:

```
url: https://cds.climate.copernicus.eu/api/v2
key: <YOUR_UID>:<YOUR_API_KEY>
```

### 3. Run the agent

**Historical — Ethiopia temperature + precipitation, 2010–2025:**
```bash
python run_agent.py \
    --countries eth \
    --variables tas pr \
    --scenario historical \
    --period 2010 2025 \
    --diagnostics
```

**Projection — Kenya and Somalia all variables, SSP2-4.5:**
```bash
python run_agent.py \
    --countries ken som \
    --variables tas rh vpd pr \
    --scenario ssp245 \
    --period 2040 2070 \
    --diagnostics
```

**Fast mode (skip expensive grid checks), 4 parallel workers:**
```bash
python run_agent.py \
    --countries eth ken som \
    --variables tas rh \
    --scenario historical \
    --period 1981 2023 \
    --mode fast \
    --workers 4
```

**Dry run — print planned commands without executing:**
```bash
python run_agent.py \
    --countries eth \
    --variables tas \
    --scenario ssp585 \
    --period 2050 2100 \
    --dry-run
```

**Resume a failed run:**
```bash
python run_agent.py \
    --countries eth ken \
    --variables tas rh pr vpd \
    --scenario historical \
    --period 1981 2023 \
    --resume run_20260506_143000
```

**Inspect a completed run:**
```bash
python run_agent.py --validate-run run_20260506_143000
python run_agent.py --validate-run run_20260506_143000 --checks   # show per-check detail
```

---

## CLI Reference

| Flag | Required | Description |
|------|----------|-------------|
| `--countries` | Yes | One or more of `eth` `ken` `som` |
| `--variables` | Yes | One or more of `tas` `rh` `vpd` `pr` |
| `--scenario` | Yes | `historical` · `ssp245` · `ssp585` |
| `--period` | Yes | Start and end year, e.g. `--period 2010 2025` |
| `--mode` | No | `strict` (default) or `fast` |
| `--workers` | No | Parallel thread count (default: 1) |
| `--diagnostics` | No | Produce QA plots and `run_report.json` |
| `--dry-run` | No | Print planned stages without executing |
| `--resume RUN_ID` | No | Skip stages already marked SUCCESS in a prior manifest |
| `--skip-preflight` | No | Bypass environment checks (not recommended) |
| `--log-level` | No | `DEBUG` · `INFO` (default) · `WARNING` · `ERROR` |
| `--validate-run [ID]` | No | Summarise a completed run manifest; early-exit mode |

---

## Output Layout

```
data/
├── raw/
│   ├── agera5/{variable}/{variable}_agera5_{YYYY}.nc
│   ├── chirps/chirps_v2.0_{YYYY}.days_p05.nc
│   └── isimip/{model}/{scenario}/{variable}/...
├── intermediate/{country}/{variable}/
│   └── {variable}_{country}_{source}_merged_{start}-{end}.nc
├── final/{country}/{scenario}/{variable}/
│   └── {variable}_{country}_{scenario}_{start}-{end}_0p25deg.nc
└── diagnostics/{run_id}/
    ├── {country}_{scenario}_{variable}_qa.png
    └── run_report.json

runs/
├── manifests/{run_id}.json
└── logs/{run_id}.log
```

---

## Validation

Every pipeline stage is validated before the next one starts. Results are recorded in the run manifest.

| Check | Strict | Fast |
|-------|--------|------|
| File exists, size > 0 | ✓ | ✓ |
| Expected variable present | ✓ | ✓ |
| Units match canonical value | ✓ | ✓ |
| Time coverage (no gaps) | ✓ | ✓ |
| Daily axis continuity | ✓ | ✓ |
| ≥ 80% non-NaN land pixels | ✓ | ✓ |
| Grid match (lat/lon vs reference) | ✓ | — |
| Spatial bounds within shapefile ± 0.5° | ✓ | — |
| Cross-file grid consistency | ✓ | — |
| Outlier / anomaly detection | warn | warn |
| Flat/saturated field detection | warn | warn |

On validation failure the agent retries the failed slice, falls back to legacy naming variants, and marks the slice `FAILED` in the manifest if still unresolved — other slices continue.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Array / NetCDF | xarray, numpy, netCDF4, h5netcdf, dask |
| Spatial processing | geopandas, rioxarray, shapely, pyproj, fiona |
| Climate data download | cdsapi (Copernicus CDS) |
| Visualization | matplotlib, cartopy |
| Configuration | PyYAML |
| Manifest validation | jsonschema |
| Progress reporting | tqdm |
| Testing | pytest, pytest-cov |
| CI | GitHub Actions |

---

## Project Structure

```
climate-agent/
├── run_agent.py                 ← entry point
├── agent_config.yaml            ← runtime configuration
├── run_manifest_schema.json     ← manifest JSON schema
├── requirements.txt
│
├── agent/                       ← Control + Observability planes
│   ├── router.py
│   ├── planner.py
│   ├── orchestrator.py
│   ├── policy.py
│   ├── state_store.py
│   ├── artifact_manager.py
│   ├── preflight.py
│   └── output_resolver.py
│
├── connectors/                  ← Data Plane: download command builders
│   ├── agera5_connector.py
│   ├── chirps_connector.py
│   └── isimip_connector.py
│
├── validation/                  ← Quality Plane: check functions
│   ├── schema_checks.py
│   ├── time_checks.py
│   ├── spatial_checks.py
│   └── anomaly_checks.py
│
├── scripts/                     ← Deterministic processing tools (black-box)
│   ├── run_historical_workflow.py
│   ├── run_projection_workflow.py
│   ├── run_future_vpd_workflow.py
│   ├── agera5_download.py
│   ├── download_chirps.py
│   └── ...
│
├── boundaries/                  ← Country shapefiles (read-only)
│   ├── ethiopia_adm0.geojson
│   ├── kenya_adm0.geojson
│   └── somalia_adm0.geojson
│
└── tests/                       ← 426 unit + integration tests
    ├── test_validation_engine.py
    ├── test_orchestrator.py
    ├── test_preflight.py
    └── ...
```

---

## Configuration

All runtime knobs live in [`agent_config.yaml`](agent_config.yaml). Key sections:

- **`paths`** — base directories for raw, intermediate, final, and diagnostic data
- **`validation`** — mode (`strict`/`fast`), coverage thresholds, grid tolerance
- **`retry`** — max attempts and backoff schedule
- **`compression`** — zlib levels for intermediate vs final outputs
- **`parallel`** — max worker threads
- **`cds`** — CDS API endpoint and timeout

---

## Running Tests

```bash
pytest tests/ -q                  # all 426 tests
pytest tests/ -q --cov=agent      # with coverage report
pytest tests/test_validation_engine.py -v   # single module
```

---

## Data Sources

| Source | Variable | Provider |
|--------|----------|----------|
| [AgERA5](https://cds.climate.copernicus.eu/cdsapp#!/dataset/sis-agrometeorological-indicators) | `tas`, `rh`, `vpd` | Copernicus / ECMWF |
| [CHIRPS v2.0](https://www.chc.ucsb.edu/data/chirps) | `pr` | UCSB Climate Hazards Center |
| [ISIMIP3b](https://www.isimip.org/) | `tas`, `rh`, `pr` (projections) | ISIMIP Consortium |

---

## Owner

**ILRI Climate Services (Livestock, Climate and Environment)** — Yonas Mersha  
Questions and data requests: [Y.Mersha@cgiar.org](mailto:Y.Mersha@cgiar.org)
