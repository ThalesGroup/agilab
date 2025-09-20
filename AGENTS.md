# Repository Guidelines

## Project Structure & Module Organization

This repository is organized to separate core libraries (`agilab`), application components (`agi-*`), and user-facing apps/views. Follow these conventions:

- **`agilab/`** — Core Python packages (shared utilities, base classes, orchestration, data, tests)
- **`agi-*/`** — Components or plugins extending the core (manager/worker patterns, installers, workflows)
- **`apps/`** — Application entry points or services (CLI, Streamlit servers, API endpoints)
- **`pages_with_venv/`** — End-user interfaces (Streamlit, dashboards, notebooks)
- **`scripts/`** — One-off scripts or developer tools
- **`tests/`** — Unit and integration tests

Each component folder should contain a clear README or `__init__.py` docstring describing responsibilities, configuration, and run commands.

---

## Build, Test, and Development Commands

Prefer **`uv`** (or the project-standard virtual env) to ensure consistent dependency resolution and fast installs.

### Environment

- Python version: **3.11+** (check with `python -V`)
- Recommended: **uv** and a local virtual environment
  ```bash
  uv venv
  source .venv/bin/activate
  uv --preview-features extra-build-dependencies pip install -e .
  ```

- Alternative: **pyenv** or **conda** (ensure consistent interpreter in IDE and run configs)

### Private Apps & Pages

- The path to your private apps and pages is set during bootstrap via the top-level `install.sh` script using the `--private-apps` option, for example:
  - `./install.sh --private-apps /path/to/your/private-repo`
- The repository provided via `--private-apps` is considered the canonical private source and is also used when generating documentation (generate-docs) for private content.
  - To generate-docs from your private repository, first install the Sphinx extra in that repo:
    - `cd /path/to/private-repo && uv sync --dev --extra sphinx`
    - Then run the docs generator script from that same private repo:
      - `uv run <private-apps>/docs/gen-docs.py`
- For this project the canonical private apps repo lives at `~/PycharmProjects/thales_agilab`; obtain approval before accessing it and reference that path when configuring `--private-apps` locally.

### Docs Generation

- Run from the private repo configured via `--private-apps`.
- Prerequisite: `uv sync --dev --extra sphinx` (run in that private repo).
- Generate docs: `uv run <private-apps>/docs/gen-docs.py`
- Output: verify `docs/_build/html/index.html` and publish as needed.

### Install (editable)

```bash
uv --preview-features extra-build-dependencies pip install -e .
```

### Format & Lint

```bash
uv run ruff format .
uv run ruff check .
uv run mypy .
```

### Tests

- Unit tests:
  ```bash
  uv run pytest -q
  ```
- Integration tests (if applicable):
  ```bash
  uv run pytest -q tests/integration
  ```

### Running Apps

- Streamlit
  ```bash
  uv run streamlit run apps/app.py
  ```
- CLI tools
  ```bash
  uv run python scripts/tool.py --help
  ```

---

## PyCharm Run Configurations

JetBrains configurations are the **source of truth** for reproducible runs. They live in:

```
.idea/runConfigurations/*.xml
```

Common XML options:

- `SCRIPT_NAME` / script path
- `WORKING_DIRECTORY`
- `PARAMETERS`
- `<envs>` / `<env name="..." value="..."/>`
- Interpreter/SDK settings (e.g., `SDK_HOME`, `SDK_NAME`)

**Guidelines:**

- Name configs consistently: `component_action_mode`, e.g., `agilab_show_dependencies_dev`, `agilab_test_manager`, `agi-foo_distribute_local`.
- Group related configs in `folders.xml` to keep the UI tidy.
- Keep XMLs versioned (git) and aligned with docs—these files drive the run matrix below.

---

## How to work on this repository

This section is a hands-on guide for contributors. It turns the JetBrains **Run Configurations** in `.idea/runConfigurations/*.xml` into a runnable “cheat-sheet” and a progressive test plan.

> **Source of truth**: the XML launchers in `.idea/runConfigurations/` — keep those updated and re-generate this matrix when they change. See the “PyCharm Run Configurations” section above for naming and structure rules.  
> Also see “Project Structure & Module Organization” and “Build, Test, and Development Commands”.

### 1) Run matrix (auto-derived from `.idea/runConfigurations/*.xml`)

