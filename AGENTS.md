# AGILab Agent Runbook

AGILab ships with a curated set of run configurations, CLI wrappers, and automation
scripts that let GPT-5 Codex and human operators work from the same playbook. This
document mirrors the Spec Kit style guide so every agent—manual or autonomous—follows
consistent launch, validation, and troubleshooting steps.

Use this runbook whenever you:
- Launch Streamlit or CLI flows from PyCharm run configurations.
- Regenerate agent/CLI wrappers after editing `.idea/runConfigurations`.
- Diagnose install or cluster issues reported by AGI agents or end users.

> **Keep this file current.** Update it alongside any run configuration,
> environment variable, or Streamlit change. CI, support, reviewers, and downstream
> agents rely on it for reproducible workflows.

---

## General practices

- **uv everywhere**: Invoke Python entry points through `uv` (`uv --preview-features extra-build-dependencies run python …`,
  `uv --preview-features extra-build-dependencies run streamlit …`) so dependencies resolve inside the managed environments that
  ship with AGILab.
- **Upgrade packaged tools first**: Before launching the published CLI with `uvx
  agilab`, run `uv --preview-features extra-build-dependencies tool upgrade agilab` to pick up the latest wheel.
- **No repo uvx**: Reserve `uvx` for packaged installs outside this checkout. Launching
  it from the source tree swaps in the published wheel and discards your local changes.
- **Run config parity**: After touching `.idea/runConfigurations/*.xml`, regenerate
  the CLI wrappers with `uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py` and commit
  the results (`tools/run_configs/`).
- **Model compatibility**: When working with GPT-5 Codex agents, confirm no new code
  calls deprecated Streamlit APIs like `st.experimental_rerun()`. Always migrate to
  `st.rerun` before merging.
- **No silent fallbacks**: Do not introduce automatic API client fallbacks
  (`chat.completions` ↔ `responses`, runtime parameter rewrites, etc.). Detect missing
  capabilities up-front and fail with a clear, actionable error.
- **Installer hygiene**: The end-user installer guarantees `pip` inside
  `~/agi-space/.venv` and uses `uv --preview-features extra-build-dependencies pip` afterwards. If an install reports
  `No module named pip`, rerun the latest installer or execute
  `uv --preview-features extra-build-dependencies run python -m ensurepip --upgrade` once in `~/agi-space`.
- **Missing dependency triage**: Whenever an app run fails because a module cannot be imported, check *both*
  `src/agilab/apps/<app>/pyproject.toml` (manager environment) and
  `src/agilab/apps/<app>/src/<app>_worker/pyproject.toml` to confirm the dependency is declared in the correct scope.
- **Installer flags**: For automation, use `./install.sh --non-interactive`/`-y` with required flags
  (`--cluster-ssh-credentials`, `--openai-api-key`). Optional flags: `--apps-repository`,
  `--install-path`, `--install-apps [all|builtin|comma list]`, `--test-apps`.
- **Apps repository symlinks**: Set `APPS_REPOSITORY` (or `AGILAB_APPS_REPOSITORY`) in
  `~/.local/share/agilab/.env` to the path of your apps repository checkout. The installer can
  create symlinks so optional apps/pages resolve without manual action.
- **Built-in apps directory**: First-party apps such as `flight_project` and `mycode_project` now live under
  `src/agilab/apps/builtin/`. Update local commands accordingly; repository apps cloned via `install_apps.sh`
  still appear under `src/agilab/apps/`.
- **Manager class aliases**: Every app module must expose both the legacy name and its ``*App`` variant
  (for example `FooApp` and `Foo`) so older installers keep working. Add or preserve these
  subclasses whenever you touch an app manager.
- **Flight dependencies**: Follow the project’s own metadata for Streamlit/matplotlib/OpenAI—no extra
  trimming beyond the flight worker manifest.
- **Runtime isolation**: Anything launched from `~/agi-space` must assume the upstream
  `~/agilab` checkout is absent. Agents can only reference packaged assets inside the
  virtual environment—never repository-relative paths.
