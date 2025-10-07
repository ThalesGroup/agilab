# AGILab Run & Troubleshooting Checklist

Use this runbook to launch, validate, and troubleshoot AGILab flows from a single
place. The sections mirror the IDE run configurations so you can copy commands
directly into a shell or Streamlit page. After changing anything under
`.idea/runConfigurations`, regenerate the table below so everyone executes the
same instructions.

Note: AGILab workflows and this checklist assume PyCharm IDE. Most commands can be run manually, but the recommended path is via PyCharm run configurations.

> **Tip**
> Update this document whenever a run config, environment variable, or Streamlit
> control changes. CI, reviewers, and support rely on it for reproduction steps.
>
> **Model compatibility check**
> When reviewing or updating flows with GPT-5 Codex agents, confirm they do **not** rely on
> deprecated Streamlit APIs such as `st.experimental_rerun()`. Upgrade callers to the
> supported replacement (`st.rerun`) before merging.

> **No silent fallbacks**
> Avoid introducing automatic client/API fallbacks (e.g., silently switching between
> `chat.completions` and `responses`, or altering parameter names at runtime). Prefer
> detecting model capability up-front and failing fast with a clear, actionable error
> for the user. Hidden fallbacks make behavior hard to reproduce and can mask config
> or model‑selection mistakes.

> **Private apps auto-link**
> The installer now creates symlinks to the private app checkout on demand. Keep the
> private repository at the path recorded in `~/.local/share/agilab/.env` so missing
> workers are resolved automatically.

> **Runtime isolation reminder**
> When you launch flows inside `~/agi-space`, assume the upstream `~/agilab` checkout is
> absent. Agents and scripts must rely solely on the packaged assets inside the virtual
> environment; never reference repository-relative paths at runtime.

> **Shared build module**
> All packaging invocations go through `python -m agi_node.agi_dispatcher.build --app-path …`.
> References to per-app `build.py` helpers are obsolete.

> **Pre/Post install hooks**
> Worker `pre_install`/`post_install` logic lives in the shared
> `agi_node.agi_dispatcher.{pre_install,post_install}` modules. Packaging invokes
> them automatically via `python -m …`. If an app needs custom behavior, drop a
> small wrapper alongside the worker that imports and extends the shared module.

> **AgiEnv singleton + pre‑init**
> `AgiEnv` is a true singleton. Instance attributes are the source of truth; class
> attribute reads proxy to the singleton when it exists. Some helpers (`set_env_var`,
> `read_agilab_path`, `_build_env`, `log_info`) are pre‑init safe and avoid hard failures
> if called before the environment is bootstrapped. Do not rely on class attributes being
> populated before creating `AgiEnv()`.

> **App constructor kwargs**
> App constructors now ignore unknown kwargs when building their Pydantic `Args` models
> (templates + flight_project). This preserves strict validation while making constructors
> resilient to incidental extras. Prefer passing runtime verbosity to `AgiEnv(verbose=…)`
> or your logging config, not app `Args`.

<details>
<summary><strong>Launch matrix (auto-sorted from .idea/runConfigurations)</strong></summary>