The table below is generated from the XML fields (`SCRIPT_NAME`, `PARAMETERS`, `WORKING_DIRECTORY`, `<envs/>`, interpreter/SDK). We show a copy‑pasteable command; if a working directory is required, it’s prefixed with `cd`.

| Group | Config name | Entry | Args | Workdir | Env | How to run | Interpreter |
|---|---|---|---|---|---|---|---|
| agilab | agilab run (dev) | streamlit | run $ProjectFileDir$/src/agilab/AGILAB.py -- --install-type 1 --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/AGILAB.py -- --install-type 1 --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps | uv (agilab) |
| agilab | agilab run (enduser) | streamlit | run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" --install 0 | $ProjectFileDir$/../agi-space | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/../agi-space && uv run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" --install 0 | uv (agi-space) |
| agilab | app install | $ProjectFileDir$/src/agilab/snippets/AGI.install-$Prompt:Enter app manager name:flight$.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.install-$Prompt:Enter app manager name:flight$.py | uv (agi-cluster) |
| agilab | app-script gen | $ProjectFileDir$/pycharm/gen-app-script.py | $Prompt:Enter app manager name:flight$ |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/pycharm/gen-app-script.py $Prompt:Enter app manager name:flight$ |  |
| agilab | install-agilab-dev | $PROJECT_DIR$/setup-pycharm.sh |  |  |  | uv run python $PROJECT_DIR$/setup-pycharm.sh |  |
| agilab | install-agilab-enduser | $PROJECT_DIR$/tools/install-enduser.sh |  |  |  | uv run python $PROJECT_DIR$/tools/install-enduser.sh |  |
| agilab | lab_run test | $USER_HOME$/agi-workspace/.venv/lib/python3.12/site-packages/agilab/lab_run.py | --openai-api-key "your-key" | $USER_HOME$/agi-workspace/ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/agi-workspace/ && uv run python $USER_HOME$/agi-workspace/.venv/lib/python3.12/site-packages/agilab/lab_run.py --openai-api-key "your-key" | uv (agilab) |
| agilab | pypi publish | $ProjectFileDir$/test/_pypi_publish.py | --repo testpypi --user agilab --clean --user agilab --regex ^\d+\.\d+\.\d+\.post\d+$ | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/test/_pypi_publish.py --repo testpypi --user agilab --clean --user agilab --regex ^\d+\.\d+\.\d+\.post\d+$ | uv (agilab) |
| agilab | run ssh cmd | $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |
| agilab | show depencencies | $ProjectFileDir$/tools/show_dependencies.py | --repo testpypi | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/show_dependencies.py --repo testpypi | uv (agilab) |
| agilab | test agi_distributor |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python  | uv (agi-cluster) |
| agilab | test agi_env |  |  | $ProjectFileDir$/src/agilab/core/agi-env/test |  | cd $ProjectFileDir$/src/agilab/core/agi-env/test && uv run python  | uv (agi-env) |
| agilab | test base_worker |  |  |  |  | uv run python  | uv (agi-cluster) |
| agilab | test dag_worker |  |  |  |  | uv run python  | uv (agi-cluster) |
| agilab | test pandas_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python  | uv (agi-cluster) |
| agilab | test polars_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python  | uv (agi-cluster) |
| agilab | test work_dispatcher |  |  |  |  | uv run python  | uv (agi-cluster) |
| agilab | zip-all gen | $ProjectFileDir$/../../tools/zip-all.py | --dir2zip src --zipfile src.zip | $ProjectFileDir$/../../tools | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/../../tools && uv run python $ProjectFileDir$/../../tools/zip-all.py --dir2zip src --zipfile src.zip |  |
| apps | app install (local) | $ProjectFileDir$/src/agilab/apps/install.py | $Prompt:selected app:~/agilab/src/agilab/apps/flight_project$ --install-type "1" --verbose 1 | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/apps/install.py $Prompt:selected app:~/agilab/src/agilab/apps/flight_project$ --install-type "1" --verbose 1 | uv (agi-cluster) |
| apps | app-test | $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app-test.py |  |  | PYTHONUNBUFFERED=1 | uv run python $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app-test.py | uv (agi-cluster) |
| apps | flight AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-flight.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-flight.py | uv (flight_project) |
| apps | flight AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-flight.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-flight.py | uv (flight_project) |
| apps | flight call worker | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_call_worker.py | uv (flight_project) |
| apps | flight test manager | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_manager.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_manager.py | uv (flight_project) |
| apps | flight test worker | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_worker.py | uv (flight_worker) |
| apps | flight_preinstall test | $PROJECT_DIR$/src/agilab/apps/flight_project/src/flight_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $PROJECT_DIR$/src/agilab/apps/flight_project/src/flight_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | uv (flight_project) |
| apps | flight_postinstall test | $USER_HOME$/wenv/flight_worker/src/flight_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/flight_project 1 $USER_HOME$/data/flight | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $USER_HOME$/wenv/flight_worker/src/flight_worker/post_install.py $ProjectFileDir$/src/agilab/apps/flight_project 1 $USER_HOME$/data/flight | uv (flight_worker) |
| apps | flight_trajectory AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-flight_trajectory.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-flight_trajectory.py | uv (flight_trajectory_project) |
| apps | flight_trajectory AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-flight_trajectory.py |  | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-flight_trajectory.py | uv (flight_trajectory_project) |
| apps | flight_trajectory call worker | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_call_worker.py | uv (flight_trajectory_project) |
| apps | flight_trajectory test manager | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_flight_trajectory_manager.py |  | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_flight_trajectory_manager.py | uv (flight_trajectory_project) |
| apps | flight_trajectory test worker | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_flight_trajectory_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_trajectory_project/test/_test_flight_trajectory_worker.py | uv (flight_trajectory_project) |
| apps | link_sim AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-link_sim.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-link_sim.py | uv (link_sim_project) |
| apps | link_sim AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-link_sim.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-link_sim.py | uv (link_sim_project) |
| apps | link_sim call worker | $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_call_worker.py | uv (link_sim_project) |
| apps | link_sim test manager | $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_manager.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_manager.py | uv (link_sim_project) |
| apps | link_sim test worker | $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_worker.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_worker.py | uv (link_sim_project) |
| apps | mycode AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-mycode.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-mycode.py | uv (mycode_project) |
| apps | mycode AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-mycode.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-mycode.py | uv (mycode_project) |
| apps | mycode call worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py | uv (mycode_project) |
| apps | mycode test manager | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py | uv (mycode_project) |
| apps | mycode test worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py | uv (mycode_project) |
| apps | sat_trajectory AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-sat_trajectory.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-sat_trajectory.py | uv (sat_trajectory_project) |
| apps | sat_trajectory AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-sat_trajectory.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-sat_trajectory.py | uv (sat_trajectory_project) |
| apps | sat_trajectory call worker | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_call_worker.py | uv (sat_trajectory_project) |
| apps | sat_trajectory test manager | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_manager.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_manager.py | uv (sat_trajectory_project) |
| apps | sat_trajectory test worker | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_worker.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_worker.py | uv (sat_trajectory_project) |
| apps | sb3_trainer AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-sb3_trainer.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-sb3_trainer.py | uv (sb3_trainer_project) |
| apps | sb3_trainer AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-sb3_trainer.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-sb3_trainer.py | uv (sb3_trainer_project) |
| apps | sb3_trainer call worker | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_call_worker.py | uv (sb3_trainer_project) |
| apps | sb3_trainer test manager | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_manager.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_manager.py | uv (sb3_trainer_project) |
| apps | sb3_trainer test worker | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_worker.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_worker.py | uv (sb3_trainer_project) |
| components | flight_egg gen | $PROJECT_DIR$/src/agilab/apps/flight_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $PROJECT_DIR$/src/agilab/apps/flight_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | uv (flight_project) |
| components | flight_lib gen | $USER_HOME$/wenv/flight_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | $USER_HOME$/wenv/flight_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/flight_worker && uv run python $USER_HOME$/wenv/flight_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | uv (flight_worker) |
| components | link_sim_egg gen | $PROJECT_DIR$/src/agilab/apps/link_sim_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/link_sim_worker | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $PROJECT_DIR$/src/agilab/apps/link_sim_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/link_sim_worker | uv (link_sim_project) |
| components | link_sim_lib gen | $USER_HOME$/wenv/link_sim_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/link_sim_worker | $USER_HOME$/wenv/link_sim_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/link_sim_worker && uv run python $USER_HOME$/wenv/link_sim_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/link_sim_worker | uv (link_sim_worker) |
| components | mycode_egg gen | $PROJECT_DIR$/src/agilab/apps/mycode_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $PROJECT_DIR$/src/agilab/apps/mycode_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | uv (mycode_project) |
| components | mycode_lib gen | $USER_HOME$/wenv/mycode_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | $USER_HOME$/wenv/mycode_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/mycode_worker && uv run python $USER_HOME$/wenv/mycode_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | uv (mycode_worker) |
| components | sat_trajectory_egg gen | $PROJECT_DIR$/src/agilab/apps/sat_trajectory_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sat_trajectory_worker | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $PROJECT_DIR$/src/agilab/apps/sat_trajectory_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sat_trajectory_worker | uv (sat_trajectory_project) |
| components | sat_trajectory_lib gen | $USER_HOME$/wenv/sat_trajectory_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sat_trajectory_worker | $USER_HOME$/wenv/sat_trajectory_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/sat_trajectory_worker && uv run python $USER_HOME$/wenv/sat_trajectory_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sat_trajectory_worker | uv (sat_trajectory_worker) |
| components | sb3_trainer_egg gen | $PROJECT_DIR$/src/agilab/apps/sb3_trainer_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sb3_trainer_worker | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $PROJECT_DIR$/src/agilab/apps/sb3_trainer_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sb3_trainer_worker | uv (sb3_trainer_project) |
| components | sb3_trainer_lib gen | $USER_HOME$/wenv/sb3_trainer_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sb3_trainer_worker | $USER_HOME$/wenv/sb3_trainer_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/sb3_trainer_worker && uv run python $USER_HOME$/wenv/sb3_trainer_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sb3_trainer_worker | uv (sb3_trainer_worker) |
| views | view_autoencoder-latenspace | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_autoencoder-latenspace/src/autoencoder_latentspace/view_autoencoder_latenspace.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_autoencoder-latenspace/src/autoencoder_latentspace/view_autoencoder_latenspace.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (autoencoder-latentspace) |
| views | view_barycentric | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_barycentric/src/view_barycentric/view_barycentric.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1 | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_barycentric/src/view_barycentric/view_barycentric.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (barycentric-graph) |
| views | view_maps | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps/src/view_maps/view_maps.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps/src/view_maps/view_maps.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (maps) |
| views | view_maps-3D | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps-3d/src/view_maps_3d/view_maps_3d.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps-3d/src/view_maps_3d/view_maps_3d.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (maps-3d) |
| views | view_maps-network | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps-network/src/view_maps_network/view_maps_network.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps-network/src/view_maps_network/view_maps_network.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (maps-network-graph) |
| apps | link_sim AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-link_sim.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-link_sim.py | uv (link_sim_project) |
| apps | link_sim AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-link_sim.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-link_sim.py | uv (link_sim_project) |
| apps | link_sim call worker | $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_call_worker.py | uv (link_sim_project) |
| apps | link_sim test manager | $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_manager.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_manager.py | uv (link_sim_project) |
| apps | link_sim test worker | $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_worker.py |  | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $ProjectFileDir$/src/agilab/apps/link_sim_project/test/_test_link_sim_worker.py | uv (link_sim_project) |
| apps | mycode AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-mycode.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-mycode.py | uv (mycode_project) |
| apps | mycode AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-mycode.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-mycode.py | uv (mycode_project) |
| apps | mycode call worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py | uv (mycode_project) |
| apps | mycode test manager | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py | uv (mycode_project) |
| apps | mycode test worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py | uv (mycode_project) |
| apps | sat_trajectory AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-sat_trajectory.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-sat_trajectory.py | uv (sat_trajectory_project) |
| apps | sat_trajectory AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-sat_trajectory.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-sat_trajectory.py | uv (sat_trajectory_project) |
| apps | sat_trajectory call worker | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_call_worker.py | uv (sat_trajectory_project) |
| apps | sat_trajectory test manager | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_manager.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_manager.py | uv (sat_trajectory_project) |
| apps | sat_trajectory test worker | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_worker.py |  | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $ProjectFileDir$/src/agilab/apps/sat_trajectory_project/test/_test_sat_trajectory_worker.py | uv (sat_trajectory_project) |
| apps | sb3_trainer AGI.run | $ProjectFileDir$/src/agilab/snippets/AGI.run-sb3_trainer.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.run-sb3_trainer.py | uv (sb3_trainer_project) |
| apps | sb3_trainer AGI.get_distrib | $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-sb3_trainer.py |  | $ProjectFileDir$/src/agilab/snippets | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/snippets && uv run python $ProjectFileDir$/src/agilab/snippets/AGI.get_distrib-sb3_trainer.py | uv (sb3_trainer_project) |
| apps | sb3_trainer call worker | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_call_worker.py | uv (sb3_trainer_project) |
| apps | sb3_trainer test manager | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_manager.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_manager.py | uv (sb3_trainer_project) |
| apps | sb3_trainer test worker | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_worker.py |  | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $ProjectFileDir$/src/agilab/apps/sb3_trainer_project/test/_test_sb3_trainer_worker.py | uv (sb3_trainer_project) |
| components | flight_egg gen | $PROJECT_DIR$/src/agilab/apps/flight_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $PROJECT_DIR$/src/agilab/apps/flight_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | uv (flight_project) |
| components | flight_lib gen | $USER_HOME$/wenv/flight_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | $USER_HOME$/wenv/flight_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/flight_worker && uv run python $USER_HOME$/wenv/flight_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | uv (flight_worker) |
| components | link_sim_egg gen | $PROJECT_DIR$/src/agilab/apps/link_sim_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/link_sim_worker | $ProjectFileDir$/src/agilab/apps/link_sim_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/link_sim_project && uv run python $PROJECT_DIR$/src/agilab/apps/link_sim_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/link_sim_worker | uv (link_sim_project) |
| components | link_sim_lib gen | $USER_HOME$/wenv/link_sim_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/link_sim_worker | $USER_HOME$/wenv/link_sim_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/link_sim_worker && uv run python $USER_HOME$/wenv/link_sim_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/link_sim_worker | uv (link_sim_worker) |
| components | mycode_egg gen | $PROJECT_DIR$/src/agilab/apps/mycode_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $PROJECT_DIR$/src/agilab/apps/mycode_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | uv (mycode_project) |
| components | mycode_lib gen | $USER_HOME$/wenv/mycode_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | $USER_HOME$/wenv/mycode_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/mycode_worker && uv run python $USER_HOME$/wenv/mycode_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | uv (mycode_worker) |
| components | sat_trajectory_egg gen | $PROJECT_DIR$/src/agilab/apps/sat_trajectory_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sat_trajectory_worker | $ProjectFileDir$/src/agilab/apps/sat_trajectory_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sat_trajectory_project && uv run python $PROJECT_DIR$/src/agilab/apps/sat_trajectory_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sat_trajectory_worker | uv (sat_trajectory_project) |
| components | sat_trajectory_lib gen | $USER_HOME$/wenv/sat_trajectory_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sat_trajectory_worker | $USER_HOME$/wenv/sat_trajectory_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/sat_trajectory_worker && uv run python $USER_HOME$/wenv/sat_trajectory_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sat_trajectory_worker | uv (sat_trajectory_worker) |
| components | sb3_trainer_egg gen | $PROJECT_DIR$/src/agilab/apps/sb3_trainer_project/build.py | bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sb3_trainer_worker | $ProjectFileDir$/src/agilab/apps/sb3_trainer_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/sb3_trainer_project && uv run python $PROJECT_DIR$/src/agilab/apps/sb3_trainer_project/build.py bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/sb3_trainer_worker | uv (sb3_trainer_project) |
| components | sb3_trainer_lib gen | $USER_HOME$/wenv/sb3_trainer_worker/build.py | build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sb3_trainer_worker | $USER_HOME$/wenv/sb3_trainer_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/sb3_trainer_worker && uv run python $USER_HOME$/wenv/sb3_trainer_worker/build.py build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/sb3_trainer_worker | uv (sb3_trainer_worker) |
| views | view_autoencoder-latenspace | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_autoencoder-latenspace/src/view_autoencoder_latentspace/view_autoencoder_latenspace.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |  | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_autoencoder-latenspace/src/view_autoencoder_latentspace/view_autoencoder_latenspace.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |
| views | view_barycentric | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_barycentric/src/barycentric_graph/view_barycentric.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |  | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_barycentric/src/barycentric_graph/view_barycentric.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |
| views | view_maps | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps/src/maps/view_maps.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |  | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps/src/maps/view_maps.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |
| views | view_maps-3D | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps-3d/src/maps_3d/view_maps_3d.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |  | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps-3d/src/maps_3d/view_maps_3d.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |
| views | view_maps-network | streamlit | run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps-network/src/maps_network_graph/view_maps_network.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |  | uv run streamlit run $ProjectFileDir$/src/agilab/pages_with_venv/view_maps-network/src/maps_network_graph/view_maps_network.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |

