# Apps

This directory contains first-party apps shipped with AGILab.

## Built-in apps

Built-in apps live under `src/agilab/apps/builtin/` and follow the `<name>_project` convention.
Each app usually contains:

- an app manager (`*_project`)
- a worker package under `src/<name>_worker/`
- optional `test/` scripts

## External apps (optional)

AGILab can also load apps from an external apps repository (for example, a private repository in your organisation).

- Configure `APPS_REPOSITORY` (or `AGILAB_APPS_REPOSITORY`) in `~/.local/share/agilab/.env`.
- Run `src/agilab/install_apps.sh` (macOS/Linux) or `src/agilab/install_apps.ps1` (Windows).
- The installer auto-discovers `*_project` directories under the external repo’s `apps/` folder and creates local links under `src/agilab/apps/`.
