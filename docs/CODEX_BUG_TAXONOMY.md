# Codex Bug Taxonomy for AGILAB

This taxonomy is derived from recurring AGILAB Codex sessions, not from generic
LLM advice.

The goal is to help classify a new failure quickly, choose the right first
inspection path, and avoid the wrong fix scope.

## How To Use It

For a new bug:

1. classify the bug family
2. classify the real scope: `app_local`, `shared_core`, or `docs_or_artifacts`
3. inspect the listed files first
4. avoid the listed false moves
5. run the minimum validation that matches the family

Use this together with:

- [tools/impact_validate.py](../tools/impact_validate.py)
- [tools/install_contract_check.py](../tools/install_contract_check.py)
- [tools/workflow_parity.py](../tools/workflow_parity.py)

## Bug Families

### 1. Missing Import After Refactor

- Typical symptom:
  - `NameError`
  - missing support module symbol after helper extraction
- Typical mode:
  - `install`
  - `run`
  - `serve`
- Real scope:
  - usually `shared_core`
- First files to inspect:
  - failing module imports
  - extracted support module imports and call sites
  - thin wrapper modules created during refactor
- Avoid moves:
  - do not patch downstream callers first
  - do not widen the change beyond the traceback path
- Fix pattern:
  - restore the missing import or helper binding
  - add a focused regression test on the exact failing function
- Minimum validation:
  - `py_compile`
  - targeted `pytest`
- Reusable rule:
  - after support-module splits, audit imports before changing behavior

### 2. Mixed Sync/Async Runtime Contract

- Typical symptom:
  - `TypeError: object ... can't be used in 'await' expression`
  - same API behaves differently across machines or dependency versions
- Typical mode:
  - `run`
  - `shutdown`
  - `service`
- Real scope:
  - `shared_core`
- First files to inspect:
  - runtime wrapper around the failing client call
  - any existing mixed sync/async helper in neighboring modules
  - test file for runtime distribution or service lifecycle
- Avoid moves:
  - do not special-case one machine or one Dask build
  - do not wrap everything in broad `except Exception`
- Fix pattern:
  - treat the API result as mixed-contract and await only if needed
  - add both sync and awaitable regressions
- Minimum validation:
  - `py_compile`
  - targeted runtime/shared-core tests
- Reusable rule:
  - external client APIs in AGILAB runtime paths should be treated as contract-variant unless proven stable

### 3. Installer Solver Drift

- Typical symptom:
  - plain `uv sync --project <app>` works
  - AGILAB install path fails later in worker deployment
  - copied worker manifest contains unexpected exact pins or missing local sources
- Typical mode:
  - `install`
- Real scope:
  - often `shared_core`, not `app_local`
- First files to inspect:
  - source manager `pyproject.toml`
  - source worker `src/*_worker/pyproject.toml`
  - copied worker `~/wenv/.../pyproject.toml`
  - deployment-local worker staging logic
- Avoid moves:
  - do not patch app dependencies before comparing all three manifests
  - do not assume `uv sync` success proves AGILAB install plumbing is correct
- Fix pattern:
  - classify with `install_contract_check`
  - fix exact-pin injection, stale `_uv_sources`, or missing local core paths at the install-plumbing layer
- Minimum validation:
  - `tools/install_contract_check.py`
  - `uv sync --project <app>`
  - `uv run python src/agilab/apps/install.py <app> --verbose 1`
- Reusable rule:
  - worker-manifest drift is a first-class AGILAB bug family, not an app-only edge case

### 4. Worker Metadata Or Classification Mismatch

- Typical symptom:
  - unsupported worker group
  - worker class not mapped to install/distribution logic
  - install path fails on base worker assumptions
- Typical mode:
  - `install`
  - `run`
- Real scope:
  - can be `app_local` or `shared_core`
- First files to inspect:
  - app manager metadata
  - worker class / base worker class declaration
  - entrypoint worker-group resolver
- Avoid moves:
  - do not patch distributor mappings before checking app metadata
  - do not assume a custom worker should reuse a default shared mapping silently
- Fix pattern:
  - confirm whether the app declared the wrong worker base
  - only then patch shared resolver logic if the contract is genuinely incomplete
- Minimum validation:
  - targeted entrypoint/install tests
  - one end-to-end install repro for the app
- Reusable rule:
  - classification bugs must separate bad app metadata from missing shared resolver coverage

### 5. Service State Persistence Or Atomic Write Failure

- Typical symptom:
  - state file missing during replace
  - stale heartbeat/restart logic fails around persistence
  - repeated writes collide