Note: Table shows the most-used configs. For the full set, re-run the refresh script below.

**How to refresh this matrix**
```bash
# Run from repo root. Prints: file|name|folder|script|workdir|params|envs|sdk
for f in .idea/runConfigurations/*.xml; do
  python3 - <<'PY' "$f"
import sys, xml.etree.ElementTree as ET
p=sys.argv[1]
t=ET.parse(p).getroot()
c=t.find('.//configuration')
name=c.get('name',''); folder=c.get('folderName','')
opt={o.get('name'):o.get('value') for o in c.findall('.//option')}
envs=';'.join(f"{e.get('name')}={e.get('value')}" for e in c.findall('.//env'))
script=opt.get('SCRIPT_NAME') or opt.get('PARAMETERS_SCRIPT') or opt.get('SCRIPT_PATH') or ''
workdir=opt.get('WORKING_DIRECTORY',''); params=opt.get('PARAMETERS','')
sdk=opt.get('SDK_NAME') or opt.get('SDK_HOME') or ''
print('|'.join([p.split('/')[-1], name, folder, script, workdir, params, envs, sdk]))
PY
done
```
Then regenerate this table (or ask Codex to do it) grouping by:
- apps: paths under `src/agilab/apps/*` or `folderName` ending with `_project`
- components: worker packaging under `$USER_HOME$/wenv/*`
- views: `agi-views` or any `SCRIPT_NAME=streamlit` view apps
- agilab: root tools, installers, and meta scripts

