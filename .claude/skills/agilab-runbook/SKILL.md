---
name: agilab-runbook
description: Runbook for working in the AGILab repo (uv, Streamlit, run configs, packaging, troubleshooting).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  short-description: AGILab repo runbook
  updated: 2026-04-08
---

# AGILab runbook (Agent Skill)

Use this skill when you need repo-specific “how we do things” guidance in `agilab/`: launching Streamlit, regenerating run-config wrappers, debugging installs, or preparing releases.

## AGILab working rules (repo policy)

- **Use `uv` for all runs** so dependencies resolve in managed envs:
  - `uv --preview-features extra-build-dependencies run python …`
  - `uv --preview-features extra-build-dependencies run streamlit …`
- **No repo `uvx`**: do not run `uvx agilab` from this checkout (it will run the published wheel and ignore local changes).
- **Run config parity**: after editing `.idea/runConfigurations/*.xml`, regenerate wrappers:
  - `uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py`
- **Local-first validation**: do not jump to GitHub Actions when the same check can be run locally.
  Reproduce with the narrowest local command first: targeted `pytest`, isolated coverage commands,
  `py_compile`, Sphinx builds, badge generation, or publish dry-runs. Use CI only for GitHub-only
  behavior such as runner differences, OS/Python matrix coverage, permissions/secrets, or the final
  publish/deploy step.
- **Clone policy**: in the PROJECT page, keep two clone classes explicit:
  - temporary clones may share the source `.venv` by symlink for lightweight local experiments
  - working clones should detach `.venv` and rerun `INSTALL` before `EXECUTE`
  Do not treat a shared `.venv` clone as a durable environment, and do not leave renamed projects
  with `.venv` symlinks pointing at the old project path.
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

## Git footprint maintenance

- Distinguish clearly between:
  - working-tree footprint (`.venv`, caches, build artifacts)
  - local Git footprint (`.git/objects`, `.git/lfs`)
  - remote repository history size
- If the user asks to reduce `.git` only, do not touch `.venv`.
- Measure before acting:
  - `du -sh .git .git/objects .git/lfs`
  - `git count-objects -vH`
  - `git lfs prune --dry-run`
- Prefer the safest local win first:
  - run `git lfs prune` when the dry-run shows meaningful reclaimable space
  - this reduces local `.git/lfs` without rewriting history
- For actual history reduction:
  - use `git filter-repo`, never ad hoc low-level object surgery
  - work in an isolated `--mirror` clone, not in the main checkout
  - create a backup bundle before rewriting: `git bundle create /tmp/<repo>-pre-rewrite.bundle --all`
  - preserve any uncommitted local files outside the checkout before realigning branches
  - rewrite only the intended refs/paths; avoid touching `gh-pages` or unrelated refs unless requested
  - after force-pushing rewritten refs, realign the local checkout to the new `origin/*` history and run:
    - `git reflog expire --expire=now --all`
    - `git gc --prune=now`
- Typical low-value history targets:
  - generated `docs/html/**`
  - `.idea/shelf/**`
  - obsolete legacy paths or duplicated archives
- Do not promise a smaller remote repository from local pruning alone. Local LFS prune and local GC only affect the clone on disk.

## Common commands (from the runbook matrix)

- Dev UI: `cd "$PROJECT_DIR" && uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py -- --openai-api-key "…" --apps-path src/agilab/apps`
- Apps-pages smoke: `cd "$PROJECT_DIR" && uv --preview-features extra-build-dependencies run python tools/smoke_preinit.py --active-app src/agilab/apps/builtin/flight_project --timeout 20`
- Apps-pages regression (AppTest): `cd "$PROJECT_DIR" && uv --preview-features extra-build-dependencies run pytest -q test/test_view_maps_network.py`
- Publish dry-run (TestPyPI): `cd "$PROJECT_DIR" && uv --preview-features extra-build-dependencies run python tools/pypi_publish.py --repo testpypi --dry-run --leave-most-recent --verbose`

## CI and badge checks

- Prefer local reproduction before rerunning workflows:
  - if a failing step has a local command equivalent, run that first and fix locally
  - only rerun a workflow after the local equivalent is green or when the issue is GitHub-specific
- CI badge is pinned to `main`:
  - `https://github.com/ThalesGroup/agilab/actions/workflows/ci.yml/badge.svg?branch=main`
- When checking recent workflow state, prefer the GitHub Actions runs API:
  - `uv --preview-features extra-build-dependencies run python - <<'PY' ... https://api.github.com/repos/ThalesGroup/agilab/actions/workflows/ci.yml/runs?per_page=10 ... PY`
- Public job logs may not be directly retrievable without auth. Use the runs/jobs API first to identify the failing step, then reproduce that exact command locally.
- For AGILAB specifically, the GitHub README now uses a static, versioned PyPI badge committed under `badges/`:
  - `https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/pypi-version-agilab.svg`
- The live PyPI page can still lag until a new package is actually published; do not infer package publication from the GitHub badge alone.
- After a release, verify all three surfaces separately before trusting version state:
  - PyPI JSON: `https://pypi.org/pypi/agilab/json`
  - PyPI simple index: `https://pypi.org/simple/agilab/`
  - GitHub static badge: `https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/pypi-version-agilab.svg`
- If the version changes, update the static badge in the same commit series as the version bump so `main`, the README, and the release metadata stay aligned.

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
- For a reinstalled cluster node, separate host-key repair from auth repair:
  - host key changed:
    - `ssh-keygen -R <ip>`
    - `ssh-keyscan -H -t ed25519 <ip> >> ~/.ssh/known_hosts`
  - user key missing on remote:
    - `ssh-copy-id agi@<ip>`
    - or recreate `~/.ssh/authorized_keys` with `0700` / `0600` permissions
- If cluster mode depends on shared storage, restore the node’s `.agilab/.env` and remount the share before blaming AGILAB:
  - Linux node example:
    - `AGI_CLUSTER_SHARE=/home/agi/clustershare`
    - `AGI_LOCAL_SHARE=/home/agi/localshare`
    - `sshfs agi@192.168.20.111:/Users/agi/clustershare /home/agi/clustershare`
- After a reinstall, validate both directions explicitly before rerunning installs:
  - `ssh agi@<ip> 'echo ok'`
  - `ssh agi@<ip> 'ssh -o BatchMode=yes agi@<scheduler_ip> hostname'`
