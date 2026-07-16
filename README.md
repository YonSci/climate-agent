# Climate Data Harmonization Agent

> A user-centred, reproducible climate-data pipeline that converts a request such as “prepare daily temperature and rainfall for Ethiopia and Kenya for 2010–2025” into validated, analysis-ready NetCDF files, together with quality-control diagnostics and a structured audit trail.

**Institutional context:** Developed for ILRI Climate Services to support impact modelling, climate-risk analysis, and the preparation of harmonized climate datasets for food security, livestock, agriculture, drought, and related decision-support applications.

**Project status:** Operational research software, version `0.1.0`. The repository demonstrates development, documentation, reproducibility, and public sharing. Formal registration or deployment within the CGIAR/ILRI Climate Data Hub should be documented separately before the product is reported as fully integrated into the Hub.

---

## Contents

- [Purpose](#purpose)
- [Contribution to the ILRI result](#contribution-to-the-ilri-result)
- [Current readiness and evidence status](#current-readiness-and-evidence-status)
- [Intended users and use cases](#intended-users-and-use-cases)
- [Supported domain](#supported-domain)
- [Architecture](#architecture--four-planes)
- [Workflow templates](#workflow-templates)
- [Quick start](#quick-start)
- [Outputs and delivery products](#outputs-and-delivery-products)
- [Validation and quality assurance](#validation-and-quality-assurance)
- [Reproducibility and provenance](#reproducibility-and-provenance)
- [Climate Data Hub integration pathway](#climate-data-hub-integration-pathway)
- [Monitoring, evaluation, learning, and reporting evidence](#monitoring-evaluation-learning-and-reporting-evidence)
- [Stakeholder engagement and user feedback](#stakeholder-engagement-and-user-feedback)
- [GESI and responsible implementation](#gesi-and-responsible-implementation)
- [Current limitations and roadmap](#current-limitations-and-roadmap)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Data sources](#data-sources)
- [Citation and contacts](#citation-and-contacts)

---

## Purpose

Impact modellers working on food security, livestock productivity, agriculture, water demand, disease risk, and drought in East Africa need consistent climate datasets spanning the observed past and plausible future conditions. Producing these datasets from raw archives involves repeated and error-prone steps, including:

- locating and downloading data from multiple providers;
- merging fragmented daily or annual files;
- harmonizing variable names, units, calendars, and metadata;
- regridding datasets to a consistent spatial grid;
- clipping data to national or other analysis boundaries;
- checking temporal completeness, spatial coverage, units, and anomalies; and
- documenting how each output was produced.

The Climate Data Harmonization Agent automates this sequence. A user specifies the country, variable, scenario, and period. The agent selects a workflow, constructs an ordered task graph, executes the required processing stages, validates the outputs, and records the run in a machine-readable manifest.

The tool therefore addresses the data-preparation gap between raw climate archives and downstream models, dashboards, vulnerability assessments, and climate-informed decision-support systems.

---

## Contribution to the ILRI result

This repository is designed to contribute to the following ILRI 2026 result.

| Result field | Contribution of this repository |
|---|---|
| **Result level** | Output |
| **Center** | ILRI |
| **Result ID** | 11 |
| **Result short name** | Develop methods and pipelines for user-centred outputs and integrate ILRI climate-relevant analytical methods and pipelines within the Climate Data Hub. |
| **Indicator** | Number of frameworks, strategies, or tools developed and shared |
| **Standard result type** | Innovation development |
| **2026 target** | 2 |
| **HLO contribution** | Harmonized data, simulations, insights, and decision-support tools for understanding climate risks, emission hotspots, and multidimensional trade-offs, co-developed and shared with stakeholders. |
| **Package ID** | M2 |

### How the tool contributes

| Requirement | Repository contribution |
|---|---|
| **Develop a climate-relevant method, framework, or tool** | Provides an operational orchestration and quality-assurance tool for climate-data acquisition, harmonization, validation, diagnostics, and delivery. |
| **Produce user-centred outputs** | Converts a simple user request into standardized, analysis-ready datasets and evidence products without requiring users to manually execute every processing script. |
| **Harmonize climate data** | Applies consistent naming, units, temporal coverage checks, grids, geographic clipping, metadata, and output conventions across multiple sources. |
| **Develop and share the product** | Source code, configuration, examples, workflow descriptions, and the usage guide are publicly accessible in this repository. |
| **Support Climate Data Hub integration** | Produces standardized files, metadata, manifests, inventories, diagnostics, and reports that can be registered, linked, or exposed through the Hub. Formal Hub registration or deployment remains an institutional integration step. |
| **Support decision tools and impact modelling** | Prepares inputs for livestock, agriculture, food-security, drought, climate-risk, disease, and other impact-model workflows. |

> **Reporting note:** The Climate Data Harmonization Agent should normally be counted as **one integrated tool** toward the target of two frameworks/strategies/tools. Its internal historical, projection, VPD, validation, and reporting workflows are modules of the same product unless the reporting authority accepts separately packaged and independently shared products.

---

## Current readiness and evidence status

The table distinguishes implemented functionality from evidence that still needs to be produced outside the code repository.

| Readiness element | Status | Evidence or action |
|---|---:|---|
| Source code and configuration available | ✅ Completed | Repository modules, scripts, configuration, and dependency files |
| User installation and usage guidance | ✅ Completed | This README and [`USAGE.md`](USAGE.md) |
| Historical and projection workflow templates | ✅ Completed | Router, planner, orchestrator, connectors, and processing scripts |
| Automated validation and diagnostics | ✅ Completed | `validation/`, QA JSON, diagnostic plots, and run reports |
| Machine-readable provenance | ✅ Completed | Run manifests validated against `run_manifest_schema.json` |
| Delivery packaging | ✅ Completed | `--export-run`, exported NetCDF files, and `delivery_manifest.json` |
| Static evidence/report page | ✅ Implemented | `scripts/generate_report.py` and GitHub Pages publishing workflow |
| Public sharing | ✅ Completed | Public GitHub repository |
| Formal Climate Data Hub catalogue/wiki entry | ⬜ Required | Add the approved Hub URL and product metadata when available |
| Deployment or callable service within the Hub | ⬜ Planned | Agree the integration pattern: linked repository, service, API, workflow, or container |
| Stakeholder demonstration and feedback record | ⬜ Required | Attach meeting notes, participant list, feedback, or acceptance record |
| Country-level operational validation beyond current configurations | ⬜ Planned | Add configurations, test runs, and evidence for additional target countries |
| Versioned institutional release | ⬜ Recommended | Create a tagged release and archive the reporting evidence package |

---

## Intended users and use cases

### Primary users

- ILRI climate, livestock, environment, and impact-modelling teams;
- Climate Data Hub data managers and analytical-product developers;
- national meteorological and hydrological services;
- ministries and agencies responsible for agriculture, livestock, and disaster risk management;
- researchers and technical partners preparing climate-impact datasets; and
- analysts developing dashboards, early-warning systems, advisories, or forecasting applications.

### User-centred use cases

| User need | Agent response |
|---|---|
| “Prepare daily temperature and rainfall for Ethiopia for 2010–2025.” | Selects historical sources, downloads missing files, merges, harmonizes, clips, validates, and delivers the requested data. |
| “Prepare projected climate inputs for Kenya under SSP2-4.5 for 2040–2070.” | Resolves ISIMIP inputs, harmonizes the variables, aggregates where needed, clips, validates, and records provenance. |
| “Generate future vapour pressure deficit for livestock heat-stress analysis.” | Resolves projected temperature and relative-humidity inputs and derives VPD with documented metadata and validation. |
| “Show whether the delivered data are complete and spatially valid.” | Produces validation results, QC statistics, diagnostics, run manifests, logs, and a static HTML report. |
| “Reproduce or audit an earlier delivery.” | Uses the saved run request, stage commands, environment metadata, validation results, and delivery manifest. |

### User request model

A user specifies:

1. **Where:** one or more supported countries;
2. **What:** one or more climate variables;
3. **Which climate context:** historical or future scenario;
4. **When:** start and end year;
5. **Quality level:** strict or fast validation; and
6. **Optional products:** diagnostics, run inspection, resume, or export.

---

## Supported domain

### Current operational configuration

| Dimension | Values |
|---|---|
| **Countries** | Ethiopia (`eth`), Kenya (`ken`), Somalia (`som`) |
| **Variables** | `tas` (temperature, K), `rh` (relative humidity, %), `vpd` (vapour pressure deficit, hPa), `pr` (precipitation, mm/day) |
| **Scenarios** | `historical`, `ssp245`, `ssp585` |
| **Reference and target grids** | CHIRPS 0.05° may be used as a historical regridding reference; configured final target resolution is 0.25° where applicable |
| **Period** | Any contiguous year range within the availability of the selected source data |
| **Primary formats** | NetCDF, JSON manifests, JSON quality-control reports, PNG diagnostics, logs, and HTML reports |

### Planned result geographies

The associated ILRI result lists Ethiopia, Ghana, Kenya, Tanzania, and Uganda. This repository currently contains operational country configurations for Ethiopia, Kenya, and Somalia. Reporting should therefore distinguish:

- **implemented and validated geographies**, supported by completed run evidence; and
- **planned or extensible geographies**, which require country boundaries, source checks, configuration, tests, and documented validation before being claimed as operational.

---

## Architecture — Four planes

```text
┌─────────────────────────────────────────────────────────────┐
│  Control Plane          agent/router.py · agent/planner.py  │
│  Parse request → select workflow template → build DAG       │
├─────────────────────────────────────────────────────────────┤
│  Data Plane             connectors/ · scripts/              │
│  Download → merge → harmonize → regrid → clip              │
├─────────────────────────────────────────────────────────────┤
│  Quality Plane          validation/                         │
│  Schema · time · spatial · anomaly checks after each stage  │
├─────────────────────────────────────────────────────────────┤
│  Observability Plane    agent/state_store.py · runs/        │
│  Run manifest · stage logs · QA diagnostics · HTML report   │
└─────────────────────────────────────────────────────────────┘
```

### Key modules

| Module | Role |
|---|---|
| `agent/router.py` | Maps a request to a workflow template, including historical, projection, future VPD, and diagnostics workflows |
| `agent/planner.py` | Builds the ordered directed acyclic graph of stages with explicit dependencies |
| `agent/orchestrator.py` | Executes stages through subprocesses and manages retry, validation, continuation, and manifest recording |
| `agent/policy.py` | Defines naming rules, compression, retry backoff, and fast-mode behaviour |
| `agent/state_store.py` | Reads and writes run manifests and supports idempotent resume operations |
| `agent/artifact_manager.py` | Centralizes file-path resolution and output locations |
| `agent/preflight.py` | Checks required packages, scripts, boundaries, and source inputs before execution |
| `connectors/agera5_connector.py` | Builds AgERA5 acquisition commands |
| `connectors/chirps_connector.py` | Builds CHIRPS acquisition commands |
| `connectors/isimip_connector.py` | Builds ISIMIP projection-data commands |
| `validation/schema_checks.py` | Checks expected variables, units, dimensions, and non-missing coverage |
| `validation/time_checks.py` | Checks requested coverage, gaps, duplicate dates, and daily continuity |
| `validation/spatial_checks.py` | Checks grid properties, spatial bounds, and cross-file consistency |
| `validation/anomaly_checks.py` | Flags outliers, flat fields, and saturated fields |
| `scripts/generate_report.py` | Generates a self-contained HTML evidence report from run manifests and diagnostic products |

---

## Workflow templates

### Historical: AgERA5 and CHIRPS

```text
Identify missing source years
→ Download or locate source data
→ Merge fragmented files
→ Harmonize units and metadata
→ Regrid using the configured reference/target grid
→ Clip the requested period
→ Clip to the country boundary
→ Validate
→ Generate diagnostics and evidence products
```

### Projection: ISIMIP SSP2-4.5 or SSP5-8.5

```text
Locate projection source files
→ Resolve model/scenario/variable inputs
→ Rename and harmonize variables
→ Aggregate sub-daily data where required
→ Regrid to the configured target
→ Clip time and geography
→ Validate
→ Generate diagnostics and evidence products
```

### Future VPD: derived variable

```text
Resolve projected temperature and relative-humidity inputs
→ Convert temperature to degrees Celsius for the calculation
→ Calculate saturation vapour pressure using the Tetens equation
→ Calculate VPD
→ Write metadata and units
→ Validate
→ Generate diagnostics
```

The implemented relationship is:

```text
VPD = 6.1078 × exp(17.27 × T / (T + 237.3)) × (1 − RH/100)
```

where `T` is temperature in °C, `RH` is relative humidity in percent, and VPD is returned in hPa.

---

## Quick start

### 1. Clone and install

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

Install the package and development dependencies:

```bash
pip install -e .
pip install -e ".[dev]"
```

Alternatively:

```bash
pip install -r requirements.txt
```

### 2. Configure data access

AgERA5 acquisition requires a Copernicus Climate Data Store account and credentials in `~/.cdsapirc`.

```text
url: https://cds.climate.copernicus.eu/api/v2
key: <YOUR_UID>:<YOUR_API_KEY>
```

Never commit credentials or access tokens to the repository.

### 3. Preview the workflow

Run a dry run first to inspect the selected stages, commands, and expected outputs without changing data.

```bash
python run_agent.py \
    --countries eth \
    --variables tas pr \
    --scenario historical \
    --period 2010 2025 \
    --diagnostics \
    --dry-run
```

### 4. Execute a historical request

```bash
python run_agent.py \
    --countries eth \
    --variables tas pr \
    --scenario historical \
    --period 2010 2025 \
    --diagnostics
```

### 5. Execute a projection request

```bash
python run_agent.py \
    --countries ken som \
    --variables tas rh vpd pr \
    --scenario ssp245 \
    --period 2040 2070 \
    --diagnostics
```

### 6. Inspect and export a completed run

```bash
python run_agent.py --list-runs
python run_agent.py --validate-run run_20260506_143000

python run_agent.py \
    --export-run run_20260506_143000 \
    --export-to /path/to/delivery/
```

For more run patterns, validation modes, logging, recovery, and operational guidance, see [`USAGE.md`](USAGE.md).

---

## CLI reference

| Flag | Required | Description |
|---|---:|---|
| `--countries` | Yes | One or more of `eth`, `ken`, or `som` |
| `--variables` | Yes | One or more of `tas`, `rh`, `vpd`, or `pr` |
| `--scenario` | Yes | `historical`, `ssp245`, or `ssp585` |
| `--period` | Yes | Start and end year, for example `--period 2010 2025` |
| `--mode` | No | `strict` by default or `fast` |
| `--workers` | No | Number of parallel worker threads; default is 1 |
| `--diagnostics` | No | Produce QA plots and a `run_report.json` |
| `--dry-run` | No | Print planned stages and commands without executing them |
| `--resume RUN_ID` | No | Resume a previous run and skip stages already marked successful |
| `--resume-latest` | No | Resume the most recent run containing a recorded failure |
| `--skip-preflight` | No | Bypass environment checks; not recommended for operational runs |
| `--log-level` | No | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `--validate-run [ID]` | No | Summarize a completed run manifest |
| `--list-runs` | No | List completed runs and status counts |
| `--failed` | No | With `--list-runs`, show only runs containing failures |
| `--limit N` | No | Limit the number of listed runs |
| `--export-run RUN_ID` | No | Copy all recorded outputs into a delivery package |
| `--export-to DIR` | No | Destination directory for an exported run |
| `--force` | No | Re-execute stages even when expected outputs already exist |
| `--manifests-dir DIR` | No | Override the default `runs/manifests/` location |

---

## Outputs and delivery products

A completed operational run may produce the following products.

| Product | Purpose | Reporting value |
|---|---|---|
| Final NetCDF files | Analysis-ready climate inputs | Demonstrates the functional output delivered to users |
| Run manifest JSON | Request, stages, commands, status, environment, and validation evidence | Supports reproducibility, audit, and provenance |
| QA JSON | Summary statistics and file-level quality checks | Demonstrates technical validation |
| Diagnostic PNG | Visual checks of spatial patterns and temporal behaviour | Supports expert review and communication |
| Structured log | Execution history and error context | Supports traceability and maintenance |
| `run_report.json` | Run-level diagnostic summary | Supports machine-readable reporting |
| `delivery_manifest.json` | Inventory of exported products, file sizes, source run, and copy status | Supports formal handover to users or the Climate Data Hub |
| Static HTML report | Human-readable run history, validation tables, inventory, QC statistics, and diagnostics | Supports demonstrations, review meetings, and reporting |

### Output layout

```text
data/
├── {country}_temperature/netcdf/              # raw AgERA5 temperature files
├── {country}_relative_humidity_mean/netcdf/   # raw AgERA5 humidity files
├── {country}_vapour_pressure_deficit/netcdf/  # raw or derived VPD files
├── {country}_chirips/                         # legacy configured CHIRPS directory name
├── projection_data/isimip-download-{country}/{scenario}/{variable}/
│
├── merged_files/
│   ├── {country}_{variable}_{start}_{end}.nc
│   ├── {country}_{variable}_{start}_{end}_025deg.nc
│   └── {country}_{variable}_{start}_{end}_025deg_clipped.nc
│
└── diagnostics/{run_id}/
    ├── {country}_{variable}_{start}_{end}_diagnostic.png
    ├── {country}_{variable}_{start}_{end}_qc.json
    └── run_report.json

runs/
├── manifests/{run_id}.json
└── logs/{run_id}.log
```

---

## Validation and quality assurance

Every pipeline stage is validated before downstream stages proceed. Results are recorded in the run manifest.

| Check | Strict mode | Fast mode |
|---|:---:|:---:|
| File exists and size is greater than zero | ✓ | ✓ |
| Expected variable is present | ✓ | ✓ |
| Units match the canonical unit | ✓ | ✓ |
| Requested temporal coverage is present | ✓ | ✓ |
| Daily time axis is continuous | ✓ | ✓ |
| At least 80% of expected land pixels are non-missing | ✓ | ✓ |
| Grid matches the configured reference | ✓ | — |
| Spatial bounds agree with the country boundary within tolerance | ✓ | — |
| Cross-file grids are consistent | ✓ | — |
| Outlier or anomaly detection | warning | warning |
| Flat or saturated field detection | warning | warning |

On a validation failure, the agent can retry the failed slice, apply supported naming fallbacks, and record the unresolved slice as `FAILED` while preserving evidence from the rest of the run.

### Recommended operational acceptance criteria

Before a dataset is delivered or registered in the Climate Data Hub:

- all required stages should be `SUCCESS` or have documented, accepted warnings;
- the final files should pass schema, unit, temporal, and spatial checks;
- a domain expert should review diagnostic plots for physical plausibility;
- the run manifest and delivery manifest should accompany the data;
- the data source, period, scenario, grid, variable, units, and processing version should be recorded; and
- any limitations or deviations should be documented in the handover note.

---

## Reproducibility and provenance

The agent is designed to make each delivery traceable and reproducible.

Each run manifest records, where available:

- the original request;
- workflow and stage names;
- commands executed;
- input and output paths;
- stage dependencies and status;
- retry attempts and error messages;
- validation results;
- software and environment metadata;
- timestamps and duration; and
- diagnostic and final-delivery products.

### Re-running and recovery

- **Skip if done:** stages are skipped when all expected outputs already exist.
- **Force:** `--force` re-executes the requested stages.
- **Resume by ID:** `--resume RUN_ID` continues from a previous manifest.
- **Resume latest failure:** `--resume-latest` identifies and resumes the most recent failed run.
- **Dry run:** `--dry-run` displays the execution plan without side effects.

### Versioning recommendation

For an institutional delivery, record:

1. the Git commit SHA;
2. a tagged release, such as `v0.1.0`;
3. the configuration file used;
4. the data-source versions and access dates;
5. the run and delivery manifests; and
6. the Hub catalogue or wiki URL where the product is registered.

---

## Climate Data Hub integration pathway

The repository is **integration-ready**, but a repository link alone should not be presented as proof of completed Climate Data Hub integration. The integration should be agreed with the Hub governance and technical teams and documented through an approved access point.

### Recommended integration components

| Component | Recommended implementation |
|---|---|
| **Product registration** | Create a Climate Data Hub catalogue or wiki page with the product name, purpose, owner, version, supported geographies, variables, sources, and contact details. |
| **Method documentation** | Link this README, `USAGE.md`, workflow diagrams, validation rules, and a short methodology note. |
| **Code access** | Link the versioned GitHub release or an approved institutional mirror. |
| **Data access** | Register exported NetCDF datasets or their storage location using consistent metadata and naming conventions. |
| **Provenance access** | Publish or archive the associated run manifest, QA report, and delivery manifest. |
| **Operational access** | Agree whether the Hub exposes the tool as a linked repository, scheduled workflow, container, API, command-line service, or downloadable package. |
| **Demonstration** | Provide at least one completed example for a priority country and use case. |
| **Governance** | Document the product owner, maintainer, review cycle, access controls, data licences, and process for approving new sources or geographies. |
| **User support** | Provide a contact point, issue-reporting route, training material, and known-limitations section. |

### Minimum evidence for claiming integration

To report the product as integrated within the Climate Data Hub, retain:

- the active Hub page, catalogue record, workflow, or service URL;
- a screenshot or exported record showing the product within the Hub;
- the approved metadata and product owner;
- a working example of data or workflow access through the agreed Hub route;
- a successful run and associated evidence products; and
- confirmation from the responsible Hub or ILRI technical lead.

---

## Monitoring, evaluation, learning, and reporting evidence

This repository can support result reporting by producing a structured evidence package.

### Recommended evidence package

| Evidence item | Suggested source |
|---|---|
| Product title and short description | README introduction and institutional contribution section |
| Source code and release | Tagged GitHub release or institutional archive |
| User guide | `README.md` and `USAGE.md` |
| Method and workflow description | Architecture and workflow sections |
| Configuration used | `agent_config.yaml` archived with the release |
| Successful operational run | `runs/manifests/{run_id}.json` |
| Quality-assurance evidence | QA JSON, validation results, and diagnostic PNGs |
| Delivered product inventory | `delivery_manifest.json` |
| Human-readable evidence report | HTML output from `scripts/generate_report.py` |
| Hub integration evidence | Approved Hub URL, screenshot, catalogue record, or workflow identifier |
| Sharing evidence | Public repository, release link, demonstration presentation, meeting record, or training material |
| Stakeholder contribution | Consultation notes, user requirements, feedback log, and changes made in response |
| Geographic evidence | Country configuration, completed run, sample output, and validation record for each claimed geography |

### Suggested reporting statement

> The Climate Data Harmonization Agent is a user-centred analytical tool developed by ILRI Climate Services to automate the acquisition, harmonization, validation, documentation, and delivery of historical and projected climate datasets. The tool converts user-defined requests into analysis-ready NetCDF products and generates structured provenance, quality-control diagnostics, and delivery manifests. Its source code and documentation are shared through a public repository, while formal Climate Data Hub integration is evidenced through the corresponding Hub catalogue, wiki, workflow, or service record.

### Completion checklist for this tool

- [ ] Versioned release created and archived
- [ ] At least one successful operational example retained
- [ ] Run manifest, QA report, diagnostics, and delivery manifest archived
- [ ] Climate Data Hub registration or deployment evidence attached
- [ ] Stakeholder demonstration completed
- [ ] Feedback and resulting improvements documented
- [ ] Country coverage claims supported by completed validation evidence
- [ ] Product owner and maintenance arrangements confirmed

---

## Stakeholder engagement and user feedback

The tool is intended to be co-developed and shared with stakeholders, including meteorological services, disaster-risk-management institutions, agriculture and livestock authorities, ILRI programmes, researchers, and other Climate Data Hub users.

A lightweight feedback log should be maintained for demonstrations and operational use.

| Date | Stakeholder or user group | User need or issue | Change made or decision | Evidence link |
|---|---|---|---|---|
| YYYY-MM-DD | Institution or team | Requirement, problem, or requested improvement | Implemented change, planned action, or documented limitation | Meeting note, issue, email, presentation, or release |

Recommended engagement evidence includes:

- user-needs interviews or consultation notes;
- demonstration agendas and participant lists;
- screenshots or recordings of the demonstration;
- GitHub issues or change requests linked to stakeholder feedback;
- training materials and attendance records;
- acceptance or handover notes; and
- examples showing how the harmonized data supported a model, dashboard, advisory, or analysis.

---

## GESI and responsible implementation

The associated result carries a **GESI tag of 1 — Significant**. The software itself does not establish a GESI outcome, but its implementation and documentation can support inclusive access and accountable use.

Recommended actions include:

- document user groups and barriers to accessing climate data and analytical tools;
- provide clear, low-complexity command examples and reusable configuration templates;
- provide training and documentation suitable for users with different technical backgrounds;
- consider low-bandwidth or offline delivery options for large datasets and reports;
- record the participation of women, youth, and underrepresented user groups in consultations and training where appropriate;
- avoid presenting model-ready data as decision-ready advice without domain interpretation; and
- document data limitations, uncertainty, licences, and responsible-use conditions.

---

## Current limitations and roadmap

### Current limitations

- Operational country configurations are currently limited to Ethiopia, Kenya, and Somalia.
- Formal Climate Data Hub registration or deployment is not demonstrated by the repository alone.
- Climate source availability, licences, credentials, calendars, and naming conventions can vary by provider.
- Large multi-country and multi-decadal requests can require substantial storage, memory, and processing time.
- Automated checks cannot replace expert review of physical plausibility and suitability for a specific impact model.
- The repository does not currently declare a formal open-source licence; users should confirm reuse and redistribution terms with the maintainers.
- A GitHub Pages workflow publishes run evidence, but automated test execution should be added to continuous integration if not managed elsewhere.

### Priority roadmap

1. Register the product in the Climate Data Hub catalogue or wiki.
2. Agree and implement the Hub access pattern: linked product, container, API, scheduled workflow, or managed service.
3. Create a tagged institutional release with an archived evidence package.
4. Add documented operational examples for Ethiopia and Kenya.
5. Add and validate Ghana, Tanzania, and Uganda configurations where required by the result geography.
6. Publish a short methodology and governance note.
7. Conduct stakeholder demonstrations and document feedback-driven improvements.
8. Add automated test execution and release checks in GitHub Actions.
9. Add a formal software licence and contribution guidance after institutional approval.
10. Develop optional dashboard or API access for users who do not work through the command line.

---

## Tech stack

| Layer | Technology |
|---|---|
| Language and packaging | Python 3.10+, setuptools |
| Array and NetCDF processing | xarray, NumPy, pandas, SciPy, netCDF4, h5netcdf, Dask |
| Spatial processing | GeoPandas, rioxarray, Shapely, pyproj, Fiona |
| Climate-data acquisition | cdsapi and source-specific connectors/scripts |
| Visualization | Matplotlib, Cartopy |
| Configuration | PyYAML |
| Manifest validation | jsonschema |
| Progress and logs | tqdm and Python logging |
| Testing | pytest and pytest-cov |
| Reporting automation | Static HTML report generation and GitHub Actions Pages deployment |

---

## Project structure

```text
climate-agent/
├── run_agent.py                 # command-line entry point
├── agent_config.yaml            # runtime configuration
├── run_manifest_schema.json     # manifest JSON schema
├── pyproject.toml               # package metadata and dependencies
├── requirements.txt
├── README.md
├── USAGE.md
│
├── agent/                       # control and observability planes
│   ├── router.py
│   ├── planner.py
│   ├── orchestrator.py
│   ├── policy.py
│   ├── state_store.py
│   ├── artifact_manager.py
│   ├── preflight.py
│   └── output_resolver.py
│
├── connectors/                  # source-specific command builders
│   ├── agera5_connector.py
│   ├── chirps_connector.py
│   └── isimip_connector.py
│
├── validation/                  # quality checks
│   ├── schema_checks.py
│   ├── time_checks.py
│   ├── spatial_checks.py
│   └── anomaly_checks.py
│
├── scripts/                     # deterministic processing and reporting tools
│   ├── run_historical_workflow.py
│   ├── run_projection_workflow.py
│   ├── run_future_vpd_workflow.py
│   ├── agera5_download.py
│   ├── download_chirps.py
│   ├── generate_report.py
│   └── ...
│
├── boundaries/                  # country boundary files
│   ├── ethiopia_adm0.geojson
│   ├── kenya_adm0.geojson
│   └── somalia_adm0.geojson
│
├── tests/                       # unit, integration, and dry-run tests
│   └── ...
│
└── .github/workflows/
    └── pages.yml                # publishes the static run-evidence report
```

---

## Configuration

Runtime settings are defined in [`agent_config.yaml`](agent_config.yaml).

| Section | Purpose |
|---|---|
| `paths` | Raw, intermediate, final, diagnostic, manifest, and log directories |
| `reference_grid` | Historical reference data and configured target resolution |
| `countries` | Country codes, names, and boundary files |
| `variables` | Long names, canonical units, source assignments, and valid ranges |
| `scenarios` | Supported historical and future scenarios |
| `validation` | Strict/fast mode, missing-data thresholds, and spatial tolerances |
| `retry` | Maximum attempts, backoff schedule, and retryable exit codes |
| `compression` | Compression settings for intermediate and final NetCDF files |
| `parallel` | Worker limits and subprocess isolation |
| `cleanup` | Retention of raw and intermediate data |
| `cds` | Copernicus endpoint and request timing settings |
| `logging` | Logging level and captured stdout/stderr lines |

Country or variable expansion should be made through reviewed configuration and tests rather than by changing output paths manually.

---

## Testing

Install development dependencies and run the test suite:

```bash
pip install -e ".[dev]"
pytest tests/ -q
pytest tests/ -q --cov=agent
```

Run focused tests during development:

```bash
pytest tests/test_validation_engine.py -v
pytest tests/test_orchestrator.py -v
pytest tests/test_e2e_dryrun.py -v
```

For a documentation-only change, verify that Markdown code fences and internal file links are valid. For code, configuration, country, variable, or workflow changes, run the relevant unit and integration tests before release.

---

## Data sources

| Source | Variables or use | Provider |
|---|---|---|
| [AgERA5](https://cds.climate.copernicus.eu/datasets/sis-agrometeorological-indicators) | Historical temperature, relative humidity, and related agrometeorological indicators | Copernicus Climate Change Service / ECMWF |
| [CHIRPS v2.0](https://www.chc.ucsb.edu/data/chirps) | Historical precipitation | Climate Hazards Center, University of California, Santa Barbara |
| [ISIMIP3b](https://www.isimip.org/) | Bias-adjusted climate-model projections and impact-modelling inputs | Inter-Sectoral Impact Model Intercomparison Project |

Users are responsible for complying with each provider’s licence, citation, access, and redistribution conditions. Generated outputs should retain source attribution and processing metadata.

---

## Citation and contacts

### Suggested software citation

Until a formal release and DOI are created, cite the repository as:

> Mersha, Y. *Climate Data Harmonization Agent: automated acquisition, harmonization, validation, and delivery of climate datasets*. ILRI Climate Services. Version 0.1.0. GitHub repository: `YonSci/climate-agent`.

For a formal institutional release, add:

- the release date;
- version tag;
- Git commit SHA;
- DOI or institutional repository identifier, when available; and
- the corresponding Climate Data Hub catalogue or wiki record.

### Questions, collaboration, and data requests

**ILRI Climate Services — Livestock, Climate and Environment**

- Yonas Mersha — [Y.Mersha@cgiar.org](mailto:Y.Mersha@cgiar.org)
- Dr Teferi Demissie — [t.demissie@cgiar.org](mailto:t.demissie@cgiar.org)

For software problems or feature requests, open a GitHub issue and include the command used, run ID, relevant manifest or log excerpt, operating system, and expected behaviour. Do not include credentials, private data, or restricted source files in public issues.