### 2) Progressive test plan

Tier A — Quick checks (fast sanity)
- UI smoke: `cd $ProjectFileDir$ && uv run streamlit run src/agilab/AGILAB.py -- --install-type 1 --openai-api-key "your-key" --apps-dir src/agilab/apps` (agilab run dev)
- Dependencies: `cd $ProjectFileDir$ && uv run python tools/show_dependencies.py --repo testpypi`
- App skeleton: `uv run python src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app-test.py`

Tier B — Component/app flows
- Flight: run → test manager/worker → distribute → call → pre/postinstall
  - `cd src/agilab/apps/flight_project && uv run python ../../snippets/AGI.run-flight.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_flight_manager.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_flight_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib-flight.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_call_worker.py`
  - `cd src/agilab/apps/flight_project && uv run python src/flight_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py`
  - `cd src/agilab/apps/flight_project && uv run python $USER_HOME$/wenv/flight_worker/src/flight_worker/post_install.py src/agilab/apps/flight_project 1 $USER_HOME$/data/flight`
- Repeat for: `link_sim_project`, `mycode_project`, `sat_trajectory_project`, `sb3_trainer_project` (same patterns with their names).

Tier C — Views and end-user
- Views: launch Streamlit views bound to an active app
  - `uv run streamlit run src/agilab/pages_with_venv/view_maps/src/view_maps/view_maps.py -- --install-type 1 --active-app src/agilab/apps/flight_project`
  - `uv run streamlit run src/agilab/pages_with_venv/view_barycentric/src/view_barycentric/view_barycentric.py -- --install-type 1 --active-app src/agilab/apps/flight_project`