- **Config preservation**: Run `tools/preserve_app_configs.sh lock` to keep local edits
  to any `app_args_form.py`, `app_settings.toml`, or `pre_prompt.json` under
  `src/agilab/apps/` out of commits and pushes. Invoke `unlock` when you intentionally
  want to share updates.
- **Model defaults**: `agi_env.defaults` centralises the fallback OpenAI model. Set
  `AGILAB_DEFAULT_OPENAI_MODEL` to override globally without editing code; individual
  runs can still pass `OPENAI_MODEL`.
- **History metadata**: `lab_steps.toml` now records an `M` field for each step so the
  saved history shows which model produced the snippet. Older automations should ignore
  unknown keys.
- **PyCharm Local History recovery**: If Git does not have the version you need, use
  PyCharm’s Local History (right-click file → Local History → Show History) or the
  helper script `pycharm/local_history_helper.py` to back up and scan
  `~/Library/Caches/JetBrains/<PyCharm>/LocalHistory/changes.storageData` for a
  filename. Example: `python3 pycharm/local_history_helper.py --grep EXPERIMENT.py --backup /tmp/local-history-backups`.
  The script does not reconstruct full contents (JetBrains format is proprietary)
  but preserves the store and surfaces offsets so you can open the snapshots in the IDE.
- **Shared build tooling**: All packaging routes through
  `python -m agi_node.agi_dispatcher.build --app-path …`. Per-app `build.py` helpers
  are deprecated.
- **Hook consolidation**: Worker `pre_install`/`post_install` logic lives in
  `agi_node.agi_dispatcher.{pre_install,post_install}`. Add lightweight wrappers near
  the worker if custom behavior is required.
- **Cython sources**: Never hand-edit generated `.pyx`/`.c` worker files; they are rebuilt automatically by the tooling pipeline.
- **Protect generated Cython**: To avoid accidental edits or regenerations on local checkouts, you can temporarily drop write permission on generated `.pyx`/`.c` files (e.g., `chmod a-w src/*_worker/*.pyx`) and rerun the build tooling when you actually need fresh outputs.
- **AgiEnv lifecycle**: `AgiEnv` is a singleton. Treat instance attributes as the
  source of truth. Helpers like `set_env_var`, `read_agilab_path`, `_build_env`, and
  `log_info` are pre-init safe; avoid relying on class attributes before instantiating
  `AgiEnv()`.
- **App constructor kwargs**: App constructors ignore unknown kwargs when building
  their Pydantic `Args` models. Keep runtime verbosity and logging decisions in
  `AgiEnv(verbose=…)` or logging configs, not app `Args`.
- **Docs edits**: `docs/html` in this repo is generated output. Regenerate docs with your documentation
  tooling and commit the updated `docs/html/`.
- **VIRTUAL_ENV warning**: `uv` may emit `VIRTUAL_ENV=... does not match the project environment path ...; use --active...`.
  This is expected because AGILAB manages multiple venvs per app/local/shared install. Ignore unless you intend to run against the currently activated venv.

### Install Error Check (at Codex startup)

- Check the latest installer log for errors before running flows.
- Log locations:
  - Windows: `C:\Users\<you>\log\install_logs`
  - macOS/Linux: `$HOME/log/install_logs`
- PowerShell quick check (Windows):
  - `($d = "$HOME\log\install_logs"); $f = Get-ChildItem -LiteralPath $d -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($f) { Write-Host "Log:" $f.FullName; Select-String -LiteralPath $f.FullName -Pattern '(?i)(error|exception|traceback|failed|fatal|denied|missing|not found)' | Select-Object -Last 25 | ForEach-Object { $_.Line } } else { Write-Host "No logs found." }`
- Bash quick check (macOS/Linux):
  - `dir="$HOME/log/install_logs"; f=$(ls -1t "$dir"/*.log 2>/dev/null | head -1); [ -n "$f" ] && echo "Log: $f" && grep -Eai "error|exception|traceback|failed|fatal|denied|missing|not found" "$f" | tail -n 25 || echo "No logs found."`

