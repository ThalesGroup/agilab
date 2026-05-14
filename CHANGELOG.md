# Changelog

All notable public AGILAB changes are summarized here. GitHub Releases remain
the publication surface for tagged release artifacts; this file gives reviewers
and adopters a versioned, repository-local upgrade trail.

## Unreleased

### Added

- Added `ADOPTION.md` as a single-page route map for evaluators, newcomers,
  external app users, and contributors.
- Expanded app template READMEs so new projects have concrete copy, rename,
  first-run, and validation guidance instead of placeholder titles.

### Changed

- Added route-selection tables to the GitHub and PyPI READMEs so adopters can
  choose between hosted preview, source-checkout proof, package install,
  external app updates, and contribution paths.
- Reworked `CONTRIBUTING.md` around a contributor first-run baseline,
  focused validation commands, and repository hygiene.
- Fixed Docker README badges and stop command formatting, clarified the Codex
  skills README mirror, and tightened app/page README routing guidance.
- Normalized standalone analysis-page README commands to the repository `uv`
  invocation used by the rest of the onboarding docs.
- Collapsed the coverage workflow's duplicate `agi-node` and `agi-cluster`
  core test executions into one combined run that still emits both component
  coverage XML files.
- Reordered the landing-page first-proof wizard around the immediate next
  action and progress summary before diagnostics.
- Split `agi-env` runtime dependencies so headless worker installs no longer pull
  Streamlit; UI consumers now depend on the separate `agi-gui` package under
  `src/agilab/lib/agi-gui`.
- Added a versioned generated-snippet API guard so stale ORCHESTRATE snippets
  ask users to clean up and regenerate after core API changes.

## [2026.05.12.post3] - 2026-05-12

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.12-6

### Changed

- Published AGILAB `2026.05.12.post3` to PyPI for `agi-env`, `agi-gui`, `agi-pages`, `agi-node`, `agi-cluster`, `agi-core`, `agi-apps`, and `agilab`.
- Kept the Trusted Publishing contract visible in the release workflow so each PyPI project/environment claim is auditable before upload.
- Used this corrective post release to prove fresh GitHub OIDC uploads instead of relying on skipped existing distributions.

## [2026.05.12.post2] - 2026-05-12

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.12-5

### Changed

- Published AGILAB `2026.05.12.post2` to PyPI for `agi-env`, `agi-gui`, `agi-pages`, `agi-node`, `agi-cluster`, `agi-core`, `agi-apps`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.12.post1] - 2026-05-12

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.12-5

### Changed

- Published AGILAB `2026.05.12.post1` to PyPI for `agi-env`, `agi-gui`, `agi-pages`, `agi-node`, `agi-cluster`, `agi-core`, `agi-apps`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.11] - 2026-05-11

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.11-5

### Changed

- Published AGILAB `2026.05.11` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.09] - 2026-05-09

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.09

### Changed

- Published AGILAB `2026.05.09` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.08] - 2026-05-08

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.08

### Changed

- Published AGILAB `2026.05.08` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.07] - 2026-05-07

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.07

### Changed

- Published AGILAB `2026.05.07` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.06] - 2026-05-06

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.06-2

### Changed

- Published AGILAB `2026.05.06` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.05.post2] - 2026-05-06

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.06

### Changed

