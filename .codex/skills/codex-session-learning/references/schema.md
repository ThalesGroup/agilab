# Session Case Schema

Use this reference when you need a concrete shape for a reusable bug-fix case or
prompt pack.

## Minimal case fields

```json
{
  "case_id": "install-missing-import-entrypoint-support",
  "bug_family": "missing_import_after_refactor",
  "context": {
    "mode": "install",
    "entry_command": "uv run python src/agilab/apps/install.py ...",
    "scope": "shared_core"
  },
  "symptom": {
    "exception_type": "NameError",
    "message": "name 'runtime_misc_support' is not defined",
    "first_failing_function": "_load_capacity_predictor"
  },
  "root_cause": "entrypoint_support called an extracted support module without importing it",
  "first_checks": [
    "inspect module imports",
    "compare extracted helper references with moved modules",
    "check direct call sites in the failing function"
  ],
  "avoid_moves": [
    "do not patch downstream callers first",
    "do not broaden the fix beyond the traceback without evidence"
  ],
  "fix_pattern": "restore the missing import and add a focused regression test",
  "validation": [
    "py_compile on the touched module",
    "targeted pytest for the failing entrypoint path"
  ],
  "outcome": {
    "first_pass_success": true,
    "followup_fix_needed": false
  },
  "reusable_rule": "after support-module extraction, audit imports before changing behavior"
}
```

## Prompt-pack fields

A prompt pack should stay smaller and more operational than a case record:

```json
{
  "bug_family": "missing_import_after_refactor",
  "scope": "shared_core",
  "first_checks": [
    "imports in failing module",
    "references to extracted support modules"
  ],
  "avoid_moves": [
    "no speculative behavior changes",
    "no broad cleanup outside proven failure path"
  ],
  "required_validation": [
    "py_compile",
    "targeted pytest"
  ]
}
```

## Recommended taxonomy axes

- `bug_family`
  - `missing_import_after_refactor`
  - `installer_solver_drift`
  - `streamlit_session_state`
  - `service_state_persistence`
  - `coverage_artifact_staleness`
  - `path_or_manifest_resolution`
- `scope`
  - `app_local`
  - `shared_core`
  - `docs_or_badges`
- `mode`
  - `install`
  - `run`
  - `serve`
  - `page_render`
  - `test`

## Prompt assembly guidance

Build prompts from:

1. condensed bug log
2. one or more matching case rules
3. the required validation list
4. explicit “do not” moves

Do not dump the full historical transcript into every prompt. Keep the prompt
focused on the next debugging decision.
