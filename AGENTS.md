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

- **uv everywhere**: Invoke Python entry points through `uv` (`uv run python …`,
  `uv run streamlit …`) so dependencies resolve inside the managed environments that
  ship with AGILab.
- **Upgrade packaged tools first**: Before launching the published CLI with `uvx
  agilab`, run `uv tool upgrade agilab` to pick up the latest wheel.
- **No repo uvx**: Reserve `uvx` for packaged installs outside this checkout. Launching
  it from the source tree swaps in the published wheel and discards your local changes.
- **Run config parity**: After touching `.idea/runConfigurations/*.xml`, regenerate
  the CLI wrappers with `uv run python tools/generate_runconfig_scripts.py` and commit
  the results (`tools/run_configs/`).
- **Model compatibility**: When working with GPT-5 Codex agents, confirm no new code
  calls deprecated Streamlit APIs like `st.experimental_rerun()`. Always migrate to
  `st.rerun` before merging.
- **No silent fallbacks**: Do not introduce automatic API client fallbacks
  (`chat.completions` ↔ `responses`, runtime parameter rewrites, etc.). Detect missing
  capabilities up-front and fail with a clear, actionable error.
- **Installer hygiene**: The end-user installer guarantees `pip` inside
  `~/agi-space/.venv` and uses `uv pip` afterwards. If an install reports
  `No module named pip`, rerun the latest installer or execute
  `uv run python -m ensurepip --upgrade` once in `~/agi-space`.
- **Fast reinstall mode**: Repeat installs now auto-detect prior runs and offer to enable
  fast mode (skips system deps, locale config, offline extras, matrix refresh). Accept the
  prompt or pass `./install.sh --fast [--python-version <major.minor>]` / `.\install.ps1 -Fast [-PythonVersion <major.minor>]`
  for non-interactive speedups. Use `--no-fast` / `-NoFast` or set `AGILAB_AUTO_FAST=0` when you
  need the full flow, and rerun without fast mode before shipping artifacts.
- **Apps repository symlinks**: Keep the apps repository (``APPS_REPOSITORY``) at the path recorded in
  `~/.local/share/agilab/.env`. On this machine it resolves to `/Users/example/PycharmProjects/agilab-apps`.
  The installer auto-creates symlinks so missing workers
  resolve without manual action.
- **Manager class aliases**: Every app module must expose both the legacy name and its ``*App`` variant
  (for example `Example AppApp` and `Example App`) so older installers keep working. Add or preserve these
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
- **Shared build tooling**: All packaging routes through
  `python -m agi_node.agi_dispatcher.build --app-path …`. Per-app `build.py` helpers
  are deprecated.
- **Hook consolidation**: Worker `pre_install`/`post_install` logic lives in
  `agi_node.agi_dispatcher.{pre_install,post_install}`. Add lightweight wrappers near
  the worker if custom behavior is required.
- **AgiEnv lifecycle**: `AgiEnv` is a singleton. Treat instance attributes as the
  source of truth. Helpers like `set_env_var`, `read_agilab_path`, `_build_env`, and
  `log_info` are pre-init safe; avoid relying on class attributes before instantiating
  `AgiEnv()`.
- **App constructor kwargs**: App constructors ignore unknown kwargs when building
  their Pydantic `Args` models. Keep runtime verbosity and logging decisions in
  `AgiEnv(verbose=…)` or logging configs, not app `Args`.

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

- Launch the local Responses API with `uv run python tools/launch_gpt_oss.py`. Defaults keep the server on `127.0.0.1:8000` using the `gpt-oss-120b` checkpoint and the `transformers` backend. Pass `--print-only` to inspect the command or append extra arguments after `--`.
- Configure environment overrides (`GPT_OSS_MODEL`, `GPT_OSS_ENDPOINT`, `GPT_OSS_BACKEND`, `GPT_OSS_PORT`, `GPT_OSS_WORKDIR`) before invoking the launcher when you need alternate checkpoints or ports.
- Condense long task descriptions via `uv run python tools/gpt_oss_prompt_helper.py --prompt "..."` or pipe text through stdin. The helper calls GPT-OSS, stores the summary under `~/.cache/agilab/gpt_oss_prompt_cache.json`, and reuses cached briefs until `--force-refresh` is provided.
- Set `GPT_OSS_CACHE` to move the cache file, `--no-cache` to bypass writes, and `--show-metadata` to display latency and token usage. Cached runs are tagged with the model and endpoint that produced the summary.
- Use the `./lq` wrapper for quick one-liners (`./lq "Summarise …"`). Prepend options (e.g. `./lq --force-refresh -- "Prompt"`) or run it with no arguments to read from stdin. Add the repo root to your `PATH` if you want `lq` available globally.

