# AGENTS.md

This repository uses Codex CLI for local agent development. Follow these notes when working as an agent in this project.

## Codex CLI Quickstart

- Start app development after an initial creation via EXECUTE project clone using:
  - `codex -s danger-full-access -a never`
- Run the command from the repository root to give the agent full filesystem access with a non-interactive approval policy.
- Use only on your local, trusted machine. Do not run with these flags on shared or untrusted environments.

## Windows Path Tips

- When setting `APPS_REPOSITORY` in `%USERPROFILE%\.agilab\.env`, prefer forward slashes to avoid escape issues:
  - `APPS_REPOSITORY=C:/Users/<you>/PycharmProjects/agilab-apps`
- Keep `AGILAB_APPS_REPOSITORY` in sync or set both keys.
- Ensure the apps pages directory exists under the apps repo: `src/agilab/apps-pages`.

## Conventions

- Keep documentation (e.g., runbooks) and scripts in sync with how agents are expected to launch and validate flows.
- Prefer concise, actionable updates and avoid adding unrelated scope in a single change.
