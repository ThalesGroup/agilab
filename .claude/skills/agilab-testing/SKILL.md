---
name: agilab-testing
description: Quick, targeted test strategy for AGILAB (core unit tests, app smoke tests, regression).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-16
---

# Testing Skill (AGILAB)

Use this skill when validating changes.

## Philosophy

- For non-trivial diffs, start with
  `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged`
  or `--files ...` and treat its output as the first pass for required validation.
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

## Pipeline Efficiency

- When multiple AGILAB skills are active in the same turn, build one validation
  plan from the final changed-file set instead of running each skill's checks
  independently.
- Run `tools/impact_validate.py` once per stable diff. Reuse its output if no
  files changed since the previous run; rerun only after edits that alter the
  impact surface.
- Batch repeated artifact checks at the end of the edit loop:
  docs mirror sync, release/pre-release coverage badge guard, skill mirror sync,
  Codex skill index generation, and release dry-runs should not run once per skill.
- Run cheap read-only inspections in parallel when possible, but keep write or
  generation commands serialized so generated files do not race.
- If several workflow parity profiles are required, run each required profile
  once. Prefer a single command with repeated `--profile` arguments when the
  tool supports it.

## Regression Hygiene

- KPI/evidence tests:
  - For product KPI snapshots, derive expected scores and release metadata from
    the evidence tool or public snapshot builder instead of duplicating numeric
    literals in several tests.
  - Keep literal thresholds only for policy boundaries or synthetic fixtures
    where the number is the behavior under test.
- User-facing rename sweeps:
  - When renaming a page/app/demo label, grep both the old and new wording across the page package, tests, README files, and `docs/source`.
  - Prefer a side-effect-free metadata module (for example `page_meta.py`) for page titles or other user-facing labels that tests also assert.
  - Make tests import or read that shared metadata instead of duplicating display strings when the page title is part of the contract.
- Filesystem order:
  - Do not assume `glob`, `rglob`, `iterdir`, or `os.scandir` order across macOS, Linux, and GitHub runners.
  - If order is user-visible, sort in the runtime/helper.
  - If order is not part of the contract, compare sorted values or sets in tests.
- Root and core test isolation:
  - Tests under `test/` must not depend on the real machine `HOME` or an existing `~/.agilab/.env`.
  - Prefer the shared `test/conftest.py` fixtures for a clean fake home; add local monkeypatches only
    when a test truly needs custom env overrides.
  - Tests under `src/agilab/core/test` must also run with a fake `HOME`, cleaned AGILAB-related
    environment variables, and a valid temporary `~/.local/share/agilab/.agilab-path` pointing at
    the checkout's `src/agilab` directory. A polluted developer marker must not affect core tests.
  - Reset singleton state and restore class-level mutable state in shared fixtures. In particular,
    tests that stub `AgiEnv.logger` must not leak that stub into later tests that expect the full
    logger API.
- Cluster/share regressions:
  - Keep explicit regressions for “cluster share missing”, “cluster share equals local share”, and
    “no silent fallback to localshare”.
  - For scheduler/worker inventory UI, cover mixed-node summaries: local scheduler
    values, reachable remote worker values, and unreachable-node counters should be
    derived from the same probe result model instead of hand-built display strings.
  - When LAN discovery auto-populates scheduler/workers, test both the discovery
    result and the persisted form fields so the UI cannot show discovered nodes
    without saving executable cluster settings.
- App settings split:
  - Source `app_settings.toml` files are seeds; mutable settings live in the user workspace.
  - Tests should target the right layer and avoid asserting that runtime writes back into source files.
- Streamlit per-project state:
  - When a page reuses one Streamlit session across multiple projects/apps, keep at least one regression for project-switch rehydration.
  - Assert that per-project widget keys are namespaced by project/app instead of using global keys like `"cluster_pool"` or `"cluster_cython"`.
  - If a bug involves preserving UI state across project changes, test the preservation decision separately from the AppTest when possible, so ordering bugs around `pop(...)` or reruns stay easy to diagnose.
