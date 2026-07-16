# Getting Started

## 1. Clone and create an environment

```bash
git clone https://github.com/YonSci/climate-agent.git
cd climate-agent
python -m venv .venv
```

Activate the environment:

```bash
# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the package:

```bash
pip install -e .
```

For development and testing:

```bash
pip install -e ".[dev]"
```

## 2. Configure data access

AgERA5 acquisition requires a Copernicus Climate Data Store account and credentials in `~/.cdsapirc`. Never commit credentials or access tokens.

## 3. Preview a workflow

```bash
python run_agent.py \
  --countries eth \
  --variables tas pr \
  --scenario historical \
  --period 2010 2025 \
  --diagnostics \
  --dry-run
```

## 4. Execute the workflow

```bash
python run_agent.py \
  --countries eth \
  --variables tas pr \
  --scenario historical \
  --period 2010 2025 \
  --diagnostics
```

## 5. Inspect and export results

```bash
python run_agent.py --list-runs
python run_agent.py --validate-run RUN_ID
python run_agent.py --export-run RUN_ID --export-to /path/to/delivery
```

## Before operational delivery

Confirm that required stages succeeded, validation results are acceptable, diagnostic plots are physically plausible, and the run manifest and delivery manifest accompany the final NetCDF files.
