# Climate Data Processing Agent — Usage Guide

## Quick Start

```bash
python run_agent.py \
  --countries eth ken som \
  --variables tas rh pr vpd \
  --scenario historical \
  --period 2010 2025 \
  --workers 3
```

**Supported values**

| Parameter | Options |
|-----------|---------|
| `--countries` | `eth` (Ethiopia), `ken` (Kenya), `som` (Somalia) |
| `--variables` | `tas` (temperature K), `rh` (relative humidity %), `vpd` (vapour pressure deficit hPa), `pr` (precipitation mm/day) |
| `--scenario` | `historical`, `ssp245`, `ssp585` |
| `--period` | Any two years: `--period 1981 2023` |

---

## Always Dry-Run First

See exactly what stages will execute — zero side effects:

```bash
python run_agent.py \
  --countries eth ken \
  --variables tas rh pr \
  --scenario historical \
  --period 2010 2023 \
  --dry-run
```

Output shows the translated script arguments, stage names, and expected output paths before anything runs.

---

## Common Run Patterns

### Historical — single country

```bash
python run_agent.py \
  --countries eth \
  --variables pr \
  --scenario historical \
  --period 2010 2023
```

### Historical — all countries in parallel

Three workers runs one subprocess per country simultaneously:

```bash
python run_agent.py \
  --countries eth ken som \
  --variables tas rh pr vpd \
  --scenario historical \
  --period 1981 2023 \
  --workers 3
```

### Future projections — SSP245

```bash
python run_agent.py \
  --countries eth ken \
  --variables tas rh pr \
  --scenario ssp245 \
  --period 2040 2070 \
  --workers 2
```

### VPD only (derived variable)

VPD is computed from `tas` and `rh`. Run this after those outputs exist:

```bash
python run_agent.py \
  --countries eth \
  --variables vpd \
  --scenario ssp245 \
  --period 2040 2070
```

### VPD + projection variables in one run

Produces two sequential stages: `regrid` then `vpd_compute`:

```bash
python run_agent.py \
  --countries eth \
  --variables tas rh vpd \
  --scenario ssp585 \
  --period 2040 2070
```

---

## Validation Modes

### Strict (default)

Full validation after every stage: grid match, spatial bounds, unit check, time coverage, non-NaN coverage. Aborts remaining stages on any `FAIL`.

```bash
python run_agent.py --countries eth --variables pr \
  --scenario historical --period 2010 2020
```

### Fast mode

Skips `grid_match` and `spatial_bounds` checks. Validation failures are recorded as `WARNING` and the run continues. Use when iterating quickly:

```bash
python run_agent.py --countries eth --variables pr \
  --scenario historical --period 2010 2020 \
  --mode fast
```

---

## Diagnostic Plots

Produces a QA PNG per output file (time series + spatial map) in `data/diagnostics/{run_id}/`:

```bash
python run_agent.py \
  --countries eth \
  --variables tas pr \
  --scenario historical \
  --period 2010 2023 \
  --diagnostics
```

---

## Resuming a Failed Run

If a stage fails or the process is interrupted, skip already-completed stages:

```bash
# Auto-resume the most recent failed run
python run_agent.py \
  --countries eth ken \
  --variables tas rh \
  --scenario historical \
  --period 2010 2023 \
  --resume-latest

# Resume a specific run by ID
python run_agent.py \
  --countries eth ken \
  --variables tas rh \
  --scenario historical \
  --period 2010 2023 \
  --resume run_20260506_143000
```

---

## Inspecting and Listing Run Results

```bash
# List all runs (most recent first)
python run_agent.py --list-runs

# Show only failed runs
python run_agent.py --list-runs --failed

# Limit to most recent 5
python run_agent.py --list-runs --limit 5

# Full detail for a specific run
python run_agent.py --validate-run run_20260506_143000
python run_agent.py --validate-run run_20260506_143000 --checks   # per-check breakdown
```

The `--validate-run` report shows:
- Per-stage status: `SUCCESS` / `FAILED` / `WARNING` / `SKIPPED`
- Validation check results per output file
- Failed-slice reasons with truncated stderr
- Output file paths and whether they currently exist on disk

