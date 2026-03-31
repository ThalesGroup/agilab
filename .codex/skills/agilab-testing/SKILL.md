---
name: agilab-testing
description: Quick, targeted test strategy for AGILAB (core unit tests, app smoke tests, regression).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-03-31
---

# Testing Skill (AGILAB)

Use this skill when validating changes.

## Philosophy

- Start small and local: run only the tests that cover the files you changed.
- Avoid “fixing the world”: do not chase unrelated test failures.

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
