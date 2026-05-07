# Climate Data Processing Agent — CLAUDE.md

> This file is the authoritative reference for Claude Code when working on this project.
> Read it fully before touching any file, running any command, or proposing any change.

---

## 1. Project Identity

**Name:** Climate Data Harmonization Agent
**Owner:** ILRI Climate Services (Yonas Mersha)
**Purpose:** Autonomous orchestration of climate data acquisition, harmonization, validation,
and diagnostics for East Africa impact modelling.
**Supported countries:** Ethiopia (`eth`), Kenya (`ken`), Somalia (`som`)
**Supported scenarios:** `historical`, `ssp245`, `ssp585`
**Supported variables:** `tas` (temperature), `rh` (relative humidity), `vpd`
(vapour pressure deficit), `pr` (precipitation)

---

## 2. Repository Layout

```
climate-agent/
│
├── CLAUDE.md                        ← YOU ARE HERE — read before anything else
├── agent_config.yaml                ← runtime knobs (paths, flags, policies)
├── run_manifest_schema.json         ← JSON schema for run manifests
├── requirements.txt                 ← pinned Python dependencies
│
├── agent/                           ← agent source (Control + Observability planes)
│   ├── __init__.py
│   ├── router.py                    ← Task Router: maps request → workflow template
│   ├── planner.py                   ← builds DAG of pipeline steps
│   ├── orchestrator.py              ← executes DAG, manages dependencies
│   ├── policy.py                    ← naming rules, compression, retry, fast-mode
│   ├── state_store.py               ← run manifest, fingerprints, checkpoints
│   └── artifact_manager.py          ← raw / intermediate / final / diagnostics paths
│
├── connectors/                      ← Source Connectors (Data Plane)
│   ├── agera5_connector.py          ← wraps agera5_download.py
│   ├── chirps_connector.py          ← wraps download_chirps.py
│   └── isimip_connector.py          ← ISIMIP projection source handler
│
├── validation/                      ← Validation Engine (Quality Plane)
│   ├── schema_checks.py             ← variable names, units, coordinate names
│   ├── time_checks.py               ← coverage, daily axis, missing periods
│   ├── spatial_checks.py            ← grid match, bounds after clipping
│   └── anomaly_checks.py            ← outlier detection, climatology comparison
│
├── scripts/                         ← EXISTING deterministic tools — DO NOT REWRITE
│   ├── agera5_download.py
│   ├── download_chirps.py
│   ├── inspect_netcdf_collection.py
│   ├── merge_netcdf_ethiopia_relative_humidity.py
│   ├── merge_netcdf_ethiopia_temperature.py
│   ├── merge_netcdf_ethiopia_vapour_pressure_deficit.py
│   ├── merge_netcdf_kenya_relative_humidity.py
│   ├── merge_netcdf_kenya_temperature.py
│   ├── merge_netcdf_kenya_vapour_pressure_deficit.py
│   ├── merge_netcdf_somalia_relative_humidity_mean.py
│   ├── merge_netcdf_somalia_temperature.py
│   ├── merge_netcdf_somalia_vapour_pressure_deficit.py
│   ├── rename_and_regrid_netcdf.py
│   ├── clip_netcdf_time_range.py
│   ├── clip_netcdf_by_shapefile.py
│   ├── hourly_to_daily_netcdf.py
│   ├── run_historical_workflow.py
│   ├── run_projection_workflow.py
│   ├── run_future_vpd_workflow.py
│   └── diagnose_final_netcdf.py
│
├── boundaries/                      ← Country shapefiles (read-only inputs)
│   ├── ethiopia/
│   ├── kenya/
│   └── somalia/
│
├── data/                            ← Data storage (managed by artifact_manager.py)
│   ├── raw/                         ← Downloaded source files — never overwrite
│   ├── intermediate/                ← Merged / regridded / clipped working files
│   ├── final/                       ← Final validated outputs ready for delivery
│   └── diagnostics/                 ← QA plots and reports
│
├── runs/                            ← Run manifests and logs
│   ├── manifests/                   ← JSON manifest per run (run_YYYYMMDD_HHMMSS.json)
│   └── logs/                        ← Per-run structured logs
│
└── tests/
    ├── test_naming.py               ← naming convention round-trips
    ├── test_validation.py           ← validation engine unit tests
    └── fixtures/                    ← small synthetic NetCDF fixtures
```