- Typical mode:
  - `serve`
  - `status`
  - `service restart`
- Real scope:
  - `shared_core`
- First files to inspect:
  - service state write helper
  - temp file naming strategy
  - lifecycle tests using repeated writes
- Avoid moves:
  - do not treat persistence races as page-level bugs
  - do not keep fixed `*.tmp` names for shared state files
- Fix pattern:
  - use unique same-directory temp files plus atomic replace
  - add repeated-write regression coverage
- Minimum validation:
  - focused service-state tests
  - lifecycle slice covering restart/heartbeat paths
- Reusable rule:
  - repeated state writes need collision-safe temp files, not fixed suffixes

### 6. Streamlit State Or Derived-Value Override

- Typical symptom:
  - saved value disappears on render
  - field silently reverts to recomputed default
  - page state differs across reruns
- Typical mode:
  - `page_render`
  - `settings_edit`
- Real scope:
  - usually `app_local`, sometimes shared page support
- First files to inspect:
  - `app_args_form.py`
  - persisted settings loader
  - session-state initialization
- Avoid moves:
  - do not recompute a stored field unless the stored value is genuinely missing
  - do not hide derived-field logic behind a normal editable widget
- Fix pattern:
  - initialize from persisted state first
  - make derived behavior explicit
  - add AppTest coverage for rerun and persistence paths
- Minimum validation:
  - targeted page/AppTest coverage
- Reusable rule:
  - in AGILAB forms, persisted state wins over recomputed defaults

### 7. Static Artifact Staleness

- Typical symptom:
  - badge does not match real coverage
  - skill mirror or generated index is stale
  - docs output diverges from source
- Typical mode:
  - `coverage`
  - `docs`
  - `skills`
- Real scope:
  - `docs_or_artifacts`
- First files to inspect:
  - source artifact generator
  - generated output
  - workflow definition that refreshes it in CI
- Avoid moves:
  - do not trust committed generated artifacts as live truth
  - do not refresh a badge without the matching local coverage XML
- Fix pattern:
  - refresh through the generator
  - add a focused regression on generator behavior if needed
  - use `workflow_parity`
- Minimum validation:
  - targeted generator test
  - matching `workflow_parity` profile
- Reusable rule:
  - generated artifacts are evidence only when the generating workflow is locally reproducible

### 8. Log Noise Hiding Real Installer Signal

- Typical symptom:
  - huge blank sections or noisy installer output
  - important failure lines buried in formatting noise
- Typical mode:
  - `install`
- Real scope:
  - can be shared tooling
- First files to inspect:
  - top-level log pipeline
  - explicit `echo`, `tee`, or formatting helpers
  - subprocess wrappers
- Avoid moves:
  - do not blame `tee` or the shell without reproducing the exact output path
- Fix pattern:
  - remove AGILAB-owned blank-line emitters
  - collapse repeated blank lines only where needed
- Minimum validation:
  - shell syntax
  - narrow reproduction of the noisy output path
- Reusable rule:
  - log UX bugs are often caused by our own wrappers, not the underlying tool

## Scope Heuristics

Use these scope defaults unless evidence disproves them:

- `app_local`
  - `app_args_form.py`
  - manager/worker app code
  - app settings
  - project-local page logic
- `shared_core`
  - `src/agilab/core/agi-env`
  - `src/agilab/core/agi-node`
  - `src/agilab/core/agi-cluster`
  - shared install/build/deploy/runtime helpers
- `docs_or_artifacts`
  - badges
  - skill mirrors/indexes
  - docs source/build outputs

## Validation Policy Derived From Sessions

Use the narrowest validation that proves the actual fix, then escalate to the
workflow-equivalent path when the bug family requires it.

- refactor/import regression:
  - `py_compile`
  - targeted `pytest`
- mixed sync/async runtime contract:
  - targeted runtime tests with both sync and awaitable paths
- installer solver drift:
  - `install_contract_check`
  - plain `uv sync`
  - real `apps/install.py` repro
- artifacts/docs/skills:
  - generator test
  - matching `workflow_parity` profile
- Streamlit/session-state:
  - AppTest or page-specific regression, not only helper tests

## Session-Derived “Do Not” Rules

- Do not patch app dependencies before comparing copied worker manifests.
- Do not assume external client APIs are always awaitable.
- Do not trust stale badges, generated indexes, or generated docs outputs.
- Do not broaden a refactor regression fix beyond the traceback path without evidence.
- Do not push after only helper tests when the real failure path is installer, UI, or workflow-level.
