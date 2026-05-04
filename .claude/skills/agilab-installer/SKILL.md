---
name: agilab-installer
description: Guidance for installing AGILAB, installing apps/pages, and debugging install/test failures.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-04-28
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
- Full clean source validation from a new public clone:
  - `cache_root="${XDG_CACHE_HOME:-$HOME/.cache}/agilab/source_validate"; root="$cache_root/agilab_source_validate_clean_$(date +%Y%m%d_%H%M%S)"; mkdir -p "$root/home"; HOME="$root/home" git clone https://github.com/ThalesGroup/agilab.git "$root/home/agilab"`
  - `cd "$root/home/agilab" && git lfs install --local && git lfs pull`
  - `HOME="$root/home" AGI_LOCAL_DIR="$PWD/localshare" ./install.sh --non-interactive --agi-share-dir "$PWD/clustershare" --install-apps builtin --test-root --test-core --test-apps --skip-offline`
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

- **Full source install validation**
  - Use an isolated `HOME` under the new validation root. Do not rely on the
    developer machine's `~/.agilab/.env`, `~/wenv`, `~/localshare`, or previous
    install logs when proving a release candidate.
  - Pass both `--agi-share-dir "$PWD/clustershare"` and `AGI_LOCAL_DIR="$PWD/localshare"`
    in the clean clone so cluster/local share values are written before root,
    core, app, and demo validation.
  - Run `git lfs pull` before install validation whenever built-in apps depend
    on LFS-backed archives, especially `flight_project` dataset seeding.
  - If an early install attempt used the real user `HOME`, discard that result
    as environment-polluted and rerun from a clean isolated `HOME` before
    publishing or deploying.

- **Installer env propagation order**
  - If app tests fail because paths point to stale `~/.agilab/.env` values even
    though the current install command passed `--agi-share-dir` or `AGI_LOCAL_DIR`,
    inspect whether the installer writes env values before validation phases run.
  - The env file must be updated before `--test-root`, `--test-core`, app
    installs, and app tests. A late write can make validation exercise an old
    share directory while the final env file looks correct.

- **Empty list options under `set -u`**
  - For root shell installers, treat empty comma/list options as a first-class
    regression target. An empty value such as `--local-models ""` must not
    expand an unbound array like `${ordered[*]}` under `set -u`.
  - Add shell syntax checks and a unit regression around the option parser when
    changing list-valued installer flags.

- **A previous agent already diagnosed the failure**
  - Do not just confirm the current diagnosis.
  - Re-run the plain repro first to prove where the bug really begins:
    - `uv sync --project <app>`
    - or, for offline manager cases, `uv --offline sync --project <app>`
  - Then assess the diagnostic itself:
    - what part is solid
    - what assumptions are still weak
    - what coverage gap allowed the bug to survive
    - whether the proposed fix is only the obvious fix or the better fix
  - Prefer this one-query pattern when you want the strongest first answer:
    - `Assess the diagnostic below and find the better fix. Keep the plain repro as the first discriminator. Identify the real root cause, regression chain, weak points in the current diagnosis, the better fix, why it is better than the obvious fix, and the regression plan.`
  - In AGILAB install bugs, explicitly compare:
    - app-local workaround
    - shared-core installer fix
    - diagnostic/preflight improvements such as `tools/install_contract_check.py`
  - If the failure starts before worker build or runtime execution, treat that as installer-contract evidence, not app-runtime evidence.

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
