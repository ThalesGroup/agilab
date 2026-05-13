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
- **High-frequency command shortcuts**: Use `./dev <shortcut>` for repeated local validation loops.
  The top shortcuts are `impact` for impact validation, `bugfix` for impact plus a fast
  GA-selected regression run, `test` for targeted `pytest -q`,
  `regress` for GA-selected fast regression subsets, `flow` for one or more workflow parity
  profiles, `release` for local pre-tag release guards, `badge` for the explicit release/pre-release
  coverage-badge guard, and `docs` for docs mirror sync plus stamp verification. `impact` tells you what must be validated, `test` runs the
  narrow pytest slice, `bugfix` is the default low-load pre-push loop for normal code fixes,
  `regress` optimizes a likely regression subset from changed files and optional JUnit timings,
  `flow` matches local GitHub workflow profiles, `release` checks impact, generated PyPI release
  plan, trusted-publisher contract, dependency policy, strict typing, docs, and badges before a tag,
  `badge` checks badge freshness when intentionally requested, and `docs` keeps the public mirror
  aligned. Use `--print-only` to audit the expanded commands.
- **Upgrade packaged tools first**: Before launching the published CLI with `uvx
  agilab`, run `uv --preview-features extra-build-dependencies tool install --upgrade agilab` to install or pick up the latest wheel.
- **No repo uvx**: Reserve `uvx` for packaged installs outside this checkout. Launching
  it from the source tree swaps in the published wheel and discards your local changes.
- **Process ownership**: Treat existing terminals, Codex CLI sessions, dev servers, and
  other long-running processes as user-owned unless this turn started them. Do not use
  broad termination commands such as `pkill`, `killall`, `pkill -f`, or port-based
  `kill` pipelines that can match unrelated sessions. Stop only verified PIDs or tool
  sessions created for the active task. Do not use Codex CLI control shortcuts such as
  `/stop`, Esc interruption, or terminal-close actions to manage background terminals
  unless the terminal/session was created by this active task and its identity is
  verified. A status banner that says a background terminal is running is not ownership
  proof. If a port is busy, choose another port or ask before stopping its owner; do
  not try to "pause" another Codex CLI session from here.
- **Git footprint helper**: Use `uv run python tools/repo_footprint.py audit` to
  separate working-tree size from `.git` size before cleaning anything. Prefer
  `lfs-prune --dry-run` / `lfs-prune --apply` for local `.git/lfs` cleanup.
  For true history reduction, use `history-rewrite` in its isolated mirror flow,
  then `realign-local` on the checkout you keep working in.
- **Local-first validation**: Do not trigger GitHub workflows when the same failure can be
  reproduced or validated locally. First run the narrowest local check that can prove the change:
  targeted `pytest`, isolated coverage commands, `py_compile`, Sphinx builds, and release dry-runs.
  Reserve coverage badge generation for release/pre-release validation or badge tooling changes.
  Reserve CI/workflow runs for GitHub-only behavior (runner differences,
  OS/Python matrix coverage, permissions/secrets, Pages/PyPI publication, or final integration
  confirmation after local validation). When a change maps cleanly to one of the repo workflow
  profiles, prefer `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile <name>`
  over handwritten command variants.
- **Repository update command plan**: When the user asks to "update repos", "sync repos", or similar,
  first show the exact command plan as a fenced `bash` block with concrete `git -C <repo>` commands
  for each checkout. Use the fast path by default: `status --porcelain=v1 --untracked-files=no`,
  `fetch --prune`, `rev-list --left-right --count HEAD...@{u}`, then `merge --ff-only @{u}` only
  for repos that are actually behind. This avoids a redundant fetch from `git pull` and avoids slow
  untracked scans. Group independent repo checks and fetches in parallel when the tooling allows it.
  If a checkout has tracked dirty paths, do not merge it until the dirty paths are reported and the
  update plan is adjusted.
- **Shared-core strict typing**: Use `uv --preview-features extra-build-dependencies run --with mypy python tools/shared_core_strict_typing.py`
  for the curated extracted support-module strict slice. The same check is also available through
  `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile shared-core-typing`.
- **Dependency policy gate**: Use
  `uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile dependency-policy`
  to verify runtime dependency hygiene, especially before release or when editing `pyproject.toml` files.