---

## 3. Naming Conventions

**CRITICAL — always enforce these. Never invent ad-hoc file names.**

### 3.1 Raw Downloads

```
data/raw/agera5/{variable}/{variable}_agera5_{YYYY}.nc
data/raw/chirps/chirps_v2.0_{YYYY}.days_p05.nc
data/raw/isimip/{model}/{scenario}/{variable}/{variable}_{model}_{scenario}_{YYYY}.nc
```

### 3.2 Merged / Intermediate

```
data/intermediate/{country}/{variable}/
    {variable}_{country}_agera5_merged_{YYYY_start}-{YYYY_end}.nc
    {variable}_{country}_isimip_{scenario}_merged_{YYYY_start}-{YYYY_end}.nc
```

### 3.3 Final Outputs (0.25-degree clipped)

```
data/final/{country}/{scenario}/{variable}/
    {variable}_{country}_{scenario}_{YYYY_start}-{YYYY_end}_0p25deg.nc
```

### 3.4 Derived VPD

```
data/final/{country}/{scenario}/vpd/
    vpd_{country}_{scenario}_{YYYY_start}-{YYYY_end}_0p25deg.nc
```

### 3.5 Diagnostics

```
data/diagnostics/{run_id}/{country}_{scenario}_{variable}_qa.png
data/diagnostics/{run_id}/run_report.json
```

### 3.6 Country Codes

| Country   | Code  |
|-----------|-------|
| Ethiopia  | `eth` |
| Kenya     | `ken` |
| Somalia   | `som` |

### 3.7 Variable Names (canonical, inside NetCDF)

| Variable             | Canonical Name | Unit   |
|----------------------|----------------|--------|
| 2m temperature       | `tas`          | K      |
| Relative humidity    | `rh`           | %      |
| Vapour pressure def. | `vpd`          | hPa    |
| Precipitation        | `pr`           | mm/day |

---

## 4. Four-Plane Architecture

### 4.1 Control Plane (`agent/router.py`, `agent/planner.py`)
- Parses user request: countries, variables, period, scenario, quality level
- Selects workflow template: `historical`, `projection`, `future_vpd`, `diagnostics`
- Builds execution DAG with explicit step dependencies
- Never executes directly — hands off to Orchestrator

### 4.2 Data Plane (`connectors/`, `scripts/`)
- **Rule: always call existing scripts as subprocess tools — never rewrite their logic**
- Preferred entry points (full runs): `run_historical_workflow.py`,
  `run_projection_workflow.py`, `run_future_vpd_workflow.py`
- Fallback (targeted repair): lower-level scripts individually
- All subprocess calls must: template parameters, capture stdout/stderr,
  parse exit code, log command invocation to run manifest

### 4.3 Quality Plane (`validation/`)
- Runs after every pipeline stage before proceeding
- Strict mode: full grid + bounds + unit + time checks
- Fast mode: existence + non-empty + time range + unit only (skip grid checks)
- Failure → either retry with repaired variant or mark stage as failed

### 4.4 Observability Plane (`agent/state_store.py`, `runs/`)
- Every run gets a unique `run_id = run_YYYYMMDD_HHMMSS`
- Manifest saved to `runs/manifests/{run_id}.json` incrementally
- Log saved to `runs/logs/{run_id}.log`
- Manifest schema: see `run_manifest_schema.json`

---

## 5. Workflow Templates

### 5.1 Historical Workflow

```
Request → Parse → Plan
  → [For each country × variable slice]:
      1. Check raw source exists or download (agera5_download.py / download_chirps.py)
      2. Merge fragmented yearly files (merge_netcdf_{country}_{variable}.py)
      3. Regrid non-precip vars to CHIRPS 0.05° reference (rename_and_regrid_netcdf.py)
      4. Clip to target year window (clip_netcdf_time_range.py)
      5. Clip by country shapefile (clip_netcdf_by_shapefile.py)
      6. Validate output
  → Run diagnostics (diagnose_final_netcdf.py)
  → Save manifest
```

