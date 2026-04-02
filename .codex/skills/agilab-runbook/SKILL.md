---
name: agilab-runbook
description: Runbook for working in the AGILab repo (uv, Streamlit, run configs, packaging, troubleshooting).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  short-description: AGILab repo runbook
  updated: 2026-04-02
---

# AGILab runbook (Agent Skill)

Use this skill when you need repo-specific “how we do things” guidance in `agilab/`: launching Streamlit, regenerating run-config wrappers, debugging installs, or preparing releases.

## Background: Agent Skills (status update 2026-01-08)

- Codex now supports **Agent Skills** using the open **Agent Skills** standard (`SKILL.md` + folder layout).
- Skills support **progressive disclosure**: only name/description load initially; full instructions load when invoked.
- Skill scopes: repo (`.codex/skills/…`), user (`~/.codex/skills/…`), and admin/system (`/etc/codex/skills/…`).
- Security note: skills are executable/context-bearing packages; treat third-party skills as supply-chain inputs (audit, pin versions, prefer sandboxes/approvals).

## AGILab working rules (repo policy)

- **Use `uv` for all runs** so dependencies resolve in managed envs:
  - `uv --preview-features extra-build-dependencies run python …`
  - `uv --preview-features extra-build-dependencies run streamlit …`
- **No repo `uvx`**: do not run `uvx agilab` from this checkout (it will run the published wheel and ignore local changes).
- **Run config parity**: after editing `.idea/runConfigurations/*.xml`, regenerate wrappers:
  - `uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py`
- **Shared core approval gate**: do not edit shared core technology without explicit user approval first.
  This includes `src/agilab/core/agi-env`, `src/agilab/core/agi-node`, `src/agilab/core/agi-cluster`,
  `src/agilab/core/agi-core`, shared installer/build/deploy code, and generic helpers reused across apps/pages.
  Prefer app-local fixes first. If a core edit looks necessary, stop and explain the required files,
  blast radius, and validation plan before making the change.
- **Docs source of truth**: edit docs in the sibling repo
  `../thales_agilab/docs/source` (machine path:
  `/Users/agi/PycharmProjects/thales_agilab/docs/source`).
- **Generated docs in this repo**: treat `docs/html` (including `docs/html/_sources`)
  as build output only. Do not hand-edit files in `docs/html`; always edit source
  first and regenerate from `../thales_agilab/docs/source`.
  - Canonical rebuild command:
    `uv --preview-features extra-build-dependencies run --project ../thales_agilab --group sphinx python -m sphinx -b html ../thales_agilab/docs/source docs/html`
- **Streamlit API**: do not add `st.experimental_rerun()`; use `st.rerun`.
- **No silent fallbacks**: avoid runtime “auto-fallbacks” between API clients or parameter rewrites; fail fast with actionable errors.

## Common commands (from the runbook matrix)

- Dev UI: `cd "$PROJECT_DIR" && uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py -- --openai-api-key "…" --apps-path src/agilab/apps`
- Apps-pages smoke: `cd "$PROJECT_DIR" && uv --preview-features extra-build-dependencies run python tools/smoke_preinit.py --active-app src/agilab/apps/builtin/flight_project --timeout 20`
- Apps-pages regression (AppTest): `cd "$PROJECT_DIR" && uv --preview-features extra-build-dependencies run pytest -q test/test_view_maps_network.py`
- Publish dry-run (TestPyPI): `cd "$PROJECT_DIR" && uv --preview-features extra-build-dependencies run python tools/pypi_publish.py --repo testpypi --dry-run --leave-most-recent --verbose`

## CI and badge checks

- CI badge is pinned to `main`:
  - `https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main`
- When checking recent workflow state, prefer the GitHub Actions runs API:
  - `uv --preview-features extra-build-dependencies run python - <<'PY' ... https://api.github.com/repos/ThalesGroup/agilab/actions/workflows/ci.yml/runs?per_page=10 ... PY`
- Public job logs may not be directly retrievable without auth. Use the runs/jobs API first to identify the failing step, then reproduce that exact command locally.
- For AGILab specifically, the Shields dynamic JSON badge for PyPI can lag or serve stale data. Prefer the stable PyPI version badge endpoint:
  - `https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300`
- After a release, verify all three surfaces separately before trusting badge state:
  - PyPI JSON: `https://pypi.org/pypi/agilab/json`
  - PyPI simple index: `https://pypi.org/simple/agilab/`
  - Shields badge: `https://img.shields.io/pypi/v/agilab.svg?cacheSeconds=300`

## CI workflow lessons

- The root `src/agilab/test` step is more stable when run from the source tree instead of the full project environment:
  - `PYTHONPATH='src' COVERAGE_FILE=.coverage.agilab uv --preview-features extra-build-dependencies run --no-project --with pytest --with pytest-cov --with toml --with packaging python -m pytest ... --ignore=src/agilab/test/test_model_returns_code.py src/agilab/test`
- The integration-only `src/agilab/test/test_model_returns_code.py` should be ignored in CI collection, not merely deselected by marker, because import-time behavior can still break collection.
- Core package coverage steps are more reliable when each step uses an isolated no-project env with explicit editable core packages and test-only extras, instead of relying on the monorepo root env.
- `agi-env` tests need:
  - editable `./src/agilab/core/agi-env`
  - editable `./src/agilab/core/agi-node`
  - `sqlalchemy`
- Shared core tests (`src/agilab/core/test`) need:
  - editable `./src/agilab/core/agi-env`
  - editable `./src/agilab/core/agi-node`
  - editable `./src/agilab/core/agi-cluster`
  - editable `./src/agilab/core/agi-core`
  - `sqlalchemy`
  - `pytest-asyncio`
- Coverage combine/XML generation should use an isolated coverage toolchain too:
  - `uv --preview-features extra-build-dependencies run --no-project --with coverage --with pytest-cov python -m coverage ...`

## Troubleshooting reminders

- Missing import: check both manager and worker `pyproject.toml` scopes (`src/agilab/apps/<app>/pyproject.toml` and `src/agilab/apps/<app>/src/<app>_worker/pyproject.toml`).
- Installer pip issue: run `uv --preview-features extra-build-dependencies run python -m ensurepip --upgrade` once in the target venv.