---

## Agent workflows and maintenance

### 1. Update or add run configurations
1. Edit the PyCharm run configuration (`.idea/runConfigurations/*.xml`).
2. Regenerate CLI wrappers: `uv run python tools/generate_runconfig_scripts.py`.
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

---

<details>
<summary><strong>Launch matrix (auto-sorted from .idea/runConfigurations)</strong></summary>

| Group | Config name | Entry | Args | Workdir | Env | How to run | Interpreter |
|---|---|---|---|---|---|---|---|
| agilab | agilab run (dev) | streamlit | run $ProjectFileDir$/src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run streamlit run $ProjectFileDir$/src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir $ProjectFileDir$/src/agilab/apps | uv (agilab) |
| agilab | agilab run (enduser) | streamlit | run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" | $ProjectFileDir$/../agi-space | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/../agi-space && uv run streamlit run .venv/lib/python3.13/site-packages/agilab/AGILAB.py -- --openai-api-key "your-key" | uv (agi-space) |
| agilab | app_script gen | $ProjectFileDir$/pycharm/gen_app_script.py | $Prompt:Enter app manager name:flight$ |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/pycharm/gen_app_script.py $Prompt:Enter app manager name:flight$ |  |
| agilab | apps-pages launcher | $ProjectFileDir$/tools/apps_pages_launcher.py | --active-app $ProjectFileDir$/src/agilab/apps/flight_project | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/apps_pages_launcher.py --active-app $ProjectFileDir$/src/agilab/apps/flight_project | uv (agilab) |
| agilab | apps-pages smoke | $ProjectFileDir$/tools/smoke_preinit.py | --active-app $ProjectFileDir$/src/agilab/apps/flight_project --timeout 20 | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/smoke_preinit.py --active-app $ProjectFileDir$/src/agilab/apps/flight_project --timeout 20 | uv (agilab) |
| agilab | lab_run test | $USER_HOME$/agi-workspace/.venv/lib/python3.12/site-packages/agilab/lab_run.py | --openai-api-key "your-key" | $USER_HOME$/agi-workspace/ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/agi-workspace/ && uv run python $USER_HOME$/agi-workspace/.venv/lib/python3.12/site-packages/agilab/lab_run.py --openai-api-key "your-key" | uv (agilab) |
| agilab | publish dry-run (testpypi) | $ProjectFileDir$/tools/pypi_publish.py | --repo testpypi --dry-run --leave-most-recent --verbose | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/pypi_publish.py --repo testpypi --dry-run --leave-most-recent --verbose | uv (agilab) |
| agilab | pypi publish | $ProjectFileDir$/tools/pypi_publish.py | --repo pypi --leave-most-recent --verbose --cleanup $Prompt:Cleanup credentials$ | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/pypi_publish.py --repo pypi --leave-most-recent --verbose --cleanup $Prompt:Cleanup credentials$ | uv (agilab) |
| agilab | run ssh cmd | $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |  | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $ProjectFileDir$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |
| agilab | show depencencies | $ProjectFileDir$/tools/show_dependencies.py | --repo pypi | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/show_dependencies.py --repo pypi | uv (agilab) |
| agilab | test agi_distributor |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test agi_env |  |  | $ProjectFileDir$/src/agilab/core/agi-env/test |  | cd $ProjectFileDir$/src/agilab/core/agi-env/test && uv run python | uv (agi-env) |
| agilab | test base_worker |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | test dag_worker |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | test pandas_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test polars_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test pypi publish | $ProjectFileDir$/tools/pypi_publish.py | --repo testpypi --leave-most-recent --verbose --cleanup $Prompt:Cleanup credentials$ | $ProjectFileDir$ | PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/pypi_publish.py --repo testpypi --leave-most-recent --verbose --cleanup $Prompt:Cleanup credentials$ | uv (agilab) |
| agilab | test work_dispatcher |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | zip_all | $ProjectFileDir$/tools/zip_all.py | --dir2zip src --zipfile src.zip --follow-app-links | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/tools/zip_all.py --dir2zip src --zipfile src.zip --follow-app-links |  |
| apps | app install (local) | $ProjectFileDir$/src/agilab/apps/install.py | $Prompt:selected app:~/PycharmProjects/agilab/src/agilab/apps/flight_project$ --install-type "1" --verbose 1 | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/apps/install.py $Prompt:selected app:~/PycharmProjects/agilab/src/agilab/apps/flight_project$ --install-type "1" --verbose 1 | uv (agi-cluster) |
| apps | app-test | $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py |  |  | PYTHONUNBUFFERED=1 | uv run python $ProjectFileDir$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py | uv (agi-cluster) |
| apps | flight get_distrib | $ProjectFileDir$/src/agilab/examples/flight/AGI_get_distrib_flight.py |  | $ProjectFileDir$/src/agilab/examples/flight | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/flight && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI_get_distrib_flight.py | uv (flight_project) |
| apps | flight install | $ProjectFileDir$/src/agilab/examples/flight/AGI_install_flight.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI_install_flight.py | uv (agi-cluster) |
| apps | flight run | $ProjectFileDir$/src/agilab/examples/flight/AGI_run_flight.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/examples/flight/AGI_run_flight.py | uv (flight_project) |
| apps | flight test manager | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_manager.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_manager.py | uv (flight_project) |
| apps | example_app get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py | uv (example_app_project) |
| apps | ilp get_distrib | $ProjectFileDir$/src/agilab/examples/ilp/AGI_get_distrib_ilp.py |  | $ProjectFileDir$/src/agilab/examples/ilp | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/ilp && uv run python $ProjectFileDir$/src/agilab/examples/ilp/AGI_get_distrib_ilp.py | uv (example_app_project) |
| apps | ilp install | $ProjectFileDir$/src/agilab/examples/ilp/AGI_install_ilp.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/ilp/AGI_install_ilp.py | uv (agi-cluster) |
| apps | ilp run | $ProjectFileDir$/src/agilab/examples/ilp/AGI_run_ilp.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/ilp/AGI_run_ilp.py | uv (example_app_project) |
| apps | ilp test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_ilp_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_ilp_manager.py | uv (example_app_project) |
| apps | example_app get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py | uv (example_app_project) |
| apps | mycode get_distrib | $ProjectFileDir$/src/agilab/examples/mycode/AGI_get_distrib_mycode.py |  | $ProjectFileDir$/src/agilab/examples/mycode | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/mycode && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI_get_distrib_mycode.py | uv (mycode_project) |
| apps | mycode install | $ProjectFileDir$/src/agilab/examples/mycode/AGI_install_mycode.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI_install_mycode.py | uv (agi-cluster) |
| apps | mycode run | $ProjectFileDir$/src/agilab/examples/mycode/AGI_run_mycode.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/examples/mycode/AGI_run_mycode.py | uv (mycode_project) |
| apps | mycode test manager | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_manager.py | uv (mycode_project) |
| apps | mycode tests | $ProjectFileDir$/src/agilab/apps/mycode_project/app_test.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/app_test.py | uv (mycode_project) |
| apps | example_app get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py | uv (example_app_project) |
| apps | example_app get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py | uv (example_app_project) |
| apps | example_app get_distrib | $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py |  | $ProjectFileDir$/src/agilab/examples/example_app | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/examples/example_app && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_get_distrib_example_app.py | uv (example_app_project) |
| apps | example_app install | $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py |  | $ProjectFileDir$ | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$ && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_install_example_app.py | uv (agi-cluster) |
| apps | example_app run | $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/examples/example_app/AGI_run_example_app.py | uv (example_app_project) |
| apps | example_app test manager | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_app_manager.py | uv (example_app_project) |
| components | flight call worker | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_call_worker.py | uv (flight_project) |
| components | flight test worker | $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_worker.py |  | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $ProjectFileDir$/src/agilab/apps/flight_project/test/_test_flight_worker.py | uv (flight_worker) |
| components | flight_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | uv (flight_project) |
| components | flight_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | $USER_HOME$/wenv/flight_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/flight_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | uv (flight_worker) |
| components | flight_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/flight_project $USER_HOME$/data/flight | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/flight_project $USER_HOME$/data/flight | uv (flight_worker) |
| components | flight_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | $ProjectFileDir$/src/agilab/apps/flight_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/flight_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | uv (flight_project) |
| components | example_app call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | example_app test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | example_app_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| components | example_app_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | example_app_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | uv (example_worker) |
| components | example_app_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
| components | ilp call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | ilp test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | ilp_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| components | ilp_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | ilp_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/ilp | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/ilp | uv (example_worker) |
| components | ilp_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
| components | example_app call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | example_app test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | example_app_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| components | example_app_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | example_app_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | uv (example_worker) |
| components | example_app_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
| components | mycode call worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_call_worker.py | uv (mycode_project) |
| components | mycode test worker | $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py |  | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $ProjectFileDir$/src/agilab/apps/mycode_project/test/_test_mycode_worker.py | uv (mycode_worker) |
| components | mycode_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | uv (mycode_project) |
| components | mycode_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/mycode_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | $USER_HOME$/wenv/mycode_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/mycode_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/mycode_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | uv (mycode_worker) |
| components | mycode_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/mycode_project $USER_HOME$/data/mycode | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/mycode_project $USER_HOME$/data/mycode | uv (mycode_worker) |
| components | mycode_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/mycode_worker/src/mycode_worker/mycode_worker.py | $ProjectFileDir$/src/agilab/apps/mycode_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/mycode_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/mycode_worker/src/mycode_worker/mycode_worker.py | uv (mycode_project) |
| components | example_app call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | example_app test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | example_app_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| components | example_app_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | example_app_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | uv (example_worker) |
| components | example_app_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
| components | example_app call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | example_app test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | example_app_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| components | example_app_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | example_app_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | uv (example_worker) |
| components | example_app_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
| components | example_app call worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_call_worker.py | uv (example_app_project) |
| components | example_app test worker | $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py |  | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $ProjectFileDir$/src/agilab/apps/example_app_project/test/_test_example_worker.py | uv (example_worker) |
| components | example_app_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/example_app_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/example_worker | uv (example_app_project) |
| components | example_app_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | $USER_HOME$/wenv/example_worker | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/example_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/example_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/example_worker | uv (example_worker) |
| components | example_app_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $ProjectFileDir$/src/agilab/apps/example_app_project $USER_HOME$/data/example_app | uv (example_worker) |
| components | example_app_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | $ProjectFileDir$/src/agilab/apps/example_app_project | PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $ProjectFileDir$/src/agilab/apps/example_app_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/example_worker/src/example_worker/example_worker.py | uv (example_app_project) |
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
- To update docs locally: run `docs/gen_docs.sh`. It builds via Sphinx when a config is present, or syncs `src/agilab/resources/help/` into `docs/html` and ensures an index.
- The Pages workflow only falls back to copying from `src/agilab/resources/help/` if `docs/html` is empty.
- Sphinx docs in agilab-apps: from that repo, run `uv run --group sphinx --dev docs/gen-docs.py`. If a sibling `agilab` checkout is present, the generator writes directly to `../agilab/docs/html/`; otherwise it builds into `docs/html/` in `agilab-apps`.