- End-user mode: `cd ../agi-space && uv run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" --install 0`

For each tier, capture: command, expected output, and pitfalls (CWD, env vars, interpreter).

### 3) Troubleshooting & environment

- **Interpreter/SDK**: préférer l’environnement du projet (ex.: `uv`). À défaut, utiliser le chemin complet de l’interpréteur ou `uv run`.  
- **Env vars**: à partir de `<envs/>` dans les XML, produire un `.env.example` (clés, valeurs fictives).  
- **Common errors**:  
  - `ModuleNotFoundError`: vérifier CWD = `WORKING_DIRECTORY` et `PYTHONPATH`.  
  - Logs Streamlit qui ne flushent pas: `PYTHONUNBUFFERED=1`.  
  - Lancements lents: `UV_NO_SYNC=1` en dev.

**`.env.example` (template)**
```dotenv
OPENAI_API_KEY=__set_me__
AGI_CLUSTER_URL=__set_me__
```

### 4) Automate with Codex (safe write with approvals)

```bash
codex --model gpt-5-codex --approvals ask "
Update AGENTS.md: refresh the 'Run matrix' and 'Progressive test plan' under 'How to work on this repository'
by parsing .idea/runConfigurations/*.xml:
- Extract: name, SCRIPT_NAME, PARAMETERS, WORKING_DIRECTORY, envs, interpreter
- Group rows by app/component/view heuristics (agilab/, agi-*/, apps/, pages_with_venv/)
- Render a markdown table with copy-pasteable commands (cd + python/uv run)
- Keep edits scoped to this section; show a unified diff before saving"
```

