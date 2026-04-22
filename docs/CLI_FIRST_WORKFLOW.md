# CLI-First AGILAB Developer Workflow

This guide is for developers who want to work on AGILAB or on an AGILAB
project without relying on an IDE.

It does not pretend CLI-only work is identical to an IDE workflow. The point is
to make CLI-first development safe, repeatable, and fast enough for real AGILAB
framework work and app/project work.

## What You Lose Without An IDE

The main losses are:

- fast structural navigation across framework, apps, pages, and tests
- refactor assistance across large multi-package surfaces
- interactive debugging for async, Dask, Streamlit, subprocess, and worker flows
- local history and point-in-time rollback outside Git
- live state inspection while a page or long action is running

For AGILAB specifically, the biggest gap is not editing. It is debugging and
state inspection.

## CLI-First Compensation Stack

Use these tools together:

- [AGENTS.md](../AGENTS.md) for repo policy and standard commands
- [impact_validate.py](../tools/impact_validate.py) for diff triage and required validations
- [perf_smoke.py](../tools/perf_smoke.py) for startup-sensitive before/after comparisons
- [service_health_check.py](../tools/service_health_check.py) for service mode health gates
- [smoke_preinit.py](../tools/smoke_preinit.py) for minimal environment smoke checks
- [tools/run_configs](../tools/run_configs) for terminal-friendly mirrors of the bundled run configurations
- [agent_workflows.md](../tools/agent_workflows.md) for the repo-supported agent entry points
- [codex_workflow.md](../tools/codex_workflow.md) if you use Codex CLI as part of the loop
- [aider_workflow.md](../tools/aider_workflow.md) if you use Aider with local Ollama models
- [opencode_workflow.md](../tools/opencode_workflow.md) if you use OpenCode with local Ollama models

## Core Rule

For non-trivial changes, always start with:

```bash
uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged
```

Use the output to decide:

- whether the change is app-local or shared-core
- which targeted tests are required
- whether install repros are mandatory
- whether generated artifacts must be refreshed

## Framework Development Workflow

Use this when you are changing:

- `src/agilab`
- `src/agilab/core/agi-env`
- `src/agilab/core/agi-node`
- `src/agilab/core/agi-cluster`
- `src/agilab/core/agi-core`
- shared tooling under `tools/`

### 1. Triage the diff

```bash
uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged
```

If `shared-core` is reported, follow the approval and validation rules from
[AGENTS.md](../AGENTS.md).

### 2. Run the narrowest proof first

Examples:

```bash
uv --preview-features extra-build-dependencies run python -m py_compile path/to/file.py
uv --preview-features extra-build-dependencies run pytest -q test/test_orchestrate_execute.py
uv --preview-features extra-build-dependencies run pytest -q src/agilab/core/test/test_agi_distributor_runtime_distribution_support.py
```

Do not jump to the full repo test suite first.

### 3. Reproduce the real path, not just the helper

If the issue is:

- page behavior: use the relevant `AppTest` or page smoke test
- installer behavior: run both `uv sync --project <app>` and `uv run python src/agilab/apps/install.py <app> --verbose 1`
- run configuration behavior: execute the wrapper under [tools/run_configs](../tools/run_configs)
- service behavior: use [service_health_check.py](../tools/service_health_check.py)

### 4. Check performance when refactoring hot startup paths

```bash
uv --preview-features extra-build-dependencies run python tools/perf_smoke.py --scenario orchestrate-execute-import --repeats 5 --warmups 1
uv --preview-features extra-build-dependencies run python tools/perf_smoke.py --scenario runtime-distribution-import --repeats 5 --warmups 1
```

Use this before and after maintainability refactors that might affect import or
startup cost.

## AGILAB Project Development Workflow

Use this when developing inside an AGILAB app/project:

- manager code
- worker code
- `app_args_form.py`
- project settings
- app pages
- install helpers for one project

### 1. Start from the project path

Common places:

- `src/agilab/apps/builtin/<app>_project`
- `src/agilab/apps/<app>_project`
- external apps repository linked into AGILAB

### 2. Use the shell mirrors, not handwritten command variants

List wrappers:

```bash
find tools/run_configs -type f -name "*.sh" | sort
```

Examples:

```bash
bash tools/run_configs/agilab/agilab-run-dev.sh
bash tools/run_configs/apps/builtin-flight-run.sh
```

These keep CLI and bundled run configurations aligned.

### 3. Validate both manager and worker sides

If an import or dependency fails, check both manifests:

- manager `pyproject.toml`
- worker `src/<app>_worker/pyproject.toml`

If an install fails, also inspect the copied worker manifest under:

```bash
~/wenv/<app>_worker/pyproject.toml
```

### 4. Use the real AGILAB install path

```bash
uv sync --project <app-project-path>
uv --preview-features extra-build-dependencies run python src/agilab/apps/install.py <app-project-path> --verbose 1
```

If the first succeeds but the second fails, treat it as an AGILAB install-path
problem first, not as an app-only dependency problem.

### 5. Use the page-appropriate test surface

- backend helper bug: test the helper directly
- widget/session-state bug: use the relevant `AppTest`
- packaging/install bug: use installer repro commands
- runtime path bug: use the worker/run wrapper or generated `AGI_*.py` snippet

## Shell-Only Safe Practices

- Commit more often than you would with PyCharm local history.
- Use `git diff` and `git add -p` aggressively.
- Keep one terminal for tests and one for long-running pages or cluster logs.
- Prefer generated wrappers and repo tools over handwritten ad hoc commands.
- Keep a small scratch note with the exact repro command while debugging.

## Recommended Daily Loop

```bash
# 1. Check what changed
git status --short

# 2. Triage impact
uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged

# 3. Run the narrowest proof
uv --preview-features extra-build-dependencies run pytest -q <targeted tests>

# 4. Reproduce the real path if needed
bash tools/run_configs/<group>/<wrapper>.sh

# 5. Benchmark startup-sensitive changes if relevant
uv --preview-features extra-build-dependencies run python tools/perf_smoke.py --scenario <scenario> --repeats 5 --warmups 1
```

## When CLI-Only Is Still Not Enough

CLI-first is workable, but there are cases where an IDE still gives a real
advantage:

- stepping through async or Dask-heavy control flow
- inspecting complex Streamlit/session state while the page is live
- large multi-file rename/refactor waves
- recovering content that was never committed

If you stay CLI-first anyway, compensate by:

- making smaller commits
- keeping repro commands written down
- using more focused regression tests
- using `impact_validate` before push
- using `perf_smoke` on startup-sensitive refactors

## Related References

- [AGENTS.md](../AGENTS.md)
- [agent_workflows.md](../tools/agent_workflows.md)
- [codex_workflow.md](../tools/codex_workflow.md)
- [aider_workflow.md](../tools/aider_workflow.md)
- [opencode_workflow.md](../tools/opencode_workflow.md)
- [quick-start.rst](source/quick-start.rst)
- [troubleshooting.rst](source/troubleshooting.rst)