| Group | Config name | Entry | Args | Workdir | Env | How to run | Interpreter |
|---|---|---|---|---|---|---|---|
| agilab | agilab run (dev) | streamlit | run $ProjectFileDir$/src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps | uv (agilab) |
| agilab | agilab run (enduser) | streamlit | run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" | $ProjectFileDir$/../agi-space | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/../agi-space && uv run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" | uv (agi-space) |
| agilab | app_script gen | $ProjectFileDir$/pycharm/gen_app_script.py | $Prompt:Enter app manager name:flight$ |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/pycharm/gen_app_script.py $Prompt:Enter app manager name:flight$ |  |
| agilab | install-dev |  |  |  |  | uv run python |  |
| agilab | install-enduser (local) |  |  |  |  | uv run python |  |
| agilab | install-enduser (test.pypi) |  |  |  |  | uv run python |  |
| agilab | lab_run test | $USER_HOME$/agi-workspace/.venv/lib/python3.12/site-packages/agilab/lab_run.py | --openai-api-key "your-key" | $USER_HOME$/agi-workspace/ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/agi-workspace/ && uv run python $USER_HOME$/agi-workspace/.venv/lib/python3.12/site-packages/agilab/lab_run.py --openai-api-key "your-key" | uv (agilab) |
| agilab | pypi publish | $ProjectFileDir$/tools/pypi_publish.py | --repo pypi --leave-most-recent --version $Prompt:version$ --verbose --cleanup-password $Prompt:Enter PyPI account password:$ | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1;PYPI_USERNAME=$Prompt:Enter PyPI username:$;PYPI_PASSWORD=$Prompt:Enter PyPI password:$ | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/pypi_publish.py --repo pypi --leave-most-recent --version $Prompt:version$ --verbose --cleanup-password $Prompt:Enter PyPI account password:$ | uv (agilab) |
| agilab | run ssh cmd | $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |
| agilab | show depencencies | $ProjectFileDir$/tools/show_dependencies.py | --repo testpypi | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/show_dependencies.py --repo testpypi | uv (agilab) |
| agilab | test agi_distributor |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test agi_env |  |  | $ProjectFileDir$/src/agilab/core/agi-env/test |  | cd $ProjectFileDir$/src/agilab/core/agi-env/test && uv run python | uv (agi-env) |
| agilab | test base_worker |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | test dag_worker |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | test pandas_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test polars_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test work_dispatcher |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | zip_all | $ProjectFileDir$/tools/zip_all.py | --dir2zip src --zipfile src.zip | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/zip_all.py --dir2zip src --zipfile src.zip |  |
| apps | app install (local) | $ProjectFileDir$/src/agilab/apps/install.py | $Prompt:selected app:~/agilab/src/agilab/apps/flight_project$ --install-type "1" --verbose 1 | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/apps/install.py $Prompt:selected app:~/agilab/src/agilab/apps/flight_project$ --install-type "1" --verbose 1 | uv (agi-cluster) |
| apps | app-test | $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py |  |  | PYTHONUNBUFFERED=1 | uv run python $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py | uv (agi-cluster) |
| apps | flight AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/flight/AGI_get_distrib_flight.py |  | $ProjectFileDir$/src/agilab/examples/flight | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/flight && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI_get_distrib_flight.py | uv (flight_project) |
| apps | flight AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/flight/AGI_get_distrib_flight.py |  | $ProjectFileDir$/src/agilab/examples/flight | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/flight && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI_get_distrib_flight.py | uv (flight_project) |
| apps | flight AGI_install | $ProjectFileDir$/src/agilab/examples/flight/AGI_install_flight.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI_install_flight.py | uv (agi-cluster) |
| apps | flight AGI_install | $ProjectFileDir$/src/agilab/examples/flight/AGI_install_flight.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI_install_flight.py | uv (agi-cluster) |
| apps | flight AGI_run | $ProjectFileDir$/src/agilab/examples/flight/AGI_run_flight.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI_run_flight.py | uv (flight_project) |
| apps | flight AGI_run | $ProjectFileDir$/src/agilab/examples/flight/AGI_run_flight.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI_run_flight.py | uv (flight_project) |
| apps | flight test | $ProjectFileDir$/src/agilab/apps/flight_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/app_test.py | uv (flight_project) |
| apps | flight test manager | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_manager.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_manager.py | uv (flight_project) |
| apps | flight_egg gen |  | --app-path $PROJECT_DIR$/src/agilab/apps/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run  --app-path $PROJECT_DIR$/src/agilab/apps/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | uv (flight_project) |
| apps | example_app AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app AGI_install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app AGI_install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app AGI_run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app AGI_run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app test | $ProjectFileDir$/src/agilab/apps/example_app_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/app_test.py | uv (example_app_project) |
| apps | example_app test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py | uv (example_app_project) |
| apps | example_app_egg gen |  | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run  --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| apps | example_app AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app AGI_install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app AGI_install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app AGI_run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app AGI_run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app test | $ProjectFileDir$/src/agilab/apps/example_app_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/app_test.py | uv (example_app_project) |
| apps | example_app test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py | uv (example_app_project) |
| apps | example_app_egg gen |  | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run  --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| apps | mycode AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/mycode/AGI_get_distrib_mycode.py |  | $ProjectFileDir$/src/agilab/examples/mycode | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/mycode && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI_get_distrib_mycode.py | uv (mycode_project) |
| apps | mycode AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/mycode/AGI_get_distrib_mycode.py |  | $ProjectFileDir$/src/agilab/examples/mycode | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/mycode && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI_get_distrib_mycode.py | uv (mycode_project) |
| apps | mycode AGI_install | $ProjectFileDir$/src/agilab/examples/mycode/AGI_install_mycode.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI_install_mycode.py | uv (agi-cluster) |
| apps | mycode AGI_install | $ProjectFileDir$/src/agilab/examples/mycode/AGI_install_mycode.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI_install_mycode.py | uv (agi-cluster) |
| apps | mycode AGI_run | $ProjectFileDir$/src/agilab/examples/mycode/AGI_run_mycode.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI_run_mycode.py | uv (mycode_project) |
| apps | mycode AGI_run | $ProjectFileDir$/src/agilab/examples/mycode/AGI_run_mycode.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI_run_mycode.py | uv (mycode_project) |
| apps | mycode test | $ProjectFileDir$/src/agilab/apps/mycode_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/app_test.py | uv (mycode_project) |
| apps | mycode test manager | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py | uv (mycode_project) |
| apps | mycode_egg gen |  | --app-path $PROJECT_DIR$/src/agilab/apps/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run  --app-path $PROJECT_DIR$/src/agilab/apps/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | uv (mycode_project) |
| apps | example_app AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app AGI_install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app AGI_install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app AGI_run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app AGI_run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app test | $ProjectFileDir$/src/agilab/apps/example_app_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/app_test.py | uv (example_app_project) |
| apps | example_app test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py | uv (example_app_project) |
| apps | example_app_egg gen |  | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run  --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| apps | example_app AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app AGI_get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app AGI_install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app AGI_install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app AGI_run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app AGI_run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app test | $ProjectFileDir$/src/agilab/apps/example_app_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/app_test.py | uv (example_app_project) |
| apps | example_app test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py | uv (example_app_project) |
| apps | example_app_egg gen |  | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run  --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| components | flight call worker | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_call_worker.py | uv (flight_project) |
| components | flight test worker | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_worker.py | uv (flight_worker) |
| components | flight_lib gen |  | --app-path $USER_HOME$/wenv/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | $USER_HOME$/wenv/flight_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/flight_worker && uv run  --app-path $USER_HOME$/wenv/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | uv (flight_worker) |
| components | flight_postinstall test | $USER_HOME$/wenv/flight_worker/src/flight_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/flight_project 1 $USER_HOME$/data/flight | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $USER_HOME$/wenv/flight_worker/src/flight_worker/post_install.py $ProjectFileDir$/src/agilab/apps/flight_project 1 $USER_HOME$/data/flight | uv (flight_worker) |
| components | flight_preinstall test | $PROJECT_DIR$/src/agilab/apps/flight_project/src/flight_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $PROJECT_DIR$/src/agilab/apps/flight_project/src/flight_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | uv (flight_project) |
| components | example_app call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | example_app test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | example_app_lib gen |  | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run  --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | example_app_postinstall test | $USER_HOME$/wenv/example_worker/src/example_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project 1 $USER_HOME$/data/example_app | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $USER_HOME$/wenv/example_worker/src/example_worker/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project 1 $USER_HOME$/data/example_app | uv (example_worker) |
| components | example_app_preinstall test | $PROJECT_DIR$/src/agilab/apps/example_app_project/src/example_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/apps/example_app_project/src/example_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
| components | example_app call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | example_app test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | example_app_lib gen |  | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run  --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | example_app_postinstall test | $USER_HOME$/wenv/example_worker/src/example_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project 1 $USER_HOME$/data/example_app | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $USER_HOME$/wenv/example_worker/src/example_worker/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project 1 $USER_HOME$/data/example_app | uv (example_worker) |
| components | example_app_preinstall test | $PROJECT_DIR$/src/agilab/apps/example_app_project/src/example_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/apps/example_app_project/src/example_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
| components | mycode call worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py | uv (mycode_project) |
| components | mycode test worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py | uv (mycode_worker) |
| components | mycode_lib gen |  | --app-path $USER_HOME$/wenv/mycode_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | $USER_HOME$/wenv/mycode_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/mycode_worker && uv run  --app-path $USER_HOME$/wenv/mycode_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | uv (mycode_worker) |
| components | mycode_postinstall test | $USER_HOME$/wenv/mycode_worker/src/mycode_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/mycode_project 1 $USER_HOME$/data/mycode | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $USER_HOME$/wenv/mycode_worker/src/mycode_worker/post_install.py $ProjectFileDir$/src/agilab/apps/mycode_project 1 $USER_HOME$/data/mycode | uv (mycode_worker) |
| components | mycode_preinstall test | $PROJECT_DIR$/src/agilab/apps/mycode_project/src/mycode_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/mycode_worker/src/mycode_worker/mycode_worker.py | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $PROJECT_DIR$/src/agilab/apps/mycode_project/src/mycode_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/mycode_worker/src/mycode_worker/mycode_worker.py | uv (mycode_project) |
| components | example_app call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | example_app test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | example_app_lib gen |  | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run  --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | example_app_postinstall test | $USER_HOME$/wenv/example_worker/src/example_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project 1 $USER_HOME$/data/example_app | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $USER_HOME$/wenv/example_worker/src/example_worker/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project 1 $USER_HOME$/data/example_app | uv (example_worker) |
| components | example_app_preinstall test | $PROJECT_DIR$/src/agilab/apps/example_app_project/src/example_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/apps/example_app_project/src/example_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
| components | example_app call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | example_app test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | example_app_lib gen |  | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run  --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | example_app_postinstall test | $USER_HOME$/wenv/example_worker/src/example_worker/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project 1 $USER_HOME$/data/example_app | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $USER_HOME$/wenv/example_worker/src/example_worker/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project 1 $USER_HOME$/data/example_app | uv (example_worker) |
| components | example_app_preinstall test | $PROJECT_DIR$/src/agilab/apps/example_app_project/src/example_worker/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/apps/example_app_project/src/example_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
| views | run view_autoencoder_latenspace | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_autoencoder_latenspace | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_autoencoder_latenspace | uv (view_autoencoder_latenspace) |
| views | run view_barycentric | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_barycentric | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_barycentric | uv (view_barycentric) |
| views | run view_maps | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_maps | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_maps | uv (view_maps) |
| views | run view_maps_3d | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_maps_3d | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_maps_3d | uv (view_maps_3d) |
| views | run view_maps_network | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_maps_network | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_maps_network | uv (view_maps_network) |
| views | view_autoencoder_latenspace | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/view_autoencoder_latentspace.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/view_autoencoder_latentspace.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  |
| views | view_barycentric | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (view_barycentric) |
| views | view_maps | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (view_maps) |
| views | view_maps_3d | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (view_maps_3d) |
| views | view_maps_network | streamlit | run $ProjectFileDir$/src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run streamlit run $ProjectFileDir$/src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py -- --install-type 1 --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (view_maps_network) |
</details>