**Docs Tooling Details**
- Diagrams: agilab-apps's generator produces UML via `pyreverse` and Graphviz into `docs/source/diagrams` and includes them in Sphinx output.
- License reports: agilab-apps's generator runs `licensecheck` and writes `*-licenses.md` pages under `docs/source` (one per module), included in the build.
- Stubs: agilab's `docs/gen_docs.sh` generates lightweight `.pyi` stubs under `docs/stubs` for API surfacing in docs.
- Prerequisites: Graphviz (`dot`) must be installed on the system for diagrams.
  - macOS: `brew install graphviz`
  - Ubuntu/Debian: `sudo apt-get update && sudo apt-get install -y graphviz`
- Troubleshooting:
  - Missing Python deps (e.g., `tomlkit`, `licensecheck`): run with `uv run --group sphinx --dev docs/gen-docs.py` from agilab-apps.
  - Missing `dot`: install Graphviz (see above) and ensure `dot` is on PATH.

**CI & Badges**
- Tests run in a dedicated `ci` workflow; README badges reference the GH Actions status badge.
- Coverage uploads to Codecov for public reporting; README includes a Codecov badge. No Codecov token required for public repos.

**Tagging**
- Git tags now use a date-based scheme in UTC: `YYYY.MM.DD` (e.g., `2025.10.08`).
- If multiple tags are created on the same day, a numeric suffix is appended (e.g., `2025.10.08-2`).
- Package versions are independent and continue to follow PEP 440.