- **PyPI release cleanup**: Use `tools/pypi_publish.py --delete-pypi-release <version>` only when a specific
  old PyPI version must be removed from the selected packages. This uses an exact `pypi-cleanup --version-regex`
  match, requires real PyPI web-login credentials in `[pypi_cleanup]`, and cannot use API tokens or trusted
  publishing credentials.
- **Impact triage first**: For non-trivial diffs, run `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged`
  before edits or push. Use its output to decide whether the change is app-local vs shared-core,
  which targeted tests are required, whether install repros are mandatory, and whether generated
  artifacts such as skill indexes or run-config wrappers must be refreshed. Coverage badges are normally
  refreshed only for release/pre-release validation or badge tooling changes.
- **Local pre-push guardrails**: Keep the repo hook enabled with
  `git config core.hooksPath .githooks`. The pre-push hook first classifies the pushed
  changed files with `tools/pre_push_changed_files.py`. It runs docs mirror checks only when
  docs mirror inputs changed, and release-proof checks only when release-proof inputs changed.
  If classification fails, it fails safe by running all local guards. Coverage badge freshness is
  intentionally not part of the default bugfix pre-push path; run `./dev badge` or the `badges`
  workflow parity profile before release/pre-release publication. Bypass only with
  `AGILAB_SKIP_LOCAL_GUARDS=1` when the skipped
  guard is intentional and documented.
- **Run config parity**: After touching `.idea/runConfigurations/*.xml`, regenerate
  the CLI wrappers with `uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py` and commit
  the results (`tools/run_configs/`).
- **PyCharm source-root switching**: The global JetBrains SDK named `uv (agilab)` is bound
  to one AGILAB source checkout at a time. To intentionally switch PyCharm execution to
  another checkout, run from the target checkout:
  `uv sync` then
  `AGILAB_PYCHARM_ALLOW_SDK_REBIND=1 uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py`.
  Without the override, `setup_pycharm.py` must refuse cross-checkout rebinding so a run
  cannot silently execute `/path/A/src/agilab/main_page.py` with `/path/B/.venv`.
  Rerun full `install.sh` only when you also need installer side effects such as app
  installation, `.agilab-path` updates, dataset seeding, or install-time tests.
- **VS Code parity**: If you work from VS Code, regenerate local tasks and debug launches from the same
  `.idea/runConfigurations/*.xml` source with
  `uv --preview-features extra-build-dependencies run python tools/generate_vscode_tasks.py`.
  This writes `.vscode/tasks.json` and `.vscode/launch.json` locally. Do not commit `.vscode/`; it remains ignored.
  The generated tasks keep the exact `uv` entrypoints. The generated launches map Python/pytest configs to VS Code
  `debugpy`, so select the matching interpreter/environment in VS Code before debugging.
- **Model compatibility**: When working with GPT-5 Codex agents, confirm no new code
  calls deprecated Streamlit APIs like `st.experimental_rerun()`. Always migrate to
  `st.rerun` before merging.
- **CLI agent helpers**: Repo-scoped wrappers and configs exist for Codex, Aider, and
  OpenCode under `tools/*_workflow.*`, `.aider.conf.yml`, `opencode.json`, and
  `.opencode/agents/`. Keep them aligned with repo guardrails when workflow policy changes.
- **Streamlit form state**: In custom `app_args_form.py` pages, initialize editable widgets
  from persisted values (`defaults_model` / stored args). Only derive companion paths such as
  `data_out` from `data_in` when the stored value is actually missing. Do not silently replace
  an explicit saved value with a recomputed default on render; if a field is intentionally derived,
  make that dependency explicit in the UI instead of presenting it as a normal independent input.
- **Bug-class sweep**: When fixing a bug, check whether the same class of bug exists elsewhere in
  the codebase, especially in sibling apps, mirrored forms, shared helpers, or duplicated logic.
  If it does, either fix the related instances in the same change or clearly document why they are
  being left out.
- **User-facing rename sweep**: When changing a visible app/page/demo name, title, or major label,
  update the paired tests, README/docs text, and capture scripts in the same change. Grep for both
  the old and new wording before closing the task. When a page title is asserted by tests, prefer a
  small side-effect-free metadata module (for example `page_meta.py`) so the page and tests do not
  drift on duplicated strings.