## Progressive test plan

### Tier A — Quick checks (fast sanity)
- UI smoke: `cd $ProjectFileDir$ && uv run streamlit run src/agilab/AGILAB.py -- --install-type 1 --openai-api-key "your-key" --apps-dir src/agilab/apps` (agilab run dev)
- Dependencies: `cd $ProjectFileDir$ && uv run python tools/show_dependencies.py --repo testpypi`
- App skeleton: `uv run python src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py`

### Tier B — Component/app flows
- Flight: run → test manager/worker → distribute → call → pre/postinstall
  - `cd src/agilab/apps/flight_project && uv run python ../../snippets/AGI.run_flight.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_flight_manager.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_flight_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_flight.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_call_worker.py`
  - `cd src/agilab/apps/flight_project && uv run python src/flight_worker/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py`
  - `cd src/agilab/apps/flight_project && uv run python $USER_HOME$/wenv/flight_worker/src/flight_worker/post_install.py src/agilab/apps/flight_project 1 $USER_HOME$/data/flight`
- Link model:
  - `cd src/agilab/apps/example_app_project && uv run python ../../snippets/AGI.run_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_app_manager.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_call_worker.py`
- MyCode:
  - `cd src/agilab/apps/mycode_project && uv run python ../../snippets/AGI.run_mycode.py`
  - `cd src/agilab/apps/mycode_project && uv run python test/_test_mycode_manager.py`
  - `cd src/agilab/apps/mycode_project && uv run python test/_test_mycode_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_mycode.py`
  - `cd src/agilab/apps/mycode_project && uv run python test/_test_call_worker.py`