---

## Logging

```bash
--log-level DEBUG    # full subprocess stdout/stderr per stage
--log-level INFO     # default — stage start/end, validation summary
--log-level WARNING  # only failures and warnings
```

Logs are written to both stdout and `runs/logs/{run_id}.log`.

---

## Skipping Preflight

Preflight checks packages, workflow scripts, boundary files, and source directories before any stage runs. It adds ~2 seconds but catches problems early. Skip it when iterating on an already-validated environment:

```bash
python run_agent.py \
  --countries eth --variables pr \
  --scenario historical --period 2010 2020 \
  --skip-preflight
```

> **Note:** Missing packages and missing workflow scripts are hard errors that abort the run. Missing boundary or source data files are warnings that allow the run to proceed (the relevant stage will fail when it actually needs the file).

---

## Output Directory Layout

```
data/
├── {country}_temperature/netcdf/        # Raw AgERA5 daily tas files
├── {country}_relative_humidity_mean/netcdf/  # Raw AgERA5 daily rh files
├── {country}_chirips/                   # Raw CHIRPS annual files
├── projection_data/isimip-download-{country}/{scenario}/{variable}/
│
├── merged_files/                        # All processed outputs live here
│   ├── {country}_{var}_{start}_{end}.nc              ← merged intermediate
│   ├── {country}_{var}_{start}_{end}_025deg.nc       ← regridded
│   └── {country}_{var}_{start}_{end}_025deg_clipped.nc  ← final output
│
└── diagnostics/{run_id}/
    ├── {country}_{var}_{start}_{end}_diagnostic.png
    ├── {country}_{var}_{start}_{end}_qc.json
    └── run_report.json

runs/
├── manifests/{run_id}.json              # Full run manifest (JSON)
└── logs/{run_id}.log                    # Structured log
```

---

## Typical Workflow Sequence

```bash
# 1. Preview — confirm stages and script args before committing
python run_agent.py --countries eth --variables tas rh pr \
  --scenario historical --period 2010 2025 --dry-run

# 2. Execute
python run_agent.py --countries eth --variables tas rh pr \
  --scenario historical --period 2010 2025 --diagnostics

# 3. List completed runs and inspect the result
python run_agent.py --list-runs
python run_agent.py --validate-run run_20260507_212038

# 4. If a stage failed, fix the underlying data issue then resume
python run_agent.py --countries eth --variables tas rh pr \
  --scenario historical --period 2010 2025 \
  --resume-latest

# 5. Export outputs for delivery
python run_agent.py \
  --export-run run_20260507_212038 \
  --export-to /path/to/delivery/
```

---

## Full CLI Reference

```
python run_agent.py [OPTIONS]

Required (pipeline mode):
  --countries CODE [CODE ...]   Country short code(s): eth, ken, som
  --variables VAR [VAR ...]     Variable(s): tas, rh, vpd, pr
  --scenario SCENARIO           Climate scenario: historical, ssp245, ssp585
  --period START END            Year range, e.g. --period 2010 2025

Execution:
  --workers N                   Parallel worker count (default: 1)
  --mode {strict,fast}          Validation mode (default: strict)
  --diagnostics                 Produce QA diagnostic plots for each output
  --dry-run                     Print planned commands without executing
  --force                       Re-run stages even if outputs already exist
  --resume RUN_ID               Resume a prior run; skip stages already SUCCESS
  --resume-latest               Auto-resume the most recent run with failures

Observability (early-exit modes, no pipeline required):
  --list-runs                   Print a table of all completed run manifests
  --failed                      With --list-runs: show only failed runs
  --limit N                     With --list-runs: cap output to N rows
  --validate-run RUN_ID         Summarise a specific completed run manifest
  --checks                      With --validate-run: show per-check detail
  --export-run RUN_ID           Copy a run's output files to a delivery dir
  --export-to DIR               Destination directory for --export-run

Environment:
  --skip-preflight              Skip preflight environment checks
  --log-level {DEBUG,INFO,WARNING,ERROR}
                                Logging verbosity (default: INFO)
  --manifests-dir DIR           Override default runs/manifests/ location
```
