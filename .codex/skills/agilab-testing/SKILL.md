---
name: agilab-testing
description: Quick, targeted test strategy for AGILAB (core unit tests, app smoke tests, regression).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-07
---

# Testing Skill (AGILAB)

Use this skill when validating changes.

## Philosophy

- Start small and local: run only the tests that cover the files you changed.
- Prefer local validation over CI reruns. If a coverage, test, docs, or badge failure has a local
  command equivalent, run that first. Use GitHub workflows only when the issue is runner-specific,
  matrix-specific, secret-dependent, or part of the final publish/deploy path.
- Avoid “fixing the world”: do not chase unrelated test failures.
- Do not turn a failing app regression into an unapproved shared-core edit. Before changing
  `src/agilab/core/agi-env`, `src/agilab/core/agi-node`, `src/agilab/core/agi-cluster`,
  `src/agilab/core/agi-core`, or shared deploy/build helpers, get explicit user approval.
  First explain why an app-local fix is insufficient and which regression will validate the shared change.
- Prefer fixing the class of failure, not a single symptom. If a regression comes from filesystem
  ordering, polluted `HOME`/`~/.agilab`, or stale cluster config leaking from the runner, harden the
  shared helper or shared test fixture instead of patching just one assertion.

## Regression Hygiene

- User-facing rename sweeps:
  - When renaming a page/app/demo label, grep both the old and new wording across the page package, tests, README files, and `docs/source`.
  - Prefer a side-effect-free metadata module (for example `page_meta.py`) for page titles or other user-facing labels that tests also assert.
  - Make tests import or read that shared metadata instead of duplicating display strings when the page title is part of the contract.
- Filesystem order:
  - Do not assume `glob`, `rglob`, `iterdir`, or `os.scandir` order across macOS, Linux, and GitHub runners.
  - If order is user-visible, sort in the runtime/helper.
  - If order is not part of the contract, compare sorted values or sets in tests.
- Root test isolation:
  - Tests under `test/` must not depend on the real machine `HOME` or an existing `~/.agilab/.env`.
  - Prefer the shared `test/conftest.py` fixtures for a clean fake home; add local monkeypatches only
    when a test truly needs custom env overrides.
- Cluster/share regressions:
  - Keep explicit regressions for “cluster share missing”, “cluster share equals local share”, and
    “no silent fallback to localshare”.
- App settings split:
  - Source `app_settings.toml` files are seeds; mutable settings live in the user workspace.
  - Tests should target the right layer and avoid asserting that runtime writes back into source files.

## Common Commands

- Core tests (repo root):
  - `uv --preview-features extra-build-dependencies run --no-sync pytest src/agilab/core/agi-env/test`
  - `uv --preview-features extra-build-dependencies run --no-sync pytest src/agilab/core/test`
- Root repo smoke/coverage step with CI parity:
  - `PYTHONPATH='src' COVERAGE_FILE=.coverage.agilab uv --preview-features extra-build-dependencies run --no-project --with pytest --with pytest-cov --with toml --with packaging python -m pytest -q --maxfail=1 --disable-warnings -o addopts='' -m 'not integration' --cov=agilab --cov-report=xml:coverage-agilab.xml --ignore=src/agilab/test/test_model_returns_code.py src/agilab/test`
- `agi-env` isolated coverage step with CI parity:
  - `COVERAGE_FILE=.coverage.agi-env uv --preview-features extra-build-dependencies run --no-project --with-editable ./src/agilab/core/agi-env --with-editable ./src/agilab/core/agi-node --with sqlalchemy --with pytest --with pytest-cov python -m pytest -q --maxfail=1 --disable-warnings -o addopts='' --cov=agi_env --cov-report=xml:coverage-agi-env.xml src/agilab/core/agi-env/test`
- Shared core isolated coverage step with CI parity:
  - `COVERAGE_FILE=.coverage.agi-node uv --preview-features extra-build-dependencies run --no-project --with-editable ./src/agilab/core/agi-env --with-editable ./src/agilab/core/agi-node --with-editable ./src/agilab/core/agi-cluster --with-editable ./src/agilab/core/agi-core --with sqlalchemy --with pytest --with pytest-asyncio --with pytest-cov python -m pytest -q --maxfail=1 --disable-warnings -o addopts='' --cov=agi_node --cov-report=xml:coverage-agi-node.xml src/agilab/core/test`
- Streamlit page regression (active-app aware):
  - Patch `sys.argv` with `["<page>.py", "--active-app", "<app_path>"]` before `streamlit.testing.v1.AppTest.from_file(...)`.
  - Example:
    `uv --preview-features extra-build-dependencies run pytest -q test/test_view_maps_network.py`
- Service health smoke tests (CI parity on Python 3.13):
  - `COVERAGE_FILE=.coverage.service-health uv --preview-features extra-build-dependencies run --no-project --with-editable ./src/agilab/core/agi-env --with-editable ./src/agilab/core/agi-node --with-editable ./src/agilab/core/agi-cluster --with-editable ./src/agilab/core/agi-core --with sqlalchemy --with pytest --with pytest-asyncio --with pytest-cov python -m pytest -q -o addopts='' --cov=agi_cluster --cov=agi_env --cov-report=xml:coverage-service-health.xml src/agilab/core/test/test_agi_distributor.py::test_agi_serve_health_action_writes_json test/test_service_health_check.py`

- Whole repo tests (if needed):
  - `uv --preview-features extra-build-dependencies run --no-sync pytest`

## Coverage Notes

- CI combines `.coverage*` artifacts; keep service health smoke coverage in
  `.coverage.service-health` to match the workflow guardrails.
- If a CI step fails before tests run, distinguish:
  - exit code `2`: often environment/tooling/collection failure
  - exit code `1`: often an actual test failure after collection
- For AGILab monorepo coverage jobs, do not assume the root `uv run pytest ...` environment is the right reproduction target. Use the isolated no-project commands above first.

## Preview / Report Alignment Regressions

- When a custom form shows a derived metric and the runtime also writes that metric into a summary/report, prefer testing the shared backend helper first.
- Add a targeted regression for the generated artifact fields as well, so the persisted report stays aligned with the preview contract.
- Only add a full Streamlit `AppTest` when the bug is in widget wiring or session-state behavior. If the logic lives in a backend helper, test that helper directly and keep the UI test surface small.
- Good alignment checks include:
  - preview helper returns the expected metric/range
  - generated summary contains the same field names
  - the summary value is derived from the same scale/selection logic as the preview, not from a second implementation

## Adding Coverage (Easy Wins)

- Add narrow unit tests for pure functions/helpers (path resolution, parsing, small transforms).
- Prefer tests that don’t require network, GPUs, or large datasets.
- For apps-pages, keep one built-in app regression in-repo and treat large external app contexts as smoke/performance checks unless the test fixture provides their datasets.