- **Deterministic filesystem behavior**: Never rely on implicit filesystem iteration order
  (`glob`, `rglob`, `iterdir`, `os.scandir`) in runtime code or tests. If order matters to users,
  sort in the implementation. If order is not part of the contract, assert on sorted values or sets
  in tests.
- **Shared core approval gate**: Do not edit shared core technology without explicit user approval first.
  Shared core includes `src/agilab/core/agi-env`, `src/agilab/core/agi-node`, `src/agilab/core/agi-cluster`,
  `src/agilab/core/agi-core`, shared installer/build/deploy tooling, and generic helpers reused across apps/pages.
  Default to app-local fixes first. If you believe a core change is required, stop and explain:
  - why an app-local fix is insufficient
  - which shared files/modules need to change
  - the expected blast radius across apps/workflows
  - the test or regression plan you will use after approval
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
- **Installer solver drift triage**: If `uv sync --project <app>` succeeds in a plain shell but the AGILAB install path
  fails later in worker deployment with an unsatisfiable dependency conflict, inspect the copied worker manifest under
  `~/wenv/<app>_worker/pyproject.toml` before patching the app. This usually means shared install plumbing rewrote the
  worker project or resolved local core packages inconsistently. Check in order:
  - run `uv --preview-features extra-build-dependencies run python tools/install_contract_check.py --app-path <app-project-path> --worker-copy ~/wenv/<app>_worker` and inspect its classification first
  - whether `AgiEnv._build_env()` is leaking `UV_RUN_RECURSION_DEPTH` into nested `uv` commands
  - whether `_deploy_local_worker()` appended an exact dependency pin into the copied worker `pyproject.toml`
  - whether local source installs are adding `agi-env` and `agi-node` together as local paths, not one by one from index metadata
  - whether `read_agilab_path()` is empty, causing a source checkout app to be treated like a generated install artifact
  For this bug class, compare the source app manifest with `~/wenv/<app>_worker/pyproject.toml`; if the worker copy gained
  a conflicting exact pin (for example a stray `scipy==...`), treat it as a shared-core install bug first, not an app-only bug.
- **Diagnostic challenge pattern**: When another agent already produced a diagnosis, do not stop at “confirm or deny”.
  First assess the quality of the diagnostic, identify any weak assumptions or missing coverage, then explicitly look for
  a better fix than the obvious one. Keep the plain repro command as the first discriminator, compare app-local and
  shared-core fixes, and explain why the stronger fix is better. Good one-query wording:
  `Assess the diagnostic below and find the better fix. Keep the plain repro as the first discriminator. Identify the real root cause, regression chain, weak points in the current diagnosis, the better fix, why it is better than the obvious fix, and the regression plan.`
- **Dependency removal audit**: When removing a dependency from code, check the impact on the corresponding
  `pyproject.toml` files as part of the same change. Remove stale declarations when they are no longer needed,
  or keep them only when there is a clear runtime, packaging, or optional-feature reason.
- **Installer flags**: For automation, set `CLUSTER_CREDENTIALS` / `OPENAI_API_KEY` in the
  environment, then use `./install.sh --non-interactive`/`-y`. Optional flags:
  `--apps-repository`, `--install-path`, `--install-apps [all|builtin|comma list]`,
  `--test-apps`, `--test-core`.
- **Apps repository symlinks**: Set `APPS_REPOSITORY` in
  `~/.local/share/agilab/.env` to the path of your apps repository checkout. The installer can
  create symlinks so optional apps/pages resolve without manual action.
- **Built-in apps directory**: First-party apps such as `flight_project` and `mycode_project` now live under
  `src/agilab/apps/builtin/`. Update local commands accordingly; repository apps cloned via `install_apps.sh`
  still appear under `src/agilab/apps/`.
- **Clone environment policy**: In the PROJECT page, treat clones in two classes:
  - `Temporary clone`: may share the source `.venv` by symlink for lightweight local experiments.
  - `Working clone`: should not keep a shared `.venv`; create it without `.venv` and rerun `INSTALL` before `EXECUTE`.
  When renaming a project, preserve the existing `.venv` rather than leaving a symlink pointing to the old project path.