- Source/end-user bootstrap regressions:
  - When a source run accidentally renders packaged or end-user paths such as `$HOME/agi-space`,
    add both a cold-bootstrap regression and a warm-session regression with a preexisting stale
    `st.session_state["env"]` or persisted `.agilab` state.
  - Assert the page header/readiness model derives manager and worker paths from the selected
    source checkout and active app, not from stale `APPS_PATH`, `.agilab-path`, or an old
    packaged workspace.
  - For PyCharm/source-install bugs, include a focused AppTest or helper test that runs with
    explicit `--apps-path` and a polluted fake home so the old bug cannot be hidden by the
    developer machine's clean state.
- Workflow action feedback:
  - When a bug is visible only after clicking a workflow button, cover both the
    helper/action function and the UI surface that renders the result.
  - If the message appears inside an expander such as `Orchestration log`, ensure
    the robot opens or inspects that container; widget-presence checks alone are
    not enough.
  - For subprocess-backed actions, test noisy stderr separately from fatal stderr.
    A realistic progress log should not fail unless it contains a concrete fatal
    marker such as traceback, non-zero exit status, missing module, or worker/build
    failure phrase.
  - For robot validation of selected actions, use `--action-button-policy
    click-selected` with explicit `--click-action-labels` and check rendered
    action feedback, not only whether the click completed.
- Installer regressions:
  - For install failures, reproduce both:
    - plain shell: `uv sync --project <app>`
    - real AGILAB path: `uv run python src/agilab/apps/install.py <app> --verbose 1`
  - If the plain shell sync succeeds but the AGILAB path fails, prefer a shared-core installer regression over app-only tests.
  - Inspect the copied worker manifest under `~/wenv/<app>_worker/pyproject.toml` before changing app dependencies.
  - If the copied worker project gained a conflicting exact pin that is not present in the source app manifest, treat that as an install-plumbing bug first.
  - For built-in app worker manifests committed under `src/agilab/apps/builtin/*_project/src/*_worker/pyproject.toml`, validate local `agi-env`/`agi-node` sources relative to the worker manifest directory, not the app root. App-level manifests use `../../../core/...`; nested worker manifests currently need `../../../../../core/...`.
  - If release tooling changes app versions, include nested worker manifests in the version bump so PyPI and HF staging do not carry stale source paths.
  - Good shared regressions for this class are:
    - nested `uv` environment cleanup in `agi_env`
    - worker dependency-rewrite behavior in `agi_distributor`
    - local-source worker adds using consistent local core paths instead of package-index metadata
- Generated AI content:
  - Test the schema boundary and the deterministic downstream artifacts, not just
    the model/client call.
  - For WORKFLOW dataframe generation, cover the safe-action contract path:
    valid JSON contract -> dataframe-schema validation -> deterministic pandas
    code generation -> persisted `generation_mode` / `action_contract` metadata.
  - Add fail-closed regressions for unsupported actions, unknown dataframe columns,
    invalid JSON, and raw Python returned while safe-action mode is selected.
  - Keep raw-Python execution/auto-fix tests explicit about the advanced mode and
    any required sandbox acknowledgement; do not treat those as the default UX.
  - For examples that expose user-facing scores or diagnostic metrics, assert the
    fields are present in persisted CSV/JSON and any reducer output. Good
    examples are `student_score` and `student_score_mean` for diagnostic apps.
  - If actual local model endpoints are unavailable, a temporary local
    Responses-compatible contract server can validate AGILAB plumbing, but the
    test/result must not be described as real model validation.
- Workflow profile failures:
  - If `tools/workflow_parity.py --profile <name>` fails in files unrelated to
    the current diff, keep the narrow changed-file tests green and report the
    exact unrelated failing test. Do not patch unrelated pages just to clear a
    broad profile unless the user approves that scope.