### 5) Keeping run configs in sync
- Quand tu crées/renommes des workflows, clone un XML existant et ajuste scripts, workdirs, interpreters; garde le grouping propre.
- Traite `.idea/runConfigurations/` comme la checklist canonique “comment repro X ?” et régénère la matrice dès que ça change.
- Important: when renaming or relocating scripts/entries, update both:
  - The concrete launchers in `.idea/runConfigurations/*.xml` (names, `SCRIPT_NAME`, `WORKING_DIRECTORY`, envs)
  - The PyCharm templates and helpers under `pycharm/` and related generators:
    - `pycharm/_template_app_*.xml`, `pycharm/setup-pycharm.py`, `pycharm/gen-app-script.py`
    - And, if used, `src/agilab/core/gen-app-script.py`
  - After changes, re-run the “Run matrix” refresh to keep docs aligned.

#### Regenerate Run Configs (step-by-step)

1) Update templates (if needed)
   - Edit `pycharm/_template_app_*.xml` to reflect new script names/paths (e.g., `AGI.get_distrib-*`).

2) Sync PyCharm modules + registered SDKs
   - `uv run python pycharm/setup-pycharm.py`

3) Re-generate per‑app launchers (one per app)
   - Examples:
     - `uv run python pycharm/gen-app-script.py flight`
     - `uv run python pycharm/gen-app-script.py link_sim`
     - `uv run python pycharm/gen-app-script.py mycode`
     - `uv run python pycharm/gen-app-script.py sat_trajectory`
     - `uv run python pycharm/gen-app-script.py sb3_trainer`