- **App repository updates over legacy aliases**: Existing maintained apps live in the apps repository.
  Prefer updating the app repository source and rerunning the installer over adding compatibility
  aliases to paper over stale local copies. When a repository app/page already exists locally as a
  real directory, the installer moves it aside and links the repository copy so future app updates
  are picked up.
- **Flight dependencies**: Follow the project’s own metadata for Streamlit/matplotlib/OpenAI—no extra
  trimming beyond the flight worker manifest.
- **Runtime isolation**: Anything launched from `~/agi-space` must assume the upstream
  source checkout is absent. Agents can only reference packaged assets inside the
  virtual environment—never repository-relative paths.
- **App settings workspace**: `src/.../app_settings.toml` is now a versioned seed only.
  Mutable per-user settings live under `~/.agilab/apps/<app>/app_settings.toml`, and
  the UI reads/writes that workspace copy.
- **Test environment isolation**: Root tests under `test/` must not depend on the developer machine
  or GitHub runner home state. Assume `HOME`, `~/.agilab/.env`, cluster env vars, and
  `APPS_REPOSITORY` may be polluted; use shared fixtures or explicit monkeypatching to force a clean
  environment.
- **Cluster fail-fast contract**: If cluster mode is requested, require an explicit, usable cluster
  share that is distinct from local share. Do not silently degrade to `localshare`, and keep
  regressions for that fail-fast behavior.
- **Config preservation**: Run `tools/preserve_app_configs.sh lock` to keep local edits
  to any `app_args_form.py` or `pre_prompt.json` under `src/agilab/apps/` out of
  commits and pushes. Invoke `unlock` when you intentionally want to share updates.
- **Model defaults**: `agi_env.defaults` centralises the fallback OpenAI model. Set
  `AGILAB_DEFAULT_OPENAI_MODEL` to override globally without editing code; individual
  runs can still pass `OPENAI_MODEL`.
- **Skill placement guardrail**: Repo-managed skills under `.claude/skills/` and
  `.codex/skills/` must stay AGILAB-specific, cross-repo reusable for AGILAB work,
  or directly support this repository’s workflows. Personal skills or skills for
  non-AGILAB domains such as private CV editing belong in `~/.codex/skills/` or
  the relevant private repo, not in this public repo.
- **Service health gates**: For service mode projects, persist SLA thresholds in
  `[cluster.service_health]` in each app `app_settings.toml`:
  - `allow_idle` (bool)
  - `max_unhealthy` (int)
  - `max_restart_rate` (float, `0.0` to `1.0`)
  Use `tools/service_health_check.py` for CLI checks (`--format json|prometheus`).
- **History metadata**: `lab_stages.toml` now records an `M` field for each step so the
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
- **Docs source of truth**: Editable docs sources live in the sibling docs
  checkout `../thales_agilab/docs/source` relative to the active AGILAB checkout. Treat
  `docs/source` in this repo as a managed public mirror, not as a second
  authoring tree.
- **Docs mirror sync**: Refresh the public mirror with
  `uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --apply --delete`
  after canonical docs edits. Use the same command without `--apply` as a drift
  check.
- **Docs mirror stamp**: `docs/.docs_source_mirror_stamp.json` is the guardrail
  for the managed public mirror. Do not edit it by hand. Refresh it through
  `tools/sync_docs_source.py --apply --delete`, or CI and Pages publication will
  fail on a mirror integrity mismatch.
- **Docs edits**: `docs/html` in this repo is generated local output and is ignored by
  git. Do not treat `docs/html/_sources/*.txt` as editable source files. Edit docs in
  `../thales_agilab/docs/source`, then sync the mirror into `docs/source`.
- **Docs guardrail**: Never stage or commit `docs/html/**`. If generated files appear in
  status, unstage/remove them from the index and keep only source edits.
- **VIRTUAL_ENV warning**: AGILAB-managed PyCharm configs and launch wrappers clear
  `VIRTUAL_ENV` before invoking `uv`, because AGILAB intentionally selects the target
  project `.venv` instead of a stale activated shell. If a direct `uv` command still
  emits `VIRTUAL_ENV=... does not match the project environment path ...; use --active...`,
  unset `VIRTUAL_ENV` or use the matching `tools/run_configs` wrapper. Do not add
  `--active` unless you intentionally want to run against the currently activated venv.

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
3. Regenerate local VS Code tasks and launches when needed:
   `uv --preview-features extra-build-dependencies run python tools/generate_vscode_tasks.py`.
