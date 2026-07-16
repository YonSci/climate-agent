# Architecture and Workflows

## Four-plane architecture

```mermaid
flowchart TB
    U[User request<br/>country · variable · scenario · period] --> CP

    subgraph CP[Control Plane]
        R[Router<br/>select workflow]
        P[Planner<br/>build dependency graph]
        O[Orchestrator<br/>execute · retry · resume]
        R --> P --> O
    end

    subgraph DP[Data Plane]
        C[Source connectors<br/>AgERA5 · CHIRPS · ISIMIP]
        S[Deterministic processing scripts]
        H[Download · merge · harmonize<br/>aggregate · regrid · clip]
        C --> S --> H
    end

    subgraph QP[Quality Plane]
        SC[Schema and unit checks]
        TC[Time coverage and continuity]
        SPC[Grid and spatial checks]
        AC[Anomaly and flat-field checks]
    end

    subgraph OP[Observability and Delivery Plane]
        M[Run manifest]
        L[Stage logs]
        D[QA diagnostics and reports]
        E[Exported NetCDFs<br/>delivery manifest]
    end

    O --> C
    H --> SC
    H --> TC
    H --> SPC
    H --> AC
    SC --> M
    TC --> M
    SPC --> M
    AC --> M
    M --> D
    M --> E
    O --> L
```

## Operational workflow

```mermaid
flowchart LR
    A[User request] --> B[Preflight]
    B --> C[Plan workflow]
    C --> D[Acquire or locate data]
    D --> E[Merge and harmonize]
    E --> F[Aggregate or derive variables]
    F --> G[Regrid and clip]
    G --> H[Validate]
    H -->|Pass or accepted warning| I[Diagnostics and report]
    H -->|Fail| J[Retry or resume]
    J --> D
    I --> K[Export delivery package]
    K --> L[Model, dashboard, Hub or analysis]
```

## Main modules

| Module | Responsibility |
|---|---|
| `agent/router.py` | Selects the workflow template from the user request. |
| `agent/planner.py` | Constructs the ordered dependency graph. |
| `agent/orchestrator.py` | Executes stages and manages retry, resume, validation, and recording. |
| `agent/state_store.py` | Stores run manifests and supports reproducible recovery. |
| `agent/artifact_manager.py` | Centralizes expected paths and delivery artifacts. |
| `connectors/` | Builds source-specific acquisition commands. |
| `validation/` | Performs schema, temporal, spatial, and anomaly checks. |
| `scripts/generate_report.py` | Produces human-readable run and validation evidence. |

## Design principles

- deterministic processing steps are separated from orchestration;
- each stage has explicit inputs, outputs, and dependencies;
- quality checks are recorded rather than hidden;
- failed slices can be retried without discarding successful work;
- every delivery can be linked to a run manifest and software version; and
- integration products are prepared for registration in the Climate Data Hub.