## GPT-OSS helpers

- Launch the local Responses API with `uv --preview-features extra-build-dependencies run python tools/launch_gpt_oss.py`. Defaults keep the server on `127.0.0.1:8000` using the `gpt-oss-120b` checkpoint and the `transformers` backend. Pass `--print-only` to inspect the command or append extra arguments after `--`.
- Configure environment overrides (`GPT_OSS_MODEL`, `GPT_OSS_ENDPOINT`, `GPT_OSS_BACKEND`, `GPT_OSS_PORT`, `GPT_OSS_WORKDIR`) before invoking the launcher when you need alternate checkpoints or ports.
- Condense long task descriptions via `uv --preview-features extra-build-dependencies run python tools/gpt_oss_prompt_helper.py --prompt "..."` or pipe text through stdin. The helper calls GPT-OSS, stores the summary under `~/.cache/agilab/gpt_oss_prompt_cache.json`, and reuses cached briefs until `--force-refresh` is provided.
- Set `GPT_OSS_CACHE` to move the cache file, `--no-cache` to bypass writes, and `--show-metadata` to display latency and token usage. Cached runs are tagged with the model and endpoint that produced the summary.
- Use the `./lq` wrapper for quick one-liners (`./lq "Summarise …"`). Prepend options (e.g. `./lq --force-refresh -- "Prompt"`) or run it with no arguments to read from stdin. Add the repo root to your `PATH` if you want `lq` available globally.

---

## Agent workflows and maintenance

### 1. Update or add run configurations
1. Edit the PyCharm run configuration (`.idea/runConfigurations/*.xml`).
2. Regenerate CLI wrappers: `uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py`.
3. Verify the generated scripts under `tools/run_configs/` and commit the changes.
4. Update the launch matrix in this document when new configs appear.

### 2. Launch flows
- **PyCharm (recommended)**: Use the run configurations defined in the launch matrix.
- **CLI mirror**: Copy the `How to run` command from the matrix into a shell for quick
  reproduction outside the IDE.
- **Streamlit UI**: Use Streamlit commands from the matrix to align with agent-driven
  flows.

### 3. Troubleshoot installs and cluster runs
1. Re-run the relevant config while tailing logs via the Streamlit expander or CLI.
2. Check for connectivity issues (e.g., unreachable SSH hosts): the orchestrator emits
  concise warnings without full tracebacks.
3. Confirm `uv` executables exist on remote hosts before reattempting distributed
  installs.
4. Document fixes or new failure modes in this runbook so future agents can respond
  consistently.

<details>
<summary><strong>Launch matrix (auto-sorted from .idea/runConfigurations)</strong></summary>