- Published AGILAB `2026.05.05.post2` to PyPI for `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.05.post1] - 2026-05-05

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.05-2

### Changed

- Published AGILAB `2026.05.05.post1` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.05] - 2026-05-05

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.05

### Changed

- Published AGILAB `2026.05.05` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.01.post4] - 2026-05-01

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01-5

### Changed

- Published AGILAB `2026.05.01.post4` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.01.post2] - 2026-05-01

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01-3

### Changed

- Published AGILAB `2026.05.01.post2` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.01.post1] - 2026-05-01

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01-2

### Changed

- Published AGILAB `2026.05.01.post1` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.05.01] - 2026-05-01

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01

### Changed

- Published AGILAB `2026.05.01` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.30.post4] - 2026-04-30

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30-5

### Changed

- Published AGILAB `2026.04.30.post4` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.30.post3] - 2026-04-30

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30-4

### Changed

- Published AGILAB `2026.04.30.post3` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.30.post2] - 2026-04-30

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30-3

### Changed

- Published AGILAB `2026.04.30.post2` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.30.post1] - 2026-04-30

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30-2

### Changed

- Published AGILAB `2026.04.30.post1` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.30] - 2026-04-30

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30

### Changed

- Published AGILAB `2026.04.30` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.29.post7] - 2026-04-29

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-9

### Changed

- Published AGILAB `2026.04.29.post7` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.29.post6] - 2026-04-29

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-8

### Changed

- Published AGILAB `2026.04.29.post6` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.29.post5] - 2026-04-29

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-7

### Changed

- Published AGILAB `2026.04.29.post5` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.29.post4] - 2026-04-29

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-6

### Changed

- Published AGILAB `2026.04.29.post4` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.29.post3] - 2026-04-29

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-5

### Changed

- Published AGILAB `2026.04.29.post3` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.29.post2] - 2026-04-29

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-3

### Changed

- Published AGILAB `2026.04.29.post2` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.29.post1] - 2026-04-29

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29

### Changed

- Published AGILAB `2026.04.29.post1` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.28.post5] - 2026-04-28

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-6

### Changed

- Published AGILAB `2026.04.28.post5` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.28.post4] - 2026-04-28

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-5

### Changed

- Published AGILAB `2026.04.28.post4` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.28.post3] - 2026-04-28

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-4

### Changed

- Published AGILAB `2026.04.28.post3` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.28.post2] - 2026-04-28

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-3

### Changed

- Published AGILAB `2026.04.28.post2` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.04.28.post1] - 2026-04-28

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-2

### Changed

- Published AGILAB `2026.04.28.post1` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.4.27.post9] - 2026-04-27

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-7

### Changed

- Published AGILAB `2026.4.27.post9` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.4.27.post8] - 2026-04-27

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-6

### Changed

- Published AGILAB `2026.4.27.post8` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.4.27.post7] - 2026-04-27

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-5

### Changed

- Published AGILAB `2026.4.27.post7` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.4.27.post6] - 2026-04-27

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-4

### Changed

- Published AGILAB `2026.4.27.post6` to PyPI for `agi-env`, `agi-gui`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.4.27.post5] - 2026-04-27

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-3

### Changed

- Published AGILAB `2026.4.27.post5` to PyPI for `agi-env`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.4.27.post4] - 2026-04-27

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-2

### Changed

- Published AGILAB `2026.4.27.post4` to PyPI for `agi-env`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.4.27.post3] - 2026-04-27

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27

### Changed

- Published AGILAB `2026.4.27.post3` to PyPI for `agi-env`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.4.27.post2] - 2026-04-26

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.26-2

### Changed

- Published AGILAB `2026.4.27.post2` to PyPI for `agi-env`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

## [2026.4.27.post1] - 2026-04-26

GitHub Release: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.26

### Changed

- Published AGILAB `2026.4.27.post1` to PyPI for `agi-env`, `agi-node`, `agi-cluster`, `agi-core`, and `agilab`.
- Updated release metadata so public docs, changelog, PyPI, and GitHub Releases point to the same source tag.
- Kept release automation active so future PyPI publishes create or update the matching GitHub Release after pushing the tag.

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
  app, `flight_telemetry_project`, `view_maps`, `view_maps_network`, and public app-tree
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
[2026.4.27.post1]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.26
[2026.4.27.post2]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.26-2
[2026.4.27.post3]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27
[2026.4.27.post4]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-2
[2026.4.27.post5]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-3
[2026.4.27.post6]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-4
[2026.4.27.post7]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-5
[2026.4.27.post8]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-6
[2026.4.27.post9]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.27-7
[2026.04.28.post1]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-2
[2026.04.28.post2]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-3
[2026.04.28.post3]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-4
[2026.04.28.post4]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-5
[2026.04.28.post5]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.28-6
[2026.04.29.post1]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29
[2026.04.29.post2]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-3
[2026.04.29.post3]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-5
[2026.04.29.post4]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-6
[2026.04.29.post5]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-7
[2026.04.29.post6]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-8
[2026.04.29.post7]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.29-9
[2026.04.30]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30
[2026.04.30.post1]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30-2
[2026.04.30.post2]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30-3
[2026.04.30.post3]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30-4
[2026.04.30.post4]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.04.30-5
[2026.05.01]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01
[2026.05.01.post1]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01-2
[2026.05.01.post2]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01-3
[2026.05.01.post3]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01-4
[2026.05.01.post4]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01-5
[2026.05.05]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.05
[2026.05.05.post1]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.05-2
[2026.05.05.post2]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.06
[2026.05.06]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.06-2
[2026.05.07]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.07
[2026.05.08]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.08
[2026.05.09]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.09
[2026.05.11]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.11-5
[2026.05.12]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.12-2
[2026.05.12.post1]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.12-5
[2026.05.12.post2]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.12-5
[2026.05.12.post3]: https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.12-6