4) Verify
   - Inspect `.idea/runConfigurations/*.xml` for updated `SCRIPT_NAME`, names, and `folderName` grouping.

5) Refresh the Run Matrix in this doc
   - Use the snippet under “How to refresh this matrix” to re-print rows and paste in place.

---

## Coding Standards

- Follow **PEP8** with project-specific exceptions documented in `pyproject.toml`.
- Type hints are **required** for public functions; enforce with `mypy`.
- Prefer composition over inheritance; interfaces live in `agilab/core/`.
- Break cycles; respect clear layering (core → components → apps → pages).

---

## Contribution Workflow

1. **Create a feature branch**: `feat/<area>-<short-desc>`
2. **Small, reviewable PRs** — keep changes focused and add context in the description.
3. **Tests** — write/adjust unit tests; add an integration path when touching orchestration.
4. **Docs** — update `AGENTS.md` and component READMEs when behavior changes.
5. **CI** — ensure lint, type-check, and tests pass before requesting review.

---

## Release & Deployment (if applicable)

- Tag version in `pyproject.toml`
- Changelog entries required for user-facing changes
- Automated packaging with `uv build` and release notes in GitHub

---

## Security & Secrets

- Never commit secrets; use `.env` or your secret manager.
- Use restricted API keys for local dev.
- Validate inputs and sanitize file paths.
- Log only non-sensitive metadata.

---

## FAQ

**Q: My run configuration fails with `ModuleNotFoundError`.**  
A: Ensure your working directory matches the config’s `WORKING_DIRECTORY` and your interpreter matches the project’s SDK.

**Q: Streamlit app doesn’t hot-reload.**  
A: Start it with `uv run streamlit run ...` and check `PYTHONUNBUFFERED`.

**Q: Where do I add a new component?**  
A: Create `agi-<name>/` under the repo root with its own README and tests; wire it into the run matrix via a new JetBrains XML.

---

## Appendix: Useful Commands

```bash
# Create & activate venv
uv venv && source .venv/bin/activate

# Install editable
uv --preview-features extra-build-dependencies pip install -e .

# Run Streamlit
uv run streamlit run src/agilab/AGILAB.py

# Run a component script
uv run python agilab/tools/show_dependencies.py

# Lint & type-check
uv run ruff check .
uv run mypy .

# Tests
uv run pytest -q
```
