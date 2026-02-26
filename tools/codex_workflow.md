# Codex Workflow for AGILAB

## Purpose

Use a fixed Codex workflow so every agent session is traceable and reversible:

- one path for review (`review`)
- one path for implementation (`exec`)
- one path for applying generated patches (`apply`)

## Standard commands

```bash
# Review current working tree before making bigger edits
./tools/codex_workflow.sh review

# Implement a scoped change from a short prompt
./tools/codex_workflow.sh exec "Refactor only ... keeping behavior unchanged"

# Apply the latest diff for an existing task id
./tools/codex_workflow.sh apply <task-id>
```

## Defaults enforced by the wrapper

- run from repository root (`-C <repo_root>`)
- sandbox mode `workspace-write`
- approval policy `on-request`
- logs saved to `log/codex/<mode>-YYYYmmdd-HHMMSS.log`
- optional environment overrides:
  - `CODEX_CLI_MODEL`
  - `CODEX_CLI_PROFILE`

## Recommended sequence

1. `review` current changes.
2. Run a short `exec` command for the same objective.
3. Re-run `review` and capture test results before considering the session done.

## Safety rules

- Keep prompts minimal and scoped.
- Never expose secrets in prompts or logs.
- Keep `--dangerously-bypass-approvals-and-sandbox` as explicit exception, never default.
