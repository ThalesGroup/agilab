# Changelog

All notable public AGILAB changes are summarized here. GitHub Releases remain
the publication surface for tagged release artifacts; this file gives reviewers
and adopters a versioned, repository-local upgrade trail.

## [2026.4.27] - 2026-04-24

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.24

### Changed

- Published AGILAB `2026.4.27` to PyPI for `agilab`, `agi-core`,
  `agi-env`, `agi-node`, and `agi-cluster`.
- Aligned the latest GitHub Release page with the PyPI-published code.
- Added release automation so future PyPI publishes create or update the
  matching GitHub Release after pushing the tag.

## [2026.04.25] - 2026-04-24

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.25

### Added

- Added `tools/kpi_evidence_bundle.py`, a machine-readable cross-KPI evidence
  bundle for overall public evaluation.
- Added `tools/production_readiness_report.py` evidence reporting for the
  bounded production-readiness pilot scope.
- Added public Hugging Face Space smoke checks covering Streamlit health, base
  app, `flight_project`, `view_maps`, `view_maps_network`, and public app-tree
  guardrails.
- Added public KPI evidence in README/docs for ease of adoption, research
  experimentation, engineering prototyping, strategic potential, and production
  readiness.

### Changed

- Promoted the public AGILAB Hugging Face demo compatibility slice from
  `documented` to `validated` after smoke coverage and private-app guardrails.
- Published the first GitHub Release page for AGILAB so external reviewers can
  inspect release notes without relying only on tags or PyPI metadata.
- Made benchmark mode selection explicit in the public runtime flow.
- Clarified MLOps positioning: AGILAB is a research/prototyping workbench and
  controlled pilot surface, not a production MLOps replacement.

### Fixed

- Fixed hosted analysis-page routing so public demo views do not fall back to
  `127.0.0.1`.
- Fixed missing Flight seed dataset handling on Hugging Face Spaces.
- Fixed notebook export/app-root handling for public first-run snippets.
- Fixed view-map network settings persistence and related public analysis-page
  behavior.

### Validation

- `tools/kpi_evidence_bundle.py --compact --run-hf-smoke`: pass, including live
  Hugging Face route checks and no non-public app entries.
- `tools/sync_docs_source.py --verify-stamp`: pass.
- Pull request checks for the evidence bundle and release-readiness changes:
  pass.

### Scope Limits

- AGILAB is still alpha-stage public software.
- This release improves release ergonomics, public evidence, and demo
  reliability; it does not add production model serving, feature stores, online
  monitoring, drift detection, enterprise governance, or broad remote-topology
  certification.

[2026.4.27]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.24
[2026.04.25]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.25
