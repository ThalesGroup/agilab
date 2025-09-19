# Repository Guidelines

## Project Structure & Module Organization
The runnable package lives under `src/agilab`, with the CLI entry point in `src/agilab/lab_run.py`. Feature surfaces are
structured by domain inside `src/agilab/apps/`, `src/agilab/pages/`, and `src/agilab/views/`; each submodule keeps its
targeted fixtures and assets. Shared runtime layers sit in `src/agilab/core` (cluster, env, node, shared utilities)
with deeper integration tests in `src/agilab/core/test/`, while repository-level regression checks land in the top-level
`test/` directory. Configuration files belong in `config/`, documentation sources in `docs/`, and shared static assets in
`src/agilab/resources/`. Optional private extensions can be symlinked beside the public modules (for example
`src/agilab/apps/<name>/private/`); ensure the open-source tree stays runnable without them.

## Build, Test, and Development Commands
Use the installer to provision toolchains and optional private apps:
```bash
./install.sh --openai-api-key "<token>" \
  --cluster-ssh-credentials "user:password" \
  --private-apps ~/PycharmProjects/thales_agilab
```
The flag combinations above mirror `install_20250918_190233.log`; drop `--private-apps` if you do not maintain a
symlinked private checkout. The installer invokes `uv sync --preview-features extra-build-dependencies -p 3.13.7 --dev`
inside each core package—reuse that command within `src/agilab/core/<component>` when iterating locally. Launch the lab
from `src/agilab` with `uv run agilab --openai-api-key <token>`. Produce distributable artifacts using `uv build`; when
CI is unavailable, fall back to `python -m build` in the repository root. Editable installs pull the bundled `cmake`
wheel so `llvmlite`/`numba` native extensions compile without system CMake.

## Coding Style & Naming Conventions
Adopt four-space indentation, an 88-character line width, and Google-style docstrings; format with `uv run black src
test`. Modules, functions, and variables stay in `snake_case`, classes in `PascalCase`, and constants in `UPPER_SNAKE`.
Keep JSON/TOML keys lowercase with hyphen or underscore separators so they align with existing configuration files.

## Testing Guidelines
Co-locate pytest modules with the code they verify, naming files `test_<feature>.py`. Mark async paths with
`@pytest.mark.asyncio`, prefer fixtures over ad-hoc setup, and keep distributed workflows covered by tests in
`src/agilab/core/test/`. Run `uv run pytest` before every submission and confirm coverage still reports on `agilab`,
`agi_core`, `agi_env`, `agi_cluster`, and `agi_node`; review `coverage.xml` if numbers shift.

## Commit & Pull Request Guidelines
Keep commit messages short and imperative (for example, `fix(cli) guard missing key`) and limit each commit to one
change set. Every pull request links relevant issues, summarizes behavior changes, and attaches evidence of `uv run
pytest` plus the generated coverage badge. Include `uv run licensecheck` results and refresh `IP.md` whenever third-party
materials are introduced. Request review after CI passes and add screenshots or CLI transcripts for UI-facing updates.