| Group | Config name | Entry | Args | Workdir | Env | How to run | Interpreter |
|---|---|---|---|---|---|---|---|
| agilab | agilab run (dev) | streamlit | run $ProjectFileDir$/src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1;IS_SOURCE_ENV=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps |  |
| agilab | agilab run (enduser) | streamlit | run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" | $ProjectFileDir$/../agi-space | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/../agi-space && uv run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" | uv (agi-space) |
| agilab | app_script gen | $ProjectFileDir$/pycharm/gen_app_script.py | $Prompt:Enter app manager name:flight$ |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/pycharm/gen_app_script.py $Prompt:Enter app manager name:flight$ |  |
| agilab | apps-pages launcher | $ProjectFileDir$/tools/apps_pages_launcher.py | --active-app $ProjectFileDir$/src/agilab/apps/flight_project | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/apps_pages_launcher.py --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (agilab) |
| agilab | apps-pages smoke | $ProjectFileDir$/tools/smoke_preinit.py | --active-app $ProjectFileDir$/src/agilab/apps/flight_project --timeout 20 | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/smoke_preinit.py --active-app $ProjectFileDir$/src/agilab/apps/flight_project --timeout 20 | uv (agilab) |
| agilab | builtin/flight get_distrib | $USER_HOME$/log/execute/flight/AGI_get_flight.py |  | $USER_HOME$/log/execute/builtin/flight | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/log/execute/builtin/flight && uv run python $USER_HOME$/log/execute/flight/AGI_get_flight.py |  |
| agilab | builtin/flight install | $USER_HOME$/log/execute/flight/AGI_install_flight.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $USER_HOME$/log/execute/flight/AGI_install_flight.py |  |
| agilab | builtin/mycode get_distrib | $USER_HOME$/log/execute/mycode/AGI_get_mycode.py |  | $USER_HOME$/log/execute/builtin/mycode | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/log/execute/builtin/mycode && uv run python $USER_HOME$/log/execute/mycode/AGI_get_mycode.py |  |
| agilab | builtin/mycode install | $USER_HOME$/log/execute/mycode/AGI_install_mycode.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $USER_HOME$/log/execute/mycode/AGI_install_mycode.py |  |
| agilab | lab_run test | $PROJECT_DIR$/src/agilab/lab_run.py | --openai-api-key "your-key" | $USER_HOME$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$ && uv run python $PROJECT_DIR$/src/agilab/lab_run.py --openai-api-key "your-key" | uv (agilab) |
| agilab | publish dry-run (testpypi) | $ProjectFileDir$/tools/pypi_publish.py | --repo testpypi --dry-run --leave-most-recent --verbose | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/pypi_publish.py --repo testpypi --dry-run --leave-most-recent --verbose | uv (agilab) |
| agilab | pypi publish | $ProjectFileDir$/tools/pypi_publish.py | --repo pypi --leave-most-recent --verbose --cleanup $Prompt:Cleanup credentials$ | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/pypi_publish.py --repo pypi --leave-most-recent --verbose --cleanup $Prompt:Cleanup credentials$ | uv (agilab) |
| agilab | run ssh cmd | $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |
| agilab | show depencencies | $ProjectFileDir$/tools/show_dependencies.py | --repo pypi | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/show_dependencies.py --repo pypi | uv (agilab) |
| agilab | test agi_distributor |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python |  |
| agilab | test agi_env |  |  | $ProjectFileDir$/src/agilab/core/agi-env/test |  | cd $ProjectFileDir$/src/agilab/core/agi-env/test && uv run python | uv (agi-env) |
| agilab | test base_worker |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | test dag_worker |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | test pandas_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test polars_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test pypi publish | $ProjectFileDir$/tools/pypi_publish.py | --repo testpypi --leave-most-recent --verbose --cleanup $Prompt:Cleanup credentials$ | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/pypi_publish.py --repo testpypi --leave-most-recent --verbose --cleanup $Prompt:Cleanup credentials$ | uv (agilab) |
| agilab | test work_dispatcher |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | zip_all | $ProjectFileDir$/tools/zip_all.py | --dir2zip $FilePrompt$ --follow-app-links --exclude-dir docs,codex | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/zip_all.py --dir2zip $FilePrompt$ --follow-app-links --exclude-dir docs,codex |  |
| apps | app install (local) | $ProjectFileDir$/src/agilab/apps/install.py | $Prompt:selected app:src/agilab/apps/builtin/flight_project$ --install-type "1" --verbose 1 | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/apps/install.py $Prompt:selected app:src/agilab/apps/builtin/flight_project$ --install-type "1" --verbose 1 | uv (agi-cluster) |
| apps | app-test | $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py |  |  | PYTHONUNBUFFERED=1 | uv run python $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py | uv (agi-cluster) |
| apps | builtin/flight run | $USER_HOME$/log/execute/flight/AGI_run_flight.py |  | $ProjectFileDir$/src/agilab/apps/builtin/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/flight_project && uv run python $USER_HOME$/log/execute/flight/AGI_run_flight.py |  |
| apps | builtin/flight test manager | $ProjectFileDir$/src/agilab/apps/builtin/flight_project/test/test_builtin/flight_manager.py |  | $ProjectFileDir$/src/agilab/apps/builtin/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/builtin/flight_project/test/test_builtin/flight_manager.py |  |
| apps | builtin/mycode run | $USER_HOME$/log/execute/mycode/AGI_run_mycode.py |  | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/mycode_project && uv run python $USER_HOME$/log/execute/mycode/AGI_run_mycode.py |  |
| apps | builtin/mycode test manager | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project/test/test_builtin/mycode_manager.py |  | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/builtin/mycode_project/test/test_builtin/mycode_manager.py |  |
| components | builtin/flight call worker | $ProjectFileDir$/src/agilab/apps/builtin/flight_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/builtin/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/builtin/flight_project/test/_test_call_worker.py |  |
| components | builtin/flight test worker | $ProjectFileDir$/src/agilab/apps/builtin/flight_project/test/test_builtin/flight_worker.py |  | $ProjectFileDir$/src/agilab/apps/builtin/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/builtin/flight_project/test/test_builtin/flight_worker.py |  |
| components | builtin/flight_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/builtin/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/builtin/flight_worker | $ProjectFileDir$/src/agilab/apps/builtin/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/flight_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/builtin/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/builtin/flight_worker |  |
| components | builtin/flight_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/builtin/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/builtin/flight_worker | $USER_HOME$/wenv/builtin/flight_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/builtin/flight_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/builtin/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/builtin/flight_worker |  |
| components | builtin/flight_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/builtin/flight_project $USER_HOME$/data/builtin/flight | $ProjectFileDir$/src/agilab/apps/builtin/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/flight_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/builtin/flight_project $USER_HOME$/data/builtin/flight |  |
| components | builtin/flight_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/builtin/flight_worker/src/builtin/flight_worker/builtin/flight_worker.py | $ProjectFileDir$/src/agilab/apps/builtin/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/flight_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/builtin/flight_worker/src/builtin/flight_worker/builtin/flight_worker.py |  |
| components | builtin/mycode call worker | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/builtin/mycode_project/test/_test_call_worker.py |  |
| components | builtin/mycode test worker | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project/test/test_builtin/mycode_worker.py |  | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/builtin/mycode_project/test/test_builtin/mycode_worker.py |  |
| components | builtin/mycode_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/builtin/mycode_worker | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/mycode_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/builtin/mycode_worker |  |
| components | builtin/mycode_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/builtin/mycode_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/builtin/mycode_worker | $USER_HOME$/wenv/builtin/mycode_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/builtin/mycode_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/builtin/mycode_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/builtin/mycode_worker |  |
| components | builtin/mycode_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project $USER_HOME$/data/builtin/mycode | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/mycode_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/builtin/mycode_project $USER_HOME$/data/builtin/mycode |  |
| components | builtin/mycode_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/builtin/mycode_worker/src/builtin/mycode_worker/builtin/mycode_worker.py | $ProjectFileDir$/src/agilab/apps/builtin/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/builtin/mycode_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/builtin/mycode_worker/src/builtin/mycode_worker/builtin/mycode_worker.py |  |
</details>

