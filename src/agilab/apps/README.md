# Apps

This directory contains AGILAB app project sources. Keep the packaged base
install small: `mycode_project` is the only project bundled directly in the
`agi-apps` umbrella as a starter template. Public demos are distributed through
focused `agi-app-*` packages.

## Source app projects

Repository-maintained app sources live under `src/agilab/apps/builtin/` and
follow the `<name>_project` convention. The `builtin/` directory is a source
staging namespace for maintained apps, not the package contract for base
installs.

- an app manager (`*_project`)
- a worker package under `src/<name>_worker/`
- optional service/template payloads

Use `mycode_project` when you need the smallest app scaffold. Install
`agilab[examples]` or individual `agi-app-*` packages when you need complete
domain demos such as mission decision, flight telemetry, weather forecast, or
queue resilience.

## Templates

Starter templates live under `src/agilab/apps/templates/`:

- `dag_app_template`: explicit task-graph/distribution wiring.
- `pandas_app_template`: Pandas-style data pipeline starter.
- `polars_app_template`: Polars-style data pipeline starter.
- `fireducks_app_template`: FireDucks-accelerated Pandas-style starter.

Copy a template to a new `<name>_project` directory, rename the package and
`pyproject.toml` metadata, then replace the template worker hooks with the app
logic.

## External apps (optional)

AGILab can also load apps from an external apps repository (for example, a private repository in your organisation).

- Configure `APPS_REPOSITORY` in `~/.local/share/agilab/.env`.
- Run `src/agilab/install_apps.sh` (macOS/Linux) or `src/agilab/install_apps.ps1` (Windows).
- The installer auto-discovers `*_project` directories under the external repo’s `apps/` folder and creates local links under `src/agilab/apps/`.

When an external app already exists locally as a real directory, the installer
moves it aside as `<name>.previous.<timestamp>` and links the repository copy so
future updates come from the apps repository.