4. Verify the generated scripts under `tools/run_configs/` and commit the changes.
5. Update the launch matrix in this document when new configs appear.

### 2. Launch flows
- **PyCharm (recommended)**: Use the run configurations defined in the launch matrix.
- **VS Code**: Run `uv --preview-features extra-build-dependencies run python tools/generate_vscode_tasks.py`
  to materialize `.vscode/tasks.json` and `.vscode/launch.json`. Use `Run Task` for the exact `uv` wrapper parity,
  or use `Run and Debug` after selecting the matching Python interpreter for `debugpy`.
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

### 3b. Diff impact triage
1. Run `uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged`
   for staged work, or pass explicit files with `--files ...` when you want to inspect a planned edit
   before touching the tree.
2. Treat `shared-core` and `installer` findings as hard gates:
   - stop for explicit approval if shared core is implicated
   - reproduce both plain `uv sync --project <app>` and `uv run python src/agilab/apps/install.py <app> --verbose 1`
     when install plumbing is implicated
3. Execute the suggested targeted tests before broader suites.
4. Refresh any required generated artifacts in the same change:
   - `tools/run_configs/` after run configuration edits
   - `.codex/skills/.generated/skills_index.*` after shared skill edits
   - `badges/coverage-*.svg` only for release/pre-release coverage validation or badge tooling changes

### 4. Cluster SSH recovery after node reinstall or host-key rotation

Use this when a cluster node such as `192.168.20.130` was reinstalled, got a new SSH host key,
or lost its `~/.ssh` state.

1. Verify the new host key fingerprint out of band before trusting it.
2. Remove the stale host key locally, then register the new one:
   ```bash
   ssh-keygen -R 192.168.20.130
   ssh-keyscan -H -t ed25519 192.168.20.130 >> ~/.ssh/known_hosts
   ssh-keygen -F 192.168.20.130 -f ~/.ssh/known_hosts
   ```
3. Re-bootstrap user auth on the remote node. Preferred path: copy the manager public key:
   ```bash
   worker_user="<worker-user>"
   ssh-copy-id "$worker_user@192.168.20.130"
   ```
   If `ssh-copy-id` is unavailable, append the public key manually on the remote:
   ```bash
   mkdir -p ~/.ssh
   chmod 700 ~/.ssh
   printf '%s\n' '<contents of ~/.ssh/id_ed25519.pub>' >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```
4. If public-key auth still fails, confirm the remote SSH daemon allows it:
   ```bash
   grep -E '^(PubkeyAuthentication|PasswordAuthentication)' /etc/ssh/sshd_config
   ```
   Expected: `PubkeyAuthentication yes`. Password auth can stay enabled as a bootstrap fallback only.
5. Verify access before rerunning AGILAB:
   ```bash
   worker_user="<worker-user>"
   ssh "$worker_user@192.168.20.130" 'echo ok'
   ```
6. Recreate cluster-share prerequisites on the reinstalled Linux node:
   ```bash
   worker_user="<worker-user>"
   worker_home="/home/$worker_user"
   mkdir -p "$worker_home/.agilab" "$worker_home/clustershare" "$worker_home/localshare"
   cat > "$worker_home/.agilab/.env" <<EOF
   AGI_CLUSTER_SHARE=$worker_home/clustershare
   AGI_LOCAL_SHARE=$worker_home/localshare
   EOF
   ```
7. Remount shared cluster storage if this cluster uses SSHFS from `.111` to `.130`:
   ```bash
   worker_user="<worker-user>"
   manager_user="<manager-user>"
   worker_home="/home/$worker_user"
   manager_share="/path/to/manager/clustershare"
   sudo apt-get update && sudo apt-get install -y sshfs
   mkdir -p "$worker_home/clustershare"
   sshfs "$manager_user@192.168.20.111:$manager_share" "$worker_home/clustershare"
   mount | grep clustershare
   ```