**PyPI Cleanup (pypi-cleanup)**
- For non-interactive runs, set `PYPI_USERNAME` and `PYPI_CLEANUP_PASSWORD` (preferred). `PYPI_PASSWORD` is also accepted for compatibility.
- Accounts with 2FA enabled will prompt for an OTP and hang in CI. In that case either:
  - run interactively, or
  - use `--skip-cleanup`, or
  - use a dedicated service account (no 2FA) only for cleanup operations.
- Adjust timeout with `--cleanup-timeout` (default 60s) when invoking `tools/pypi_publish.py`.

**Docs Publishing**
- The published site is committed under `docs/html` (tracked in git).
- GitHub Pages deploys the committed content; CI no longer installs or runs Sphinx.
- To update docs, regenerate `docs/html/` with your documentation tooling and commit the result.

**CI & Badges**
- Tests run in a dedicated `ci` workflow; README badges reference the GH Actions status badge.
- Coverage uploads to Codecov for public reporting; README includes a Codecov badge. No Codecov token required for public repos.

**Tagging**
- Git tags now use a date-based scheme in UTC: `YYYY.MM.DD` (e.g., `2025.10.08`).
- If multiple tags are created on the same day, a numeric suffix is appended (e.g., `2025.10.08-2`).
- Package versions are independent and continue to follow PEP 440.