- Example App:
  - `cd src/agilab/apps/example_app_project && uv run python ../../snippets/AGI.run_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_app_manager.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_call_worker.py`
- Sb3Trainer:
  - `cd src/agilab/apps/example_app_project && uv run python ../../snippets/AGI.run_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_app_manager.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_worker.py`
  - `cd src/agilab/snippets && uv run python AGI.get_distrib_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_call_worker.py`
- FireDucks worker (core):
  - `cd src/agilab/core/agi-cluster && uv run pytest src/agilab/core/test/test_fireducks_worker.py`

### Tier C — Apps-pages and end-user
- Apps-pages: launch Streamlit pages bound to an active app
- `uv run streamlit run src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --active-app src/agilab/apps/flight_project`
- `uv run streamlit run src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --active-app src/agilab/apps/flight_project`
- `▶️ EXECUTE` page tips:
  - Use the sidebar `Verbosity level` select to choose AgiEnv verbosity (0–3). The value propagates to the generated install/distribute/run snippets and appears in the install log header.
  - Install output now streams inside the dedicated **Install logs** expander. Keep it open to watch live progress even if the snippet expander is collapsed.
- End-user mode: `cd ../agi-space && uv run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key"`

For each tier, capture: command, expected output, and pitfalls (CWD, env vars, interpreter).

