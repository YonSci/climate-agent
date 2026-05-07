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
# 1. Find the run ID of the failed run
python scripts/validate_run.py --list

# 2. Resume — successful stages are skipped, failed ones re-run
python run_agent.py \
  --countries eth ken \
  --variables tas rh \
  --scenario historical \
  --period 2010 2023 \
  --resume run_20260506_143000
```

---

## Inspecting Run Results

```bash
# Latest run (default)
python scripts/validate_run.py

# Specific run
python scripts/validate_run.py --run-id run_20260506_143000

# List all runs with summary counts
python scripts/validate_run.py --list
```

The report shows:
- Per-stage status: `OK` / `FAIL` / `WARN` / `SKIP`
- Validation check results per output file
- Failed-slice reasons with truncated stderr
- Output file paths and whether they exist on disk

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
├── raw/                                 # Downloaded source files — never overwritten
│   ├── agera5/{variable}/
│   └── chirps/
├── intermediate/{country}/{variable}/   # Merged / regridded working files
├── final/{country}/{scenario}/{variable}/
│   └── {variable}_{country}_{scenario}_{start}-{end}_0p25deg.nc
└── diagnostics/{run_id}/
    └── {country}_{scenario}_{variable}_qa.png

runs/
├── manifests/{run_id}.json              # Full run manifest (JSON)
└── logs/{run_id}.log                    # Structured log
```

---

## Typical Workflow Sequence

```bash
# 1. Preview — confirm stages and script args before committing
python run_agent.py --countries eth --variables tas rh pr \
  --scenario historical --period 2010 2023 --dry-run

# 2. Execute
python run_agent.py --countries eth --variables tas rh pr \
  --scenario historical --period 2010 2023 --workers 1

# 3. Inspect results
python scripts/validate_run.py

# 4. If a stage failed, fix the underlying data issue then resume
python run_agent.py --countries eth --variables tas rh pr \
  --scenario historical --period 2010 2023 \
  --resume run_20260506_143000
```

---

## Full CLI Reference

```
python run_agent.py [OPTIONS]

Required:
  --countries CODE [CODE ...]   Country short code(s): eth, ken, som
  --variables VAR [VAR ...]     Variable(s): tas, rh, vpd, pr
  --scenario SCENARIO           Climate scenario: historical, ssp245, ssp585
  --period START END            Year range, e.g. --period 2010 2025

Execution:
  --workers N                   Parallel worker count (default: 1)
                                 When N > 1 and multiple countries, runs one
                                 subprocess per country concurrently.
  --mode {strict,fast}          Validation mode (default: strict)
  --diagnostics                 Produce QA diagnostic plots for each output
  --dry-run                     Print planned commands without executing
  --resume RUN_ID               Resume from a previous run; skip SUCCESS stages

Environment:
  --skip-preflight              Skip preflight environment checks
  --log-level {DEBUG,INFO,WARNING,ERROR}
                                Logging verbosity (default: INFO)
```