**Publishing to PyPI/TestPyPI**
- Use the Python script directly or the PyCharm run configuration:
  - CLI (dry run): `uv run python tools/pypi_publish.py --repo testpypi --dry-run`
  - CLI (TestPyPI): `uv run python tools/pypi_publish.py --repo testpypi`
- CLI (PyPI): `uv run python tools/pypi_publish.py --repo pypi`
- PyCharm: run configurations “publish dry-run (testpypi)”, “testpypi publish”, “pypi publish”.
- PyPI direct (no IDE): `uv run tools/pypi_publish.py --repo pypi --purge-after --username "<pypi-user>" --password "<pypi-pass>" --git-commit-version --retries 2` (expects `~/.pypirc` to mirror the current repo content so token-based logins keep working).
- Cleanup-only (with OTP prompt): `uv run tools/pypi_publish.py --repo pypi --cleanup-only --username "<pypi-user>" --password "<pypi-pass>"` and enter the 2FA code when PyPI asks.
- Developer refresh tip: after merging or bumping package code, run `uv tool update agilab agi-env agi-node agi-core agi-cluster` so `uvx` pulls the latest CLI entry points.
- Options: `--leave-most-recent`, `--skip-cleanup`, `--cleanup-timeout N`, `--cleanup username:password`, `--twine-username __token__`, `--twine-password`, `--yank-previous`.
- Cleanup defaults: TestPyPI cleanup is skipped automatically (avoids interactive web login/timeouts). To run cleanup, provide `--cleanup username:password` (or set `PYPI_USERNAME`/`PYPI_CLEANUP_PASSWORD` / configure `~/.pypirc`). The script reads the username from `~/.pypirc` when available.