**Publishing to PyPI/TestPyPI**
- Use the Python script directly or the PyCharm run configuration:
  - CLI (dry run): `uv --preview-features extra-build-dependencies run python tools/pypi_publish.py --repo testpypi --dry-run`
  - CLI (TestPyPI): `uv --preview-features extra-build-dependencies run python tools/pypi_publish.py --repo testpypi`
- CLI (PyPI): `uv --preview-features extra-build-dependencies run python tools/pypi_publish.py --repo pypi`
- PyCharm: run configurations “publish dry-run (testpypi)”, “testpypi publish”, “pypi publish”.
- PyPI direct (no IDE): `uv --preview-features extra-build-dependencies run tools/pypi_publish.py --repo pypi --purge-after --username "<pypi-user>" --password "<pypi-pass>" --git-commit-version --retries 2` (expects `~/.pypirc` to mirror the current repo content so token-based logins keep working).
- Cleanup-only (with OTP prompt): `uv --preview-features extra-build-dependencies run tools/pypi_publish.py --repo pypi --cleanup-only --username "<pypi-user>" --password "<pypi-pass>"` and enter the 2FA code when PyPI asks.
- Developer refresh tip: after merging or bumping package code, run `uv --preview-features extra-build-dependencies tool update agilab agi-env agi-node agi-core agi-cluster` so `uvx` pulls the latest CLI entry points.
- Options: `--leave-most-recent`, `--skip-cleanup`, `--cleanup-timeout N`, `--cleanup username:password`, `--twine-username __token__`, `--twine-password`, `--yank-previous`.
- Cleanup defaults: TestPyPI cleanup is skipped automatically (avoids interactive web login/timeouts). To run cleanup, provide `--cleanup username:password` (or set `PYPI_USERNAME`/`PYPI_CLEANUP_PASSWORD` / configure `~/.pypirc`). The script reads the username from `~/.pypirc` when available.

## Progressive test plan

### Tier A — Quick checks (fast sanity)
- UI smoke: `cd $ProjectFileDir$ && uv --preview-features extra-build-dependencies run streamlit run src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir src/agilab/apps` (agilab run dev)
- Dependencies: `cd $ProjectFileDir$ && uv --preview-features extra-build-dependencies run python tools/show_dependencies.py --repo testpypi`
- App skeleton: `uv --preview-features extra-build-dependencies run python src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py`

### Tier B — Component/app flows
- Flight: run → test manager/worker → distribute → call → pre/postinstall
  - `cd src/agilab/apps/builtin/flight_project && uv --preview-features extra-build-dependencies run python ../../examples/flight/AGI_run_flight.py`
  - `cd src/agilab/apps/builtin/flight_project && uv --preview-features extra-build-dependencies run python test/_test_flight_manager.py`
  - `cd src/agilab/apps/builtin/flight_project && uv --preview-features extra-build-dependencies run python test/_test_flight_worker.py`
  - `cd src/agilab/examples/flight && uv --preview-features extra-build-dependencies run python AGI_get_distrib_flight.py`
  - `cd src/agilab/apps/builtin/flight_project && uv --preview-features extra-build-dependencies run python test/_test_call_worker.py`
  - `cd src/agilab/apps/builtin/flight_project && uv --preview-features extra-build-dependencies run python ../../core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py`
  - `cd src/agilab/apps/builtin/flight_project && uv --preview-features extra-build-dependencies run python ../../core/agi-node/src/agi_node/agi_dispatcher/post_install.py src/agilab/apps/builtin/flight_project $USER_HOME$/data/flight`