### 5.2 Projection Workflow (SSP245 / SSP585)

```
Request → Parse → Plan
  → [For each country × model × scenario × variable slice]:
      1. Locate ISIMIP source file
      2. Rename variables and regrid (rename_and_regrid_netcdf.py)
      3. Clip to requested time window (clip_netcdf_time_range.py)
      4. Aggregate hourly → daily if required (hourly_to_daily_netcdf.py)
      5. Clip by country shapefile to 0.25° (clip_netcdf_by_shapefile.py)
      6. Validate output
  → Run diagnostics
  → Save manifest
```

### 5.3 Future VPD Workflow

```
Request → Parse → Plan
  → Resolve tas input: prefer 0.25° clipped → fallback legacy daily naming
  → Resolve rh input: same resolution priority
  → Compute VPD using Tetens equation: vpd = 6.1078 × exp(17.27×T/(T+237.3)) × (1 - rh/100)
      (T in °C, result in hPa)
  → Write vpd NetCDF with correct metadata
  → Validate: units, time coverage, grid match tas/rh
  → Run diagnostics
  → Save manifest
```

### 5.4 Diagnostics-Only Workflow

```
Request → Parse → Locate final output(s)
  → Run diagnose_final_netcdf.py per file
  → Produce QA PNGs and run_report.json
  → Save manifest
```

---

## 6. Script Integration Rules

**These rules are non-negotiable:**

1. **Never rewrite script logic** — treat all files in `scripts/` as black-box tools
2. **Always prefer top-level workflow scripts** for full runs
3. **Use lower-level scripts only** for targeted repair or single-stage reruns
4. **Log every subprocess call** with exact command string, timestamp, exit code,
   stdout tail (last 20 lines), stderr tail (last 20 lines)
5. **Parse exit codes deterministically:**
   - `0` → success, proceed
   - `1` → recoverable error, attempt retry or fallback
   - `2+` → hard failure, mark stage failed, stop slice
6. **Retry policy:** exponential backoff — 30s, 60s, 120s → then fail

### Script Parameter Templates

```python
# agera5_download.py
cmd = ["python", "scripts/agera5_download.py",
       "--variable", variable,
       "--year", str(year),
       "--outdir", str(raw_dir / "agera5" / variable)]

# merge_netcdf_{country}_{variable}.py  (no CLI args — driven by internal config)
cmd = ["python", f"scripts/merge_netcdf_{country}_{variable}.py"]

# rename_and_regrid_netcdf.py
cmd = ["python", "scripts/rename_and_regrid_netcdf.py",
       "--input", str(input_path),
       "--reference", str(reference_grid_path),
       "--output", str(output_path)]

# clip_netcdf_time_range.py
cmd = ["python", "scripts/clip_netcdf_time_range.py",
       "--input", str(input_path),
       "--start", str(year_start),
       "--end", str(year_end),
       "--output", str(output_path)]

# clip_netcdf_by_shapefile.py
cmd = ["python", "scripts/clip_netcdf_by_shapefile.py",
       "--input", str(input_path),
       "--shapefile", str(boundaries_dir / country),
       "--output", str(output_path)]

# hourly_to_daily_netcdf.py
cmd = ["python", "scripts/hourly_to_daily_netcdf.py",
       "--input", str(input_path),
       "--output", str(output_path)]

# diagnose_final_netcdf.py
cmd = ["python", "scripts/diagnose_final_netcdf.py",
       "--input", str(final_path),
       "--outdir", str(diagnostics_dir)]
```

---

## 7. Validation Rules

### 7.1 Strict Mode (default)

| Check | Rule |
|-------|------|
| Existence | File exists and size > 0 |
| Time coverage | All expected years/months present, no gaps |
| Daily axis | `time` dimension has daily frequency |
| Variable present | Canonical variable name exists in dataset |
| Units | Match expected unit for variable |
| Grid match | `lat`/`lon` arrays match reference grid within 1e-4 tolerance |
| Spatial bounds | Clipped output bbox within country shapefile bbox ± 0.5° |
| Non-NaN | At least 80% of land pixels non-NaN per time step |