- Concurrent workspace interference:
  - When another session or long-running workflow can rewrite files, re-check
    `git diff` for the touched files before final validation.
  - If your changes disappeared or were rewritten, reapply only your intended
    patch, rerun the narrow affected tests, and call out the interference rather
    than silently assuming the old validation still applies.

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
  - If an AppTest passes in isolation but times out in the full profile, first
    confirm there is no real hang with an isolated run, then raise only that
    test's timeout narrowly. Do not mask global AppTest latency by inflating the
    whole suite timeout.
  - Example:
    `uv --preview-features extra-build-dependencies run pytest -q test/test_view_maps_network.py`
- Focused ORCHESTRATE robot action regression:
  - Use this shape when validating a user-visible ORCHESTRATE action failure:
    `AGILAB_WIDGET_ROBOT_RUNTIME_ISOLATION=current-home uv --preview-features extra-build-dependencies run --with playwright python tools/agilab_widget_robot.py --apps flight_project --pages ORCHESTRATE --apps-pages none --json --json-output /tmp/flight-orchestrate-widget-robot.json --progress-log /tmp/flight-orchestrate-widget-robot.ndjson --interaction-mode full --action-button-policy click-selected --click-action-labels "CHECK distribute" --preselect-labels "Run now" --missing-selected-action-policy fail --runtime-isolation current-home`
- Service health smoke tests (CI parity on Python 3.13):
  - `COVERAGE_FILE=.coverage.service-health uv --preview-features extra-build-dependencies run --no-project --with-editable ./src/agilab/core/agi-env --with-editable ./src/agilab/core/agi-node --with-editable ./src/agilab/core/agi-cluster --with-editable ./src/agilab/core/agi-core --with sqlalchemy --with pytest --with pytest-asyncio --with pytest-cov python -m pytest -q -o addopts='' --cov=agi_cluster --cov=agi_env --cov-report=xml:coverage-service-health.xml src/agilab/core/test/test_agi_distributor.py::test_agi_serve_health_action_writes_json test/test_service_health_check.py`
- Account-free cloud connector validation:
  - Use this when AWS/Azure/GCP compatibility needs evidence but no cloud account or credentials are available.
  - `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile cloud-emulators`
  - This proves connector schemas, local-emulator endpoint boundaries, runtime adapter mappings, and no credential materialization for MinIO/S3, Azurite/Azure Blob, fake-gcs-server/GCS, and local search endpoints.
  - Do not claim real-cloud validation from this profile; IAM, private networking, region behavior, quota, and billing still require opt-in live smoke in a real cloud account.

- Whole repo tests (if needed):
  - `uv --preview-features extra-build-dependencies run --no-sync pytest`

## Release Validation Gate

Use this when the user asks for full documentation alignment, source-install
validation, release, and Hugging Face sync in one flow.

- Keep docs validation separate from installer validation:
  - `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --delete`
  - `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile docs`
- Validate the release candidate from a clean public source clone with an
  isolated `HOME`, not from the developer checkout:
  - clone `https://github.com/ThalesGroup/agilab.git` into a new directory under `$HOME`
  - run `git lfs install --local && git lfs pull`
  - run the installer with `--install-apps builtin --test-root --test-core --test-apps --skip-offline`
  - set `AGI_LOCAL_SHARE="$PWD/localshare"` and `--agi-cluster-share "$PWD/clustershare"`
- If the release includes a first-proof or demo claim, run the demo command from
  that same clean clone and record the produced artifact path plus key metrics.
- Treat benign `uv self update` failures from package-manager-installed `uv` as
  warnings only when the installer catches them and continues; do not ignore
  uncaught install failures.
- After release, verify package publication with a network-level check such as
  `curl https://pypi.org/pypi/agilab/json`, because local Python SSL trust can
  differ from the actual PyPI publication state.
- `repo-guardrails` clean public installs must install the exact
  `docs/source/data/release_proof.toml` package spec via
  `tools/install_release_proof_package.py`, not plain `pip install agilab`.
  Release commits are pushed before PyPI propagation is guaranteed, so an
  unpinned install can validate a stale previous release and fail for the wrong
  artifact.