## Troubleshooting & environment

- **Interpreter/SDK**: prefer the project environment (`uv`). Otherwise point to the full interpreter path or call through `uv run`.
- **Environment variables**: inspect `<envs/>` in the XML and mirror them in a `.env.example` (use placeholders, never secrets).
- **Common errors**:
  - `ModuleNotFoundError`: ensure the working directory matches `WORKING_DIRECTORY` and that `PYTHONPATH` carries the project roots.
  - Streamlit logs missing: set `PYTHONUNBUFFERED=1`.
  - Slow iterative runs: add `UV_NO_SYNC=1` in dev environments.

**`.env.example` (template)**
```dotenv
OPENAI_API_KEY=__set_me__
AGI_CLUSTER_URL=__set_me__
```

## Automate with Codex (safe write with approvals)

```bash
codex --model gpt-5-codex --approvals ask "
Update AGENTS.md: refresh the 'Run matrix' and 'Progressive test plan' under 'How to work on this repository'
by parsing .idea/runConfigurations/*.xml:
- Extract: name, SCRIPT_NAME, PARAMETERS, WORKING_DIRECTORY, envs, interpreter
- Group rows by app/component/app-pages heuristics (agilab/, agi-*/, apps/, apps-pages/, apps/templates/)
- Render a markdown table with copy-pasteable commands (cd + python/uv run)
- Keep edits scoped to this section; show a unified diff before saving"
```

