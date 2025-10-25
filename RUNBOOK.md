# AGILab Agent Runbook

Use this runbook to align Codex CLI and human operators on consistent launch and validation steps.

## General practices

- Codex CLI startup (after EXECUTE project clone): run from repo root
  - `codex -s danger-full-access -a never`
  - Grants full filesystem access with non-interactive approvals. Use only on trusted local machines.

- Windows: set `APPS_REPOSITORY` using forward slashes in `%USERPROFILE%\.agilab\.env` to avoid path parsing issues
  - Example: `APPS_REPOSITORY=C:/Users/<you>/PycharmProjects/thales_agilab`
  - Optionally set `AGILAB_APPS_REPOSITORY` to the same value for legacy callers.
  - Ensure the apps repo contains `src/agilab/apps-pages` (copy from this repo if missing).

Keep this file current alongside changes to run configurations, environment variables, or Streamlit flows.
