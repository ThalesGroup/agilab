---
name: agilab-testing
description: Quick, targeted test strategy for AGILAB (core unit tests, app smoke tests, regression).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-02-27
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
- Service health smoke tests (CI parity on Python 3.13):
  - `COVERAGE_FILE=.coverage.service-health uv --preview-features extra-build-dependencies run pytest -q src/agilab/core/test/test_agi_distributor.py::test_agi_serve_health_action_writes_json test/test_service_health_check.py`

- Whole repo tests (if needed):
  - `uv --preview-features extra-build-dependencies run --no-sync pytest`

## Coverage Notes

- CI combines `.coverage*` artifacts; keep service health smoke coverage in
  `.coverage.service-health` to match the workflow guardrails.

## Adding Coverage (Easy Wins)

- Add narrow unit tests for pure functions/helpers (path resolution, parsing, small transforms).
- Prefer tests that don’t require network, GPUs, or large datasets.