- MyCode:
  - `cd src/agilab/apps/builtin/mycode_project && uv --preview-features extra-build-dependencies run python ../../examples/mycode/AGI_run_mycode.py`
  - `cd src/agilab/apps/builtin/mycode_project && uv --preview-features extra-build-dependencies run python test/_test_mycode_manager.py`
  - `cd src/agilab/apps/builtin/mycode_project && uv --preview-features extra-build-dependencies run python test/_test_mycode_worker.py`
  - `cd src/agilab/examples/mycode && uv --preview-features extra-build-dependencies run python AGI_get_distrib_mycode.py`
  - `cd src/agilab/apps/builtin/mycode_project && uv --preview-features extra-build-dependencies run python test/_test_call_worker.py`
- FireDucks worker (core):
  - `cd src/agilab/core/agi-cluster && uv --preview-features extra-build-dependencies run pytest src/agilab/core/test/test_fireducks_worker.py`

### Tier C — Apps-pages and end-user
- Apps-pages: launch Streamlit pages bound to an active app
- `uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py -- --active-app src/agilab/apps/builtin/flight_project`
- `uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py -- --active-app src/agilab/apps/builtin/flight_project`
- `uv --preview-features extra-build-dependencies run streamlit run src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py -- --active-app src/agilab/apps/builtin/flight_project`
- `view_maps_network` tip: use the sidebar **Edges file picker** to select a topology export (for example `AGI_SHARE_DIR/network_sim/pipeline/ilp_topology.gml`) instead of manually typing a path.
- `view_maps_network` tip: for **📡 Live allocations**, use the **Trajectory data picker** (or custom glob like `AGI_SHARE_DIR/flight_trajectory/pipeline/*.csv`) so the overlay can place nodes/edges on the map.
- `view_maps_network` tip: most sidebar picks persist via app settings + URL query params (`edges_file`, `traj_glob`, `allocations_file`, `baseline_allocations_file`); copy the URL to share a reproducible snapshot configuration.
- `▶️ EXECUTE` page tips:
  - Use the sidebar `Verbosity level` select to choose AgiEnv verbosity (0–3). The value propagates to the generated install/distribute/run snippets and appears in the install log header.
  - Install output now streams inside the dedicated **Install logs** expander. Keep it open to watch live progress even if the snippet expander is collapsed.
- End-user mode: `cd ../agi-space && uv --preview-features extra-build-dependencies run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key"`

For each tier, capture: command, expected output, and pitfalls (CWD, env vars, interpreter).

## Troubleshooting & environment

