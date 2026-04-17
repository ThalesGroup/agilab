---
name: agilab-installer
description: Guidance for installing AGILAB, installing apps/pages, and debugging install/test failures.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-17
---

# AGILAB Installer Skill

Use this skill when working on:
- `install.sh` / `install.ps1` (root installer)
- `src/agilab/install_apps.sh` / `src/agilab/install_apps.ps1` (apps/pages installer)
- `src/agilab/apps/install.py` (app install entry)
- Data seeding / dataset archives / post-install hooks

## Golden Rules

- Use `uv --preview-features extra-build-dependencies …` for Python entrypoints.
- Do not add silent fallbacks (detect missing capabilities and raise actionable errors).
- Keep installs **idempotent**: rerunning should not wipe user data or re-download unnecessarily.
- Before editing or validating installer-related diffs, run
  `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --files install.sh src/agilab/install_apps.sh src/agilab/apps/install.py`
  or point it at the actual changed install/deploy files. Use the output to confirm whether install
  repros, shared-core approval, or extra artifact refreshes are required.
- Treat installer/build/deploy changes as shared-core work. Before editing shared install plumbing,
  `agi_dispatcher` install hooks, or generic cluster deployment code, get explicit user approval
  and explain the expected cross-app impact first.

## Common Commands

- Full install with app tests (macOS/Linux):
  - `./install.sh --non-interactive --cluster-ssh-credentials user:pass --apps-repository /path/to/apps-repo --install-apps --test-apps`
- Add core suites only when needed:
  - macOS/Linux: `./install.sh --install-apps --test-apps --test-core`
  - Windows: `.\install.ps1 -InstallApps -TestApps -TestCore`
- Apps/pages install only:
  - `cd src/agilab && ./install_apps.sh --test-apps`

## Installer test switches

- App tests stay opt-in via `--test-apps` / `-TestApps`.
- Root core suites stay opt-in via `--test-core` / `-TestCore`.
- Do not make core suites implicit in the default developer install path unless the user explicitly asks for that stricter gate.

## Debugging Patterns

- **“Does not appear to be a Python project”**
  - You are installing a directory without `pyproject.toml`/`setup.py`.
  - Ensure the installer runs `uv pip install -e .` from the repo root.

- **App install fails with missing worker/manager**
  - Validate both manifests exist:
    - manager: `.../<app>_project/pyproject.toml`
    - worker:  `.../<app>_project/src/<app>_worker/pyproject.toml`

- **Plain `uv sync` works, AGILAB install still fails in worker phase**
  - Treat this as a shared installer candidate before patching the app.
  - `tools/impact_validate.py` should report this path as an install-contract gate; do not push until
    both repro commands below are green.
  - Compare:
    - plain shell: `uv sync --project <app>`
    - AGILAB path: `uv run python src/agilab/apps/install.py <app> --verbose 1`
  - Run the contract checker against the copied worker project before changing app code:
    - `uv --preview-features extra-build-dependencies run python tools/install_contract_check.py --app-path <app-project-path> --worker-copy ~/wenv/<app>_worker`
  - Inspect the copied worker manifest:
    - `~/wenv/<app>_worker/pyproject.toml`
  - If the checker reports `shared-core-installer-issue`, treat that as a shared install-plumbing bug first.
  - If that worker file gained a conflicting exact pin that is not present in the source app manifest, the usual causes are:
    - nested `uv` subprocesses inheriting `UV_RUN_RECURSION_DEPTH`
    - `_deploy_local_worker()` appending exact dependency pins into the worker copy
    - local core packages (`agi-env`, `agi-node`) being added one by one instead of together as local paths
    - missing `read_agilab_path()` causing a source checkout app to be treated like a generated install artifact
  - Typical symptom:
    - manager install and worker build succeed
    - failure appears later at `uv add agi-env` / `uv add agi-node` or worker `uv sync`
    - the error mentions an unsatisfiable transitive dependency conflict from the copied worker project

- **Dataset extraction wipes seeded files**
  - Avoid mtime heuristics on extracted files; use a stamp file tied to the archive.
  - Prefer linking to shared datasets rather than copying to each app.

## Data Dependencies Between Apps

Some apps depend on outputs of others (e.g. LinkSim needs satellite trajectories).
Preferred approach:
- Install/seed the producing app first.
- Reuse outputs via symlink/junction into the dependent dataset folder to avoid duplication.