8. Verify the node can still reach the scheduler/manager peer non-interactively:
   ```bash
   worker_user="<worker-user>"
   manager_user="<manager-user>"
   ssh "$worker_user@192.168.20.130" "ssh -o BatchMode=yes $manager_user@192.168.20.111 hostname"
   ```
9. Only after these SSH and share checks pass, rerun `AGI.install(...)` / cluster pipelines.

### 4b. macOS SSHFS cluster-share recovery

Use this when `agilab doctor --setup-share sshfs --apply` fails before the
sentinel check on a macOS worker.

1. Check the real remote state from a non-interactive SSH command:
   ```bash
   worker_user="<worker-user>"
   worker_ip="<worker-ip>"
   ssh "$worker_user@$worker_ip" 'printf "path=%s\n" "$PATH"; command -v sshfs || true; /usr/local/Homebrew/bin/brew --version 2>/dev/null | head -1 || true'
   ```
2. On older Intel macOS hosts, Homebrew may exist at `/usr/local/Homebrew/bin/brew`
   even when `command -v brew` is empty. Use that explicit path before assuming
   no package manager exists.
3. Prefer a normal interactive install of FUSE-T SSHFS or macFUSE plus SSHFS:
   ```bash
   worker_user="<worker-user>"
   worker_ip="<worker-ip>"
   ssh -t "$worker_user@$worker_ip" 'HOMEBREW_NO_AUTO_UPDATE=1 /usr/local/Homebrew/bin/brew install macos-fuse-t/homebrew-cask/fuse-t-sshfs'
   ```
   This can require an admin password because it installs a package.
4. Ensure `sshfs` is visible to non-interactive zsh. If it is installed under
   `/usr/local/bin` but remote SSH still cannot find it, add a minimal
   `~/.zshenv` PATH entry for that user:
   ```bash
   case ":$PATH:" in
     *:/usr/local/bin:*) ;;
     *) export PATH="/usr/local/bin:$PATH" ;;
   esac
   ```
5. Validate reverse SSH from worker to scheduler/manager. SSHFS mounts are
   created on the worker, so the worker must authenticate back to the scheduler
   account used in the mount source:
   ```bash
   worker_user="<worker-user>"
   worker_ip="<worker-ip>"
   manager_user="<manager-user>"
   manager_ip="<manager-ip>"
   ssh "$worker_user@$worker_ip" "ssh -o BatchMode=yes $manager_user@$manager_ip hostname"
   ```
6. If reverse SSH fails with a host-key error, refresh the manager key on the
   worker. If it fails with `Permission denied`, add the worker public key to
   the manager account’s `~/.ssh/authorized_keys`.
7. Rerun the narrow gate before any full cluster validation:
   ```bash
   manager_ip="<manager-ip>"
   worker_user="<worker-user>"
   worker_ip="<worker-ip>"
   local_shared_path="/path/to/local/shared/path"
   remote_mount_path="/path/to/remote/mount/path"
   uv --preview-features extra-build-dependencies run agilab doctor \
     --cluster \
     --scheduler "$manager_ip" \
     --workers "$worker_user@$worker_ip" \
     --cluster-share "$local_shared_path" \
     --remote-cluster-share "$remote_mount_path" \
     --share-check-only
   ```

<details>
<summary><strong>Launch matrix (auto-sorted from .idea/runConfigurations)</strong></summary>

