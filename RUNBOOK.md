# AGILab Agent Runbook

Use this runbook to align Codex CLI and human operators on consistent launch and validation steps.

## General practices

- Codex CLI startup (after EXECUTE project clone): run from repo root
  - `codex --full-access -a never -m codex-medium`
  - Grants full filesystem access with non-interactive approvals. Use only on trusted local machines.

- Windows: set `APPS_REPOSITORY` using forward slashes in `%USERPROFILE%\.agilab\.env` to avoid path parsing issues
  - Example: `APPS_REPOSITORY=C:/Users/<you>/PycharmProjects/agilab-apps`
  - Optionally set `AGILAB_APPS_REPOSITORY` to the same value for legacy callers.
  - Ensure the apps repo contains `src/agilab/apps-pages` (copy from this repo if missing).
- Fast reinstall: repeat runs auto-detect existing installs and prompt to enable fast mode
  (skips system deps, locale, offline extras). Use `./install.sh --fast [--python-version 3.13] ...`
  or `.\install.ps1 -Fast [-PythonVersion 3.13] ...` for unattended speedups, and pass
  `--no-fast` / `-NoFast` or set `AGILAB_AUTO_FAST=0` to force the full flow. Always run a full
  install before packaging or sharing artifacts.

Keep this file current alongside changes to run configurations, environment variables, or Streamlit flows.