### 7.2 Fast Mode (`fast_mode: true` in agent_config.yaml)

Skip: grid match check, spatial bounds check
Keep all other checks.

### 7.3 On Validation Failure

```
Stage failed validation →
  1. Try repaired file variant (legacy naming fallback)
  2. Re-run only failed slice from that stage
  3. If still failing → mark slice as FAILED in manifest, continue other slices
  4. Report all failed slices in run_report.json
```

---

## 8. Error Handling

| Error Type | Strategy |
|------------|----------|
| Missing source file | Fail fast — report exact missing path, suggest download command |
| Missing boundary file | Fail fast — report expected path |
| Invalid scenario/country/variable | Fail fast — list valid values |
| API transient failure (CDS) | Retry with exponential backoff (3 attempts max) |
| Permission error on overwrite | Log and skip — never silently overwrite |
| Missing years in merged file | Quantify gap, flag if > 5% of expected coverage |
| Grid mismatch | Report actual vs expected shape and resolution |
| Unit mismatch | Report found vs expected, suggest conversion |
| Outlier detected | Log variable/period/pixel count, do not abort |

---

## 9. Run Manifest Structure

Every run produces `runs/manifests/{run_id}.json`:

```json
{
  "run_id": "run_20260506_143000",
  "timestamp": "2026-05-06T14:30:00Z",
  "request": {
    "countries": ["eth", "ken"],
    "variables": ["tas", "rh"],
    "period": [1981, 2023],
    "scenario": "historical",
    "quality_level": "strict",
    "diagnostics": true
  },
  "environment": {
    "python_version": "3.11.x",
    "xarray_version": "...",
    "script_commit": "abc1234"
  },
  "stages": [
    {
      "stage": "merge",
      "country": "eth",
      "variable": "tas",
      "command": "python scripts/merge_netcdf_ethiopia_temperature.py",
      "started_at": "...",
      "finished_at": "...",
      "exit_code": 0,
      "status": "SUCCESS",
      "input_files": ["data/raw/agera5/tas/tas_agera5_1981.nc", "..."],
      "output_file": "data/intermediate/eth/tas/tas_eth_agera5_merged_1981-2023.nc",
      "input_hash": "sha256:...",
      "output_hash": "sha256:...",
      "validation": {"time_coverage": "OK", "units": "OK", "grid_match": "OK"}
    }
  ],
  "summary": {
    "total_slices": 4,
    "succeeded": 3,
    "failed": 1,
    "failed_slices": [{"country": "ken", "variable": "rh", "stage": "regrid", "reason": "..."}],
    "duration_seconds": 342
  }
}
```

---

## 10. Dependencies

```
xarray>=2024.1
numpy>=1.26
pandas>=2.1
geopandas>=0.14
rioxarray>=0.15
netCDF4>=1.6
matplotlib>=3.8
scipy>=1.12
cdsapi>=0.6
dask>=2024.1        # for chunked xarray operations
tqdm>=4.66          # progress bars in scripts
pyyaml>=6.0         # agent_config.yaml parsing
jsonschema>=4.21    # manifest validation
```

---

## 11. Dos and Don'ts for Claude Code

**DO:**
- Read `agent_config.yaml` before every run to get current paths and flags
- Check `runs/manifests/` for previous runs before re-downloading source data
- Use `artifact_manager.py` to resolve all file paths — never hardcode paths
- Log every subprocess command to the manifest before executing it
- Validate output after every stage before proceeding
- Fingerprint (SHA-256) all source files and record in manifest
- Ask for confirmation before deleting or overwriting any file in `data/final/`

**DO NOT:**
- Rewrite logic inside `scripts/` — treat them as black boxes
- Hardcode absolute paths — always use `agent_config.yaml` base dirs
- Skip validation even in fast mode — only skip the expensive checks
- Run multiple writes to the same output path concurrently
- Silently swallow subprocess stderr — always capture and log it
- Invent new variable or country codes outside the canonical lists above