| Group | Config name | Entry | Args | Workdir | Env | How to run | Interpreter |
|---|---|---|---|---|---|---|---|
| agilab | agilab run (dev) | streamlit | run $PROJECT_DIR$/src/agilab/main_page.py -- --openai-api-key "your-key" --apps-path $PROJECT_DIR$/src/agilab/apps | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1;IS_SOURCE_ENV=1 | cd $PROJECT_DIR$ && uv run streamlit run $PROJECT_DIR$/src/agilab/main_page.py -- --openai-api-key "your-key" --apps-path $PROJECT_DIR$/src/agilab/apps | Project/module SDK |
| agilab | agilab run (enduser) | streamlit | run .venv/lib/python3.13/site-packages/agilab/main_page.py -- --openai-api-key "your-key" | $PROJECT_DIR$/../agi-space | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$/../agi-space && uv run streamlit run .venv/lib/python3.13/site-packages/agilab/main_page.py -- --openai-api-key "your-key" | uv (agi-space) |
| agilab | app_script gen | $PROJECT_DIR$/pycharm/gen_app_script.py | $Prompt:Enter app manager name:flight$ |  | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $PROJECT_DIR$/pycharm/gen_app_script.py $Prompt:Enter app manager name:flight$ | uv (agi-cluster) |
| agilab | apps-pages launcher | $PROJECT_DIR$/tools/apps_pages_launcher.py | --active-app $PROJECT_DIR$/src/agilab/apps/builtin/flight_project | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $PROJECT_DIR$/tools/apps_pages_launcher.py --active-app $PROJECT_DIR$/src/agilab/apps/builtin/flight_project | uv (agilab) |
| agilab | apps-pages smoke | $PROJECT_DIR$/tools/smoke_preinit.py | --active-app $PROJECT_DIR$/src/agilab/apps/builtin/flight_project --timeout 20 | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $PROJECT_DIR$/tools/smoke_preinit.py --active-app $PROJECT_DIR$/src/agilab/apps/builtin/flight_project --timeout 20 | uv (agilab) |
| agilab | builtin/flight get_distrib | $USER_HOME$/log/execute/flight/AGI_get_flight.py |  | $USER_HOME$/log/execute/builtin/flight | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/log/execute/builtin/flight && uv run python $USER_HOME$/log/execute/flight/AGI_get_flight.py | uv (flight_project) |
| agilab | builtin/flight install | $USER_HOME$/log/execute/flight/AGI_install_flight.py |  | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $USER_HOME$/log/execute/flight/AGI_install_flight.py | uv (agi-cluster) |
| agilab | builtin/mycode get_distrib | $USER_HOME$/log/execute/mycode/AGI_get_mycode.py |  | $USER_HOME$/log/execute/builtin/mycode | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/log/execute/builtin/mycode && uv run python $USER_HOME$/log/execute/mycode/AGI_get_mycode.py | uv (mycode_project) |
| agilab | builtin/mycode install | $USER_HOME$/log/execute/mycode/AGI_install_mycode.py |  | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $USER_HOME$/log/execute/mycode/AGI_install_mycode.py | uv (agi-cluster) |
| agilab | lab_run test | $PROJECT_DIR$/src/agilab/lab_run.py | --openai-api-key "your-key" | $USER_HOME$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$ && uv run python $PROJECT_DIR$/src/agilab/lab_run.py --openai-api-key "your-key" | uv (agilab) |
| agilab | publish dry-run (testpypi) | $PROJECT_DIR$/tools/pypi_publish.py | --repo testpypi --dry-run --verbose | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $PROJECT_DIR$/tools/pypi_publish.py --repo testpypi --dry-run --verbose | uv (agilab) |
| agilab | pypi publish | $PROJECT_DIR$/tools/pypi_publish.py | --repo pypi --verbose --git-tag --git-commit-version --git-reset-on-failure | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $PROJECT_DIR$/tools/pypi_publish.py --repo pypi --verbose --git-tag --git-commit-version --git-reset-on-failure | uv (agilab) |
| agilab | run ssh cmd | $PROJECT_DIR$/src/agilab/core/agi-env/test/_test_ssh_cmd.py |  |  | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | uv run python $PROJECT_DIR$/src/agilab/core/agi-env/test/_test_ssh_cmd.py | uv (agi-cluster) |
| agilab | show depencencies | $PROJECT_DIR$/tools/show_dependencies.py | --repo pypi | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $PROJECT_DIR$/tools/show_dependencies.py --repo pypi | uv (agilab) |
| agilab | test agi_distributor |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test agi_env |  |  | $PROJECT_DIR$/src/agilab/core/agi-env/test |  | cd $PROJECT_DIR$/src/agilab/core/agi-env/test && uv run python | uv (agi-env) |
| agilab | test base_worker |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | test dag_worker |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | test pandas_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test polars_worker |  |  | $PROJECT_DIR$/src/agilab/core/agi-cluster |  | cd $PROJECT_DIR$/src/agilab/core/agi-cluster && uv run python | uv (agi-cluster) |
| agilab | test pypi publish | $PROJECT_DIR$/tools/pypi_publish.py | --repo testpypi --verbose --git-reset-on-failure | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1 PYDEVD_USE_FRAME_EVAL=NO;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $PROJECT_DIR$/tools/pypi_publish.py --repo testpypi --verbose --git-reset-on-failure | uv (agilab) |
| agilab | test work_dispatcher |  |  |  |  | uv run python | uv (agi-cluster) |
| agilab | zip_all | $PROJECT_DIR$/tools/zip_all.py | --dir2zip $FilePrompt$ --follow-app-links --exclude-dir docs --exclude-dir codex | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $PROJECT_DIR$/tools/zip_all.py --dir2zip $FilePrompt$ --follow-app-links --exclude-dir docs --exclude-dir codex | uv (agilab) |
| apps | app install (local) | $PROJECT_DIR$/src/agilab/apps/install.py | $Prompt:selected app:src/agilab/apps/builtin/flight_project$ --install-type "1" --verbose 1 | $PROJECT_DIR$ | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$ && uv run python $PROJECT_DIR$/src/agilab/apps/install.py $Prompt:selected app:src/agilab/apps/builtin/flight_project$ --install-type "1" --verbose 1 | uv (agi-cluster) |
| apps | app-test | $PROJECT_DIR$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py |  |  | VIRTUAL_ENV=;PYTHONUNBUFFERED=1 | uv run python $PROJECT_DIR$/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py | uv (agi-cluster) |
| apps | builtin/flight run | $USER_HOME$/log/execute/flight/AGI_run_flight.py |  | $PROJECT_DIR$/src/agilab/apps/builtin/flight_project | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$/src/agilab/apps/builtin/flight_project && uv run python $USER_HOME$/log/execute/flight/AGI_run_flight.py | uv (flight_project) |
| apps | builtin/mycode run | $USER_HOME$/log/execute/mycode/AGI_run_mycode.py |  | $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project && uv run python $USER_HOME$/log/execute/mycode/AGI_run_mycode.py | uv (mycode_project) |
| components | builtin/flight_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/builtin/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | $PROJECT_DIR$/src/agilab/apps/builtin/flight_project | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$/src/agilab/apps/builtin/flight_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/builtin/flight_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/flight_worker | uv (flight_project) |
| components | builtin/flight_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | $USER_HOME$/wenv/flight_worker | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/flight_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/flight_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/flight_worker | uv (flight_worker) |
| components | builtin/flight_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $PROJECT_DIR$/src/agilab/apps/builtin/flight_project $USER_HOME$/data/builtin/flight | $PROJECT_DIR$/src/agilab/apps/builtin/flight_project | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$/src/agilab/apps/builtin/flight_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $PROJECT_DIR$/src/agilab/apps/builtin/flight_project $USER_HOME$/data/builtin/flight | uv (flight_worker) |
| components | builtin/flight_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | $PROJECT_DIR$/src/agilab/apps/builtin/flight_project | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$/src/agilab/apps/builtin/flight_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/flight_worker/src/flight_worker/flight_worker.py | uv (flight_project) |
| components | builtin/mycode_egg gen | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py | --app-path $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py --app-path $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" -d $USER_HOME$/wenv/mycode_worker | uv (mycode_project) |
| components | builtin/mycode_lib gen | agi_node.agi_dispatcher.build | --app-path $USER_HOME$/wenv/mycode_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | $USER_HOME$/wenv/mycode_worker | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $USER_HOME$/wenv/mycode_worker && uv run python agi_node.agi_dispatcher.build --app-path $USER_HOME$/wenv/mycode_worker build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" -b $USER_HOME$/wenv/mycode_worker | uv (mycode_worker) |
| components | builtin/mycode_postinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py | $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project $USER_HOME$/data/builtin/mycode | $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project $USER_HOME$/data/builtin/mycode | uv (mycode_worker) |
| components | builtin/mycode_preinstall test | $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py | remove_decorators --verbose --worker_path $USER_HOME$/wenv/mycode_worker/src/mycode_worker/mycode_worker.py | $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project | VIRTUAL_ENV=;PYTHONUNBUFFERED=1;UV_NO_SYNC=1 | cd $PROJECT_DIR$/src/agilab/apps/builtin/mycode_project && uv run python $PROJECT_DIR$/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path $USER_HOME$/wenv/mycode_worker/src/mycode_worker/mycode_worker.py | uv (mycode_project) |
</details>