## Keeping run configs in sync
- When you create or rename workflows, clone an existing XML, tweak script/workdir/interpreter, and keep the grouping tidy.
- Treat `.idea/runConfigurations/` as the canonical “how do I repro this?” checklist and regenerate the matrix whenever something changes.
- Important: when renaming or relocating scripts/entries, update both:
  - The concrete launchers in `.idea/runConfigurations/*.xml` (names, `SCRIPT_NAME`, `WORKING_DIRECTORY`, envs).
  - The PyCharm templates and helpers under `pycharm/` and related generators, for example:
    - `pycharm/app_scripts/_template_app_*.xml`
    - `pycharm/setup_pycharm.py`
    - `pycharm/gen_app_script.py`
    - `src/agilab/core/gen_app_script.py` (if you rely on the core helper)
  - After changes, re-run the “Run matrix” refresh to keep docs aligned.

### Regenerate run configs (step-by-step)

1. Update templates (if needed)
   - Edit `pycharm/app_scripts/_template_app_*.xml` to reflect new script names/paths (e.g., `AGI.get_distrib_*`).

2. Sync PyCharm modules + registered SDKs
   - `uv run python pycharm/setup_pycharm.py`

3. Re-generate per‑app launchers (one per app)
   - Examples:
     - `uv run python pycharm/gen_app_script.py flight`
     - `uv run python pycharm/gen_app_script.py example_app`
     - `uv run python pycharm/gen_app_script.py mycode`
     - `uv run python pycharm/gen_app_script.py example_app`
     - `uv run python pycharm/gen_app_script.py example_app`

4) Verify
   - Inspect `.idea/runConfigurations/*.xml` for updated `SCRIPT_NAME`, names, and `folderName` grouping.

5) Refresh the Run Matrix in this doc
   - Use the snippet under “How to refresh this matrix” to re-print rows and paste in place.

---

## Service Mode (`AGI.serve`)

- Prefer `AGI.serve` over `AGI.run` for long-lived agents: it keeps workers attached and
  runs `BaseWorker.loop` on each Dask worker via `Client.submit`.
- `BaseWorker.loop` creates a thread-safe stop event and honours worker-defined `loop`
  hooks (sync or async). Returning `False` or calling `BaseWorker.break()` stops the loop.
- Use `AGI.serve(..., action="stop")` to broadcast `BaseWorker.break` and wait for
  graceful teardown before optionally shutting down the cluster.

## AgiEnv environment flags and path discovery

- `AgiEnv.is_source_env`: True when running from a source checkout (not from site/dist-packages).
- `AgiEnv.is_worker_env`: True in worker-only contexts (apps_dir unset or under a `wenv/*_worker`).
- `AgiEnv.is_local_worker`: True when the environment resides under the user's home “agilab” tree.
- `AgiEnv._ensure_path_cache` reads `~/.local/share/agilab/.agilab-path` first; the file
  stores the absolute path to `agilab/src/agilab` in repo checkouts (source layout).
- If the hint is missing, it falls back to ``importlib.util.find_spec("agilab")`` and, as a
  last resort, a parent-directory scan around `agi_env` to support packaged installs.
- `read_agilab_path` guards logging in case the shared logger is not configured.

## Coding Standards

- Follow **PEP8** with project-specific exceptions documented in `pyproject.toml`.
- Type hints are **required** for public functions; enforce with `mypy`.
- Prefer the simplest viable solution before introducing additional abstractions.
- Prefer composition over inheritance; interfaces live in `agilab/core/`.
- Break cycles; respect clear layering (core → components → apps → pages).
- Never commit symlinks to the repository; keep repo trees portable across platforms.

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
Note: The legacy `install_type` is removed from docs and internal logic. Existing
run-configs that still pass `--install-type` can omit it; refresh the run matrix
to remove obsolete flags.
