# Contributing to the Climate Data Harmonization Agent

Thank you for helping improve the Climate Data Harmonization Agent. Contributions may include code, tests, documentation, country configurations, data-source connectors, validation methods, operational examples, and Climate Data Hub integration guidance.

## Choose the right channel

- **GitHub Issues:** reproducible bugs, clearly scoped feature requests, documentation defects, and implementation tasks.
- **GitHub Discussions:** usage questions, design proposals, scientific-method discussions, demonstrations, stakeholder feedback, and ideas that are not yet ready for implementation.
- **Wiki:** maintained guidance, tutorials, methodology notes, frequently asked questions, operational procedures, and Climate Data Hub integration documentation.

## Before opening an issue

1. Search existing Issues and Discussions.
2. Reproduce the problem with the smallest practical example.
3. Record the command, run ID, software version or commit SHA, and environment.
4. Remove credentials, personal information, restricted data, and private file paths.
5. Check whether the problem belongs to an upstream data provider rather than this repository.

## Development workflow

1. Fork or create a branch from the current default branch.
2. Keep each pull request focused on one coherent change.
3. Add or update tests for code, configuration, validation, or workflow changes.
4. Update the README, usage guide, or Wiki starter pages when behaviour changes.
5. Run the relevant checks before opening a pull request.

```bash
pip install -e ".[dev]"
pytest tests/ -q
pytest tests/ -q --cov=agent
```

## Adding a country or geography

A country should not be described as operationally supported until the contribution includes:

- an approved boundary file and documented source;
- a country code and configuration entry;
- verified source-data availability;
- representative historical or projection test runs;
- temporal, spatial, unit, and missing-data validation;
- diagnostic review for physical plausibility; and
- documentation of known limitations.

## Adding a variable or data source

Document the provider, dataset version, licence, access method, variable name, canonical unit, valid range, calendar, spatial resolution, temporal resolution, regridding method, and expected output metadata. Add validation and tests that can detect unit, time-axis, grid, and coverage errors.

## Scientific and operational review

Automated tests do not replace expert review. Changes that affect climate interpretation, derived variables, regridding, aggregation, bias adjustment, or impact-model inputs should document the scientific rationale and be reviewed by an appropriate domain expert.

## Stakeholder-driven changes

When a contribution responds to a user or partner request, link the relevant Issue or Discussion and summarize:

- the user need;
- participating stakeholder group or institution;
- the agreed change;
- how the change was validated; and
- any remaining limitation.

Do not publish confidential meeting records or personal information.

## Pull request checklist

- [ ] The change is clearly described and scoped.
- [ ] Relevant tests pass.
- [ ] Documentation is updated.
- [ ] New data sources and dependencies have compatible licences.
- [ ] No credentials, restricted data, or generated large datasets are committed.
- [ ] Geographic and operational claims are supported by evidence.
- [ ] User-facing changes include an example or acceptance criterion.

## Licence

Unless explicitly stated otherwise, contributions submitted to this repository are provided under the Apache License 2.0 in [`LICENSE.md`](LICENSE.md). Do not contribute material that you are not authorized to license under those terms.

## Code of conduct

Be respectful, evidence-based, and constructive. Scientific disagreement is welcome when it focuses on methods, data, assumptions, and reproducible evidence rather than individuals.