## Progressive test plan

### Tier A — Quick checks (fast sanity)
- UI smoke: `cd $ProjectFileDir$ && uv run streamlit run src/agilab/AGILAB.py -- --openai-api-key "your-key" --apps-dir src/agilab/apps` (agilab run dev)
- Dependencies: `cd $ProjectFileDir$ && uv run python tools/show_dependencies.py --repo testpypi`
- App skeleton: `uv run python src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py`

### Tier B — Component/app flows
- Flight: run → test manager/worker → distribute → call → pre/postinstall
  - `cd src/agilab/apps/flight_project && uv run python ../../examples/flight/AGI_run_flight.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_flight_manager.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_flight_worker.py`
  - `cd src/agilab/examples/flight && uv run python AGI_get_distrib_flight.py`
  - `cd src/agilab/apps/flight_project && uv run python test/_test_call_worker.py`
  - `cd src/agilab/apps/flight_project && uv run python ../../core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py`
  - `cd src/agilab/apps/flight_project && uv run python ../../core/agi-node/src/agi_node/agi_dispatcher/post_install.py src/agilab/apps/flight_project $USER_HOME$/data/flight`
- Link model:
  - `cd src/agilab/apps/example_app_project && uv run python ../../examples/example_app/AGI_run_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_app_manager.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_worker.py`
  - `cd src/agilab/examples/example_app && uv run python AGI_get_distrib_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_call_worker.py`
- MyCode:
  - `cd src/agilab/apps/mycode_project && uv run python ../../examples/mycode/AGI_run_mycode.py`
  - `cd src/agilab/apps/mycode_project && uv run python test/_test_mycode_manager.py`
  - `cd src/agilab/apps/mycode_project && uv run python test/_test_mycode_worker.py`
  - `cd src/agilab/examples/mycode && uv run python AGI_get_distrib_mycode.py`
  - `cd src/agilab/apps/mycode_project && uv run python test/_test_call_worker.py`
- Example App:
  - `cd src/agilab/apps/example_app_project && uv run python ../../examples/example_app/AGI_run_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_app_manager.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_worker.py`
  - `cd src/agilab/examples/example_app && uv run python AGI_get_distrib_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_call_worker.py`
- Sb3Trainer:
  - `cd src/agilab/apps/example_app_project && uv run python ../../examples/example_app/AGI_run_example_app.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_app_manager.py`
  - `cd src/agilab/apps/example_app_project && uv run python test/_test_example_worker.py`
  - `cd src/agilab/examples/example_app && uv run python AGI_get_distrib_example_app.py`
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

- Do **not** add `agi-env` or `agi-node` back into `apps/example_app_project/pyproject.toml`. They were intentionally removed from the dependency list.

### Regenerate run configs (step-by-step)

1. Update templates (if needed)
   - Edit `pycharm/app_scripts/_template_app_*.xml` to reflect new script names/paths (e.g., `AGI_get_distrib_*`).

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
   - `uv run python tools/refresh_launch_matrix.py --inplace`

6) Rebuild the CLI wrappers
   - `uv run python tools/generate_runconfig_scripts.py`

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

This repository uses Codex CLI for local agent development. Follow these notes when working as an agent in this project.

## Codex CLI Quickstart

- Start app development after an initial creation via EXECUTE project clone using:
  - `codex --full-access -a never -m codex-medium`
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
