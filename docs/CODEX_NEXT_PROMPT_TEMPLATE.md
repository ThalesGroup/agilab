# Codex Next Prompt Template

Use this template at the start of a new Codex debugging session.

It is designed for AGILAB and assumes you want Codex to reason from the bug
family, scope, validation depth, and push gate instead of reacting only to a raw
traceback.

## Short Version

```text
Fix this end to end.

Context:
- mode: <install | run | serve | page_render | test>
- suspected scope: <app_local | shared_core | docs_or_artifacts>
- app or module: <path or name>

Symptom:
- exception or failure: <exact message>
- first failing function/file: <symbol and path>
- command that reproduced it: <exact command>

Bug family guess:
- <missing_import_after_refactor | mixed_sync_async_runtime_contract | installer_solver_drift | worker_metadata_mismatch | service_state_persistence | streamlit_state_override | static_artifact_staleness | log_noise>

First checks:
- <check 1>
- <check 2>
- <check 3>

Avoid moves:
- <avoid 1>
- <avoid 2>

Required validation:
- <validation 1>
- <validation 2>

Push gate:
- run `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --files <touched-files>`
- run the matching `tools/workflow_parity.py --profile <profile>` if applicable

Execution policy:
- use the smallest correct fix
- add the narrowest regression test that proves it
- do not stop before validation
- push only after the gate is green
```

## Recommended AGILAB Prompt Pack

Paste this, then fill the bracketed values.

```text
Fix this AGILAB bug end to end.

Start with diagnosis, not speculative edits.

Bug context:
- mode: [install|run|serve|page_render|test]
- suspected scope: [app_local|shared_core|docs_or_artifacts]
- failing app/module: [path]
- exact repro command: [command]

Symptom:
- exception/failure: [exact text]
- first failing file/function: [path + symbol]
- environment notes: [machine, Python version, dependency/version differences, copied worker manifest path if relevant]

Bug family guess:
- [family]

Inspect first:
- [file or helper]
- [file or helper]
- [file or helper]

Avoid:
- [wrong move]
- [wrong move]

Required validation:
- [targeted test or py_compile]
- [workflow parity or install repro]

Push gate:
- run `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --files [files]`
- if relevant, run:
  - `uv --preview-features extra-build-dependencies run python tools/install_contract_check.py --app-path [app] --worker-copy [copied-worker]`
  - `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile [agi-gui|docs|badges|skills|installer]`

Execution policy:
- use the smallest correct fix
- add or update the narrowest regression that proves the fix
- do not broaden the patch beyond the failing contract unless the evidence requires it
- do not push until the validation above is green
```

## Family-Specific Fill-Ins

### Missing Import After Refactor

Use:

```text
Bug family guess:
- missing_import_after_refactor

Inspect first:
- imports in the failing module
- references to extracted support modules
- neighboring thin wrappers or re-export layers

Avoid:
- do not patch downstream callers first
- do not widen the fix beyond the traceback path

Required validation:
- py_compile on touched modules
- targeted pytest on the failing entrypoint
```

### Mixed Sync/Async Runtime Contract

Use:

```text
Bug family guess:
- mixed_sync_async_runtime_contract

Inspect first:
- the failing client call wrapper
- existing helpers that treat return values as maybe-awaitable
- tests around sync vs awaitable variants

Avoid:
- do not assume the client API is always awaitable
- do not hide the bug with broad exception handling

Required validation:
- targeted runtime tests
- one regression each for sync and awaitable paths
```

### Installer Solver Drift

Use:

```text
Bug family guess:
- installer_solver_drift

Inspect first:
- source manager pyproject.toml
- source worker pyproject.toml
- copied worker ~/wenv/.../pyproject.toml

Avoid:
- do not patch app dependencies before comparing all manifests
- do not assume plain uv sync proves AGILAB installer correctness

Required validation:
- tools/install_contract_check.py
- uv sync --project <app>
- uv run python src/agilab/apps/install.py <app> --verbose 1
```

### Streamlit State Override

Use:

```text
Bug family guess:
- streamlit_state_override

Inspect first:
- app_args_form.py
- persisted settings loader
- session_state initialization and rerun flow

Avoid:
- do not recompute a stored value unless it is actually missing
- do not validate only helper functions when the bug is UI-state behavior

Required validation:
- page/AppTest regression
- persisted-settings round-trip if relevant
```

### Static Artifact Staleness

Use:

```text
Bug family guess:
- static_artifact_staleness

Inspect first:
- artifact generator
- workflow definition that produces the artifact
- committed generated output

Avoid:
- do not trust the committed artifact as the current truth
- do not refresh output without the matching local input data

Required validation:
- targeted generator test
- workflow_parity profile matching the artifact type
```

## Better Input Package For Cross-Machine Failures

When the failure comes from another PC, include this in the prompt:

- exact traceback
- exact command or generated `AGI_*.py` script
- Python version
- relevant dependency version if known
- copied worker `pyproject.toml` if install-related
- whether the failing API returned a sync object or awaitable on that machine

This improves first-pass diagnosis more than pasting only the exception text.

## Recommended Closing Line

Use this at the end of your prompt when you want the full Codex workflow:

```text
Implement the smallest correct fix, add the narrowest regression test, run the required validation and push only when the gate is green.
```