- Root package dependencies must install on the full clean public install matrix
  (Windows, macOS, Linux). Platform-specific packages such as Apple MLX must
  carry environment markers in `pyproject.toml`, otherwise the released wheel can
  pass local macOS validation and still fail `repo-guardrails` on Windows.
- For partial umbrella patch releases, do not make release-preflight tests assume
  every internal package version equals the root `agilab` version. The umbrella
  may publish a metadata-only post release while exact-pinning already-published
  core libraries; assert exact internal pins and marker correctness instead.
- Supply-chain attestation should validate the release graph, not just equality
  between root and internal package versions. For metadata-only umbrella post
  releases, exact root pins to already-published core/page libraries are valid
  evidence when the internal dependency graph also aligns.
- Real PyPI pre-upload must run the external install matrix guard from the built
  wheel artifacts. It should dry-run `uv pip install` for Windows, Linux, and
  macOS x64 before upload so `repo-guardrails` cannot be the first place a bad
  platform marker or resolver failure appears.
- Verify installed package content from outside the repo checkout with
  `uv run --refresh-package agilab --no-project --with agilab==<version> ...`.
  Running this from the repo can import local source and give a false pass.
- If the release feeds Hugging Face, inspect build logs for `Staged uv source`
  lines and run `tools/hf_space_smoke.py --json` only after the runtime stage is
  `RUNNING` on the uploaded Space SHA.

## Coverage Notes

- CI combines `.coverage*` artifacts; keep service health smoke coverage in
  `.coverage.service-health` to match the workflow guardrails.
- Treat committed coverage badges as CI-canonical for release/pre-release
  freshness. Local macOS coverage can differ by one executable line from Ubuntu
  because optional/runtime compatibility branches may execute differently. If a
  local badge refresh disagrees with the latest green coverage workflow, inspect
  the CI XML artifacts first and align the badge with the CI aggregate instead
  of blindly committing the local percentage.
- Badge-only commits normally do not trigger the coverage workflow. After a
  badge correction, manually dispatch `coverage.yml` on `main` and wait for the
  aggregate badge-freshness job before calling the badge fixed.
- For `agi-gui` coverage parity, keep the optional visualization extra aligned
  with CI (`--extra ui --extra viz`). Tests that import plotting-aware pages can
  require `plotly` even when the touched code is not directly visualization
  logic.
- If a CI step fails before tests run, distinguish:
  - exit code `2`: often environment/tooling/collection failure
  - exit code `1`: often an actual test failure after collection
- For AGILab monorepo coverage jobs, do not assume the root `uv run pytest ...` environment is the right reproduction target. Use the isolated no-project commands above first.
- If `tools/impact_validate.py` reports required artifact refreshes, treat those as part of validation,
  not as optional cleanup.

## Preview / Report Alignment Regressions

- When a custom form shows a derived metric and the runtime also writes that metric into a summary/report, prefer testing the shared backend helper first.
- Add a targeted regression for the generated artifact fields as well, so the persisted report stays aligned with the preview contract.
- Only add a full Streamlit `AppTest` when the bug is in widget wiring or session-state behavior. If the logic lives in a backend helper, test that helper directly and keep the UI test surface small.
- For mixed state-model bugs, prefer both:
  - one helper/unit regression for the source-of-truth or preservation logic
  - one narrow AppTest that proves the page still hydrates and persists the expected project-specific state
- Good alignment checks include:
  - preview helper returns the expected metric/range
  - generated summary contains the same field names
  - the summary value is derived from the same scale/selection logic as the preview, not from a second implementation

## Adding Coverage (Easy Wins)

- Add narrow unit tests for pure functions/helpers (path resolution, parsing, small transforms).
- Prefer tests that don’t require network, GPUs, or large datasets.
- For apps-pages, keep one built-in app regression in-repo and treat large external app contexts as smoke/performance checks unless the test fixture provides their datasets.
