# Validation and Evidence

Every operational delivery should include evidence showing what was requested, how it was processed, whether the outputs passed quality checks, and which software version produced them.

## Core checks

| Check | Purpose |
|---|---|
| File existence and non-zero size | Detect missing or incomplete outputs. |
| Expected variable and dimensions | Confirm the file schema matches the request. |
| Canonical units | Prevent silent unit mismatches. |
| Requested temporal coverage | Confirm the requested period is present. |
| Daily-axis continuity | Detect gaps and duplicate dates. |
| Non-missing land coverage | Detect unusable or poorly clipped fields. |
| Grid and spatial bounds | Confirm expected resolution, coordinates, and geographic extent. |
| Cross-file consistency | Confirm related files can be analysed together. |
| Outlier and flat-field checks | Flag implausible values or processing failures for expert review. |

## Recommended evidence package

- tagged release or commit SHA;
- configuration used;
- run manifest;
- run log;
- QA JSON;
- diagnostic plots;
- `run_report.json` or generated HTML report;
- final NetCDF outputs;
- `delivery_manifest.json`;
- short handover note with limitations; and
- Climate Data Hub record or access URL, when integrated.

## Acceptance guidance

A product should be delivered only when required stages succeed or warnings are explicitly reviewed and accepted. Diagnostic plots should be reviewed by a climate or domain expert. Automated validation demonstrates technical consistency but does not prove that a dataset is scientifically appropriate for every impact model or decision.