- **Interpreter/SDK**: prefer the project environment (`uv`). Otherwise point to the full interpreter path or call through `uv --preview-features extra-build-dependencies run`.
- **Environment variables**: inspect `<envs/>` in the XML and mirror them in a `.env.example` (use placeholders, never secrets).
- **Cluster shared outputs (`AGI_SHARE_DIR`)**: when `cluster_enabled=true`, every worker must be able to read/write the same `AGI_SHARE_DIR` content.
  - Prefer `AGI_SHARE_DIR=~/clustershare` (tilde) so each node expands to its own home directory, but mounts the same NFS/SMB export there.
  - If `▶️ EXECUTE` warns that the directory “appears local”, confirm with `df -h ~/clustershare` and `mount | grep clustershare` (it should show `nfs`/`smbfs`, not `apfs`/local disks).
  - macOS automount tip: `/etc/auto_master` already contains `/- -static` and macOS ignores later duplicate `/-` entries. To use `/etc/auto_nfs`, replace `/- -static` with `/- auto_nfs` and run `sudo automount -vc` (or add the NFS mount to `/etc/fstab`, which `-static` reads).
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
- Render a markdown table with copy-pasteable commands (cd + python/uv --preview-features extra-build-dependencies run)
- Keep edits scoped to this section; show a unified diff before saving"
```

## Keeping run configs in sync
- When you create or rename workflows, clone an existing XML, tweak script/workdir/interpreter, and keep the grouping tidy.
- Treat `.idea/runConfigurations/` as the canonical “how do I repro this?” checklist and regenerate the matrix whenever something changes.
- `pycharm/gen_app_script.py` is already the source of truth—consider wrapping it (plus `setup_pycharm.py`) in a helper target (`just run-configs`, `make run-configs`) so local workflows and CI both depend on the same command.
- Important: when renaming or relocating scripts/entries, update both:
  - The concrete launchers in `.idea/runConfigurations/*.xml` (names, `SCRIPT_NAME`, `WORKING_DIRECTORY`, envs).
  - The PyCharm templates and helpers under `pycharm/` and related generators, for example:
    - `pycharm/app_scripts/_template_app_*.xml`
    - `pycharm/setup_pycharm.py`
    - `pycharm/gen_app_script.py`
    - `src/agilab/core/gen_app_script.py` (if you rely on the core helper)
  - After changes, re-run the “Run matrix” refresh to keep docs aligned.

## Apps dev Guidelines

- Keep core dependencies (`agi-env`, `agi-node`, `agi-cluster`) in the core layer; avoid duplicating them in app `pyproject.toml` unless the app must be standalone.

### Regenerate run configs (step-by-step)

1. Update templates (if needed)
   - Edit `pycharm/app_scripts/_template_app_*.xml` to reflect new script names/paths (e.g., `AGI_get_distrib_*`).

2. Sync PyCharm modules + registered SDKs
   - `uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py`

3. Re-generate per‑app launchers (one per app)
   - Examples:
     - `uv --preview-features extra-build-dependencies run python pycharm/gen_app_script.py flight`
     - `uv --preview-features extra-build-dependencies run python pycharm/gen_app_script.py mycode`
     - `uv --preview-features extra-build-dependencies run python pycharm/gen_app_script.py <app>`

4) Verify
   - Inspect `.idea/runConfigurations/*.xml` for updated `SCRIPT_NAME`, names, and `folderName` grouping.

5) Refresh the Run Matrix in this doc
   - `uv --preview-features extra-build-dependencies run python tools/refresh_launch_matrix.py --inplace`

6) Rebuild the CLI wrappers
   - `uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py`

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
- `AgiEnv.is_worker_env`: True in worker-only contexts (apps_path unset or under a `wenv/*_worker`).
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
- Automated packaging with `uv --preview-features extra-build-dependencies build` and release notes in GitHub

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
A: Start it with `uv --preview-features extra-build-dependencies run streamlit run ...` and check `PYTHONUNBUFFERED`.

**Q: Where do I add a new component?**  
A: Create `agi-<name>/` under the repo root with its own README and tests; wire it into the run matrix via a new JetBrains XML.

This repository uses Codex CLI for local agent development. Follow these notes when working as an agent in this project.

## Codex CLI Quickstart

- Start app development after an initial creation via EXECUTE project clone using:
  - `codex  --dangerously-bypass-approvals-and-sandbox --model gpt-5-codexr`
- Run the command from the repository root to give the agent full filesystem access with a non-interactive approval policy.
- Use only on your local, trusted machine. Do not run with these flags on shared or untrusted environments.

## Windows Path Tips

- When setting `APPS_REPOSITORY` in `%USERPROFILE%\.agilab\.env`, prefer forward slashes to avoid escape issues:
  - `APPS_REPOSITORY=C:/Users/<you>/path/to/your-apps-repo`
- Keep `AGILAB_APPS_REPOSITORY` in sync or set both keys.
- Ensure the apps pages directory exists under the apps repo: `src/agilab/apps-pages`.

## Conventions

- Keep documentation (e.g., runbooks) and scripts in sync with how agents are expected to launch and validate flows.
- Prefer concise, actionable updates and avoid adding unrelated scope in a single change.
