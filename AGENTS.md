# AGILab Agent Runbook

AGILab ships with a curated set of run configurations, CLI wrappers, and automation
scripts that let GPT-5 Codex and human operators work from the same playbook. This
document mirrors the Spec Kit style guide so every agent—manual or autonomous—follows
consistent launch, validation, and troubleshooting steps.

> **Agent MCP start here**: When using `agilab-mcp`, call `agent_quickstart`
> first. It is read-only and returns the safety boundary, recommended workflow,
> live tool list, and compact capability overview.

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
  `uv --preview-features extra-build-dependencies run --extra ui streamlit …` for source UI launches) so dependencies resolve inside the managed environments that
  ship with AGILab.
- **Command speed policy**: Use raw `rg`, `sed`, and small file reads for cheap local inspection where wrapper startup would dominate. Use `tokki run -- ...` for Git writes, pushes, merges, tests, builds, installs, network operations, long logs, slow/noisy commands, and any state-changing or policy-sensitive command.
- **High-frequency command shortcuts**: Use `./dev <shortcut>` for repeated
  local validation loops and `./dev --print-only <shortcut>` when you need the
  expanded command. Start with `scope`, `impact`, `test`, `lint`, `bugfix`,
  `regress`, `ui-flow`, `flow`, `docs`, `app-contracts`, `builtin-app-tests`,
  `release`, `badge`, `maintenance`, `memory`, `warnings`, `robust`,
  `parallel-stage`, `audit`, `task-worktree`, or `clean` as the task requires.
  Keep shortcut behavior in `./dev` and workflow references, not duplicated in
  this runbook. By default, `./dev` captures full logs under ignored
  `reports/dev-logs/`, prints compact signal summaries, and isolates `uv`
  subprocesses in `.venv-dev` so validation does not mutate a live Streamlit
  source environment. Use `--raw-output`, `AGILAB_DEV_OUTPUT=raw`, or
  `AGILAB_DEV_SUMMARY_LINES` only when a human or downstream tool needs more
  output.
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
- **Fix prevention close-out / Bug-class sweep contract**: For logged or
  reproducible failures, preserve the smallest
  repro first, identify the root cause, choose the right layer, and add the
  smallest regression, guard, robot scenario, or validation that would have
  caught it. Sweep only sibling apps, shared helpers, manifests, or generated
  artifacts that can plausibly share the same failure class. For browser-only
  failures, validate the browser/dev-log surface rather than stopping at unit
  tests or AppTest. For agent-process defects, add or tighten the durable rule in
  `AGENT_LEARNINGS.md`, `AGENTS.md`, a repo skill, or tooling. If automation is
  not practical, document why and name the closest manual or robot validation.
- **Streamlit duplicate-widget triage**: For duplicate element ID errors, first
  check whether the page, app surface, or entrypoint is being executed twice.
  Add stable widget keys for repeated controls, but do not mask duplicate
  rendering by adding keys when the real bug is a double `main()` call or a
  duplicated render path.
- **Visible-label cleanup contract**: When the user asks to remove visible UI
  text, search all render paths before closing the task: page files,
  `main_page.py`, `page_bootstrap.py`, `workflow_ui.py`,
  `page_project_selector.py`, lazy-import wrappers, CSS class names, and tests.
  Do not update tests to expect newly introduced clutter unless the user
  explicitly approves that clutter as product behavior. Add a negative
  regression assertion for removed text when practical.
- **Cross-page action semantics**: When adding or renaming visible UI actions,
  compare the label meaning across PROJECT, ORCHESTRATE, WORKFLOW, ANALYSIS,
  SETTINGS, sidebars, and robot click labels before closing the task. Do not
  reuse the same visible button text for different contracts across pages. Scope
  labels by object and layer, for example `Install agi-app` for package/catalog
  installation and `Deploy workers` for manager/worker environment deployment.
  Do not rename stable lower-level APIs only to match product copy. In
  ORCHESTRATE, `Deploy workers` may call `AGI.install` because that primitive
  prepares manager and worker runtime environments and reuses an already-ready
  local manager environment instead of forcing a reinstall. Update focused page
  tests and robot action labels with the semantic split.
- **Documentation screenshot update contract**: When documentation changes touch
  visible UI behavior, page labels, screenshots, GIFs, or diagrams derived from
  screenshots, refresh the corresponding source screenshot assets as part of the
  same docs update. Keep screenshots in the canonical docs source first, sync the
  public mirror, update captions/alt text and references, and inspect the
  rendered page so stale UI such as old labels, duplicate sidebars, or outdated
  screenshots cannot remain in published docs. Do not hand-edit generated
  `docs/html` screenshots or `_images`; regenerate or resync from source.
- **Shared page chrome restraint**: Keep global AGILAB page chrome minimal. Do
  not add active-project labels, chips, or badges above page controls by
  default; project identity belongs in the project selector, the sidebar, or an
  explicitly opened context expander.
- **Diagnostic quality rule**: If a failure was slow or ambiguous to diagnose,
  improve the error message, log context, status report, or validation output
  as part of the fix when practical.
- **Token-budgeted logging rule**: Treat raw stdout/stderr and long tracebacks
  as artifacts, not default prompt/UI payloads. Default visible and agent-facing
  logs to compact signal-first summaries: counts, bounded high-value lines,
  latest relevant tail, and explicit omitted-line counts. Escalate to
  context-window details or full log artifacts only when the user, PyCharm
  debugging flow, or Codex diagnosis needs that detail. Keep the runtime
  diagnostics levels aligned with this contract: Quiet is essential status,
  Standard is compact signal summary, Detailed adds nearby context windows, and
  Debug may point to raw artifacts or include full text only when the log is
  already small enough for prompt-safe use.
- **Compact validation close-out rule**: In final user-facing replies, write
  `Validation passed.` without listing every command when all checks are green
  and the command details are not needed for the next action. Include validation
  detail only for failures, skipped checks, release or audit evidence,
  PR/commit messages that need reproducible proof, or when the user explicitly
  asks for the command list.
- **Dependency-bound validation rule**: When changing dependency caps or
  compatibility shims, validate the meaningful boundary versions when practical:
  the currently installed version, the new lower or upper bound, and an import
  or runtime smoke that exercises the affected API. If boundary validation is
  too expensive or platform-specific, document the untested edge and rely on the
  closest local or CI matrix check.
- **Environment-pollution regression rule**: If a bug depends on local state
  such as `HOME`, `~/.agilab`, `.agilab-path`, `.venv`, cluster settings,
  ignored generated files, cached wheels, or stale app/workspace copies, add a
  polluted-environment regression rather than only testing the clean path. The
  regression should prove AGILAB ignores, isolates, repairs, or reports the
  polluted state intentionally.
- **Pre-push guard pollution triage**: If a pre-push guard fails on projects,
  app catalogs, docs rows, or generated artifacts that are not part of the
  pushed diff, first classify whether the failure comes from the current diff,
  a real repository contract issue, or polluted local filesystem state. Compare
  `git diff --name-only @{u}..HEAD`, `git ls-files`, and `git check-ignore -v`
  before patching product code or bypassing the hook. Untracked generated app
  directories, local `.venv` links, build outputs, and workspace copies under
  source trees must be treated as environment pollution unless they are tracked
  release assets. If the guard should ignore them, fix or tighten the guard at
  the inventory layer and add a polluted-workspace regression; if bypassing is
  still necessary, state the exact unrelated guard failure and the targeted
  check that was run.
- **Reasonable factorization check**: When adding new code, look for nearby
  existing helpers, contracts, or patterns that can reasonably be reused or
  extended instead of duplicating logic. Factor only when it reduces real
  duplication or preserves a shared contract without increasing blast radius.
  Respect dependency-avoidance rules: do not pull app-specific dependencies into
  shared core, do not create import cycles, and do not move logic across package
  boundaries unless the dependency direction remains valid and the validation
  scope covers the affected callers.
- **Existing mechanism first**: Before adding a new UI control, workflow path,
  configuration key, launcher, persistence model, or helper abstraction, search
  for the existing mechanism that already solves the same user intent. Reuse or
  extend that mechanism when it is part of the established product contract.
  Do not invent a parallel mechanism just because it is faster locally; only add
  a new mechanism when the existing one is objectively insufficient, and state
  why in the change summary and regression plan.
- **Change-reporting accuracy rule**: When summarizing edits, make the coverage
  of the summary explicit enough that nearby preserved text is not mistaken for
  deleted text. If a change inserts rules around an existing rule, say whether
  the existing rule was preserved, moved, rewritten, or removed. Do not list
  only the newly added items when that can reasonably imply adjacent existing
  guidance disappeared.
- **PR-first publishing**: For normal code, docs, tests, workflow, and badge changes,
  work on a short branch, push it, open a GitHub PR, merge through the PR, and delete
  the branch after merge. Keep one coherent change per PR and stage only the files
  that belong to that scope. Direct pushes to `main` are reserved for explicit
  emergency fixes or release-maintenance operations where the user asks for that
  exception.
- **PR agent metadata**: Every AGILAB PR description must include an `Agent Metadata`
  section with the Tokki version (`tokki --version`, or `not used`/`unavailable`),
  agent/runtime name and version when exposed, model name, reasoning effort, and
  whether `/fast` mode was used. Do not infer missing values; write `unknown`,
  `unavailable`, or `not used` explicitly.
- **Agent commit provenance**: Agent-prefixed branches such as `codex/*`,
  `codex-*`, `claude/*`, `aider/*`, `opencode/*`, and `agent/*` must not use a
  human Git author or committer identity. Before committing on those branches,
  run `python3 tools/agent_commit_provenance_guard.py --check-config`; the
  repo hooks also run this guard at pre-commit and pre-push. If a released
  commit already has misleading identity metadata, do not rewrite public
  history; inventory PR-backed agent work with `python3
  tools/agent_commit_provenance_guard.py --inventory-github --repo
  ThalesGroup/agilab --json`, inventory direct first-parent history with
  `python3 tools/agent_commit_provenance_guard.py --inventory-git-history
  --first-parent --since 2026-06-01 --until '2026-06-24 23:59:59' --json`, and repeat the
  local-history inventory with `--root /Users/agi/PycharmProjects/thales_agilab
  --repo-label thales_agilab` when the docs/source sibling repo is in scope.
  Add a corrective provenance guard or note instead of rewriting public history.
- **PR evidence contract**: PR descriptions must stay current through merge.
  Include `Review Evidence` when model or sub-agent review was used, naming the
  reviewer model, result, and whether findings were addressed. If sub-agents were
  used, state their role/model and whether they edited files or reviewed only.
  Bugfix PRs must include `Repro`, `Root Cause`, and `Regression Test` sections;
  if automation is impractical, say why and name the closest validation. Any
  skipped check must include a reason such as `not applicable`, `GitHub skipped`,
  or `manual validation only`. Before marking a PR ready or merging, update the
  body if review, CI, validation, or skip status changed after PR creation.
- **Dirty-scope guardrail**: Before starting a new task in a dirty checkout, and
  before answering "push", "release", or "all clean", run `./dev scope`. It
  includes untracked non-ignored files by default. If it reports `MIXED`, stop
  adding changes to that checkout unless the user explicitly wants to merge the
  scopes. Either create a clean sibling worktree with
  `./dev task-worktree <branch-name>` and continue there, or stage only the exact
  files for the current task and run `./dev scope --staged`. This prevents one
  frequent failure mode: unrelated app, docs, skills, release, and test edits
  accumulating until no safe push or release scope is obvious.
- **AGILAB product goal**: Optimize AGILAB work toward becoming the strongest
  open-source workbench for turning AI/ML experiments, notebooks, and agent runs
  into replayable, attestable evidence. Prefer concrete evidence primitives:
  run manifests, notebook export manifests, artifact hashes, UI robot evidence,
  SBOM / `pip-audit` / provenance, release proof, and verifier/replay contracts.
  Keep claims honest; do not present roadmap items as shipped features.
- **Changelog accuracy**: Treat `CHANGELOG.md` as release evidence, not a
  release-script dumping ground. Before a release or any changelog edit, compare
  `## Unreleased`, the target release section, `git log <previous-tag>..HEAD`,
  and the public evidence state for PyPI, GitHub Releases, docs, and Hugging Face.
  Move only shipped, user-visible changes into the dated release section, keep
  unfinished or unverified work under `Unreleased`, and do not claim publication
  until the public evidence exists. If a release workflow fails and is recovered,
  record the final successful workflow or repair evidence, not the failed attempt,
  then rerun the release-proof check before closing the task.
- **Current-code planning guardrail**: Before answering "next move", "ready for release",
  "release it", "sync HF", or any operational sequencing question, inspect the current
  repository state and the authoritative workflow/tooling files instead of relying on memory.
  For release sequencing, check at least `./dev --print-only release`,
  `.github/workflows/pypi-publish.yaml`, and `tools/release_plan.py` before saying
  whether PyPI, GitHub release assets, Hugging Face sync, release proof, or docs updates
  are separate manual steps. If the workflow already performs a step, state the condition
  under which it runs rather than adding a redundant manual step.
- **Path-scoped maintenance memory**: Some fragile files have durable notes under
  `maintenance/memory/by-path/` using URL-encoded source paths. When `./dev impact` reports a
  maintenance-memory check, run it before closing the change and update the note
  only after the code and validations are current. Use
  `./dev memory context --files <path>` to read the hidden invariants for a
  touched file. Treat drifted notes as stale guidance, not current truth.
- **Optimized PyPI release scope**: Do not bump unchanged AGILAB packages only to keep
  a global version aligned. For partial behavior releases, compute the minimal publish
  set with `tools/release_plan.py --impact-base-ref <previous-tag>` or
  `tools/pypi_publish.py --impact-base-ref <previous-tag> --dry-run`. The impact
  selector maps changed paths to packages and adds only transitive bundle packages
  that exact-pin changed packages. Use the workflow `impact_base_ref` input for the
  same behavior in GitHub Actions; explicit `packages` or `roles` still override it.
  When answering what needs to be published, report this impacted package set first.
  Then run the same plan with `--skip-existing-pypi` to separate release scope from
  artifact existence; do not summarize `to publish: 0` as "nothing needs publishing."
- **Repository update command plan**: When the user asks to "update repos", "sync repos", or similar,
  first show the exact command plan as a fenced `bash` block with concrete `git -C <repo>` commands
  for each checkout. In AGILAB maintenance, the default repo-sync target set is the active
  `/Users/agi/PycharmProjects/agilab` checkout plus the sibling
  `/Users/agi/PycharmProjects/thales_agilab` canonical docs/apps checkout when it exists.
  Include both in the printed plan, or explicitly state why one is out of scope, missing,
  or unsafe to update. Use the fast path by default: `status --porcelain=v1 --untracked-files=no`,
  `fetch --prune`, `rev-list --left-right --count HEAD...@{u}`, then `merge --ff-only @{u}` only
  for repos that are actually behind. This avoids a redundant fetch from `git pull` and avoids slow
  untracked scans. Group independent repo checks and fetches in parallel when the tooling allows it.
  If a checkout has tracked dirty paths, do not merge it until the dirty paths are reported and the
  update plan is adjusted. If a dirty feature checkout blocks direct update of a repo's `main`,
  check whether a clean registered `main` worktree exists before omitting that repository from the
  update.
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
  changed files with `tools/pre_push_changed_files.py`. It rejects pushes that span too many
  non-infrastructure scopes before docs/release/app-contract checks run; split the work or use
  `AGILAB_ALLOW_MIXED_SCOPE_PUSH=1` only with an explicit reason. It runs docs mirror checks
  only when docs mirror inputs changed, release-proof checks only when release-proof inputs changed,
  agent-instruction contract checks only when AGENTS/runbook/skill/discovery inputs changed,
  and app-contract checks only when built-in app/package/catalog/docs contract inputs changed.
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
- **Browser dev-log validation**: When validating Streamlit, React, `agi-web`,
  custom component, canvas/WebGL, or iframe pages in a real browser, inspect
  browser dev-log evidence as part of the validation. For robot runs, use
  scenarios/options that capture console warnings/errors, `pageerror`, failed
  requests, and HTTP 4xx/5xx responses, then inspect the JSON/progress output
  or failure-bundle `browser-issues.json`. For manual Chrome validation, open
  DevTools Console and Network and report whether relevant runtime, asset, or
  HTTP errors were present. Do not call a browser page validated only because
  the visible DOM rendered.
- **CLI agent helpers**: Repo-scoped wrappers and configs exist for Codex, Aider, and
  OpenCode under `tools/*_workflow.*`, `.aider.conf.yml`, `opencode.json`, and
  `.opencode/agents/`. Keep them aligned with repo guardrails when workflow policy changes.
  When coding through a terminal agent, prefer launching it through Tokki when
  available so AGILAB sessions get compact context, noisy-output digestion,
  token-savings accounting, and consistent wrapper metadata. For ad-hoc
  terminal checks inside a session, prefer `tokki run -- <command>` when it can
  execute the command faithfully. Tokki is an agent-session efficiency layer,
  not a replacement for AGILAB validation gates.
- **Agent instruction contract**: Keep `AGENTS.md`, `AGENT_CONVENTIONS.md`,
  `AGENT_LEARNINGS.md`, `tools/agent_workflows.md`, public agent docs, and
  `agilab-capabilities.json` aligned. Run
  `python3 tools/agent_instruction_contract.py --check` after changing root
  agent runbooks, agent-discovery surfaces, or capability metadata.
- **Agent correction ledger**: When a correction reveals a reusable agent
  operating rule that is not already covered, add one concrete rule to
  `AGENT_LEARNINGS.md` or tighten an existing rule. Do not use it as a session
  transcript, generic caution list, or replacement for code/tests.
- **Streamlit form state**: In custom `app_args_form.py` pages, initialize editable widgets
  from persisted values (`defaults_model` / stored args). Only derive companion paths such as
  `data_out` from `data_in` when the stored value is actually missing. Do not silently replace
  an explicit saved value with a recomputed default on render; if a field is intentionally derived,
  make that dependency explicit in the UI instead of presenting it as a normal independent input.
- **Worker data path resolution layer**: In cluster and workflow execution,
  UI pages may choose and persist `workers_data_path`, but canonical share-root
  storage and app `data_in` / `data_out` resolution belong to the shared worker
  runtime: `runtime_misc_support.initialize_runtime_state`,
  `BaseWorker._resolve_data_dir`, and `agi_node.agi_dispatcher.base_worker_path_support`.
  The canonical workflow share root passed as `workers_data_path` is
  `clustershare/<user>/<workflow-id>/<session>`. App module subdirectories are
  appended by app arguments, where the module is the project name without the
  `_project` suffix, yielding
  `clustershare/<user>/<workflow-id>/<session>/<module>/...` for app data. Do
  not fix duplicated paths such as `<module>/<module>/dataset`, stale
  `<project>/<session>/workers`, or UI value re-aggregation in one app page
  only. Fix the shared resolver when the failure class is generic, keep UI
  fixes limited to default selection/persistence, and add regressions at both
  `test_base_worker_path_support.py` and `test_base_worker.py` plus a focused
  UI test only when the default/persisted value changes. Do not preserve
  backward compatibility for the legacy `/workers` layout unless an explicit
  migration request requires it.
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
- **agi-core owner gate**: Treat `src/agilab/core/agi-core/**` as owner-protected even after
  shared-core approval. Only GitHub actor `jpmorard` may change this path. The local pre-push
  hook and repo-guardrails CI run `tools/agi_core_change_guard.py`; agents should not stage or
  push `agi-core` changes for any other actor. Use `AGILAB_CORE_CHANGE_ACTOR=jpmorard` only when
  the real approving/publishing actor is jpmorard.
- **No silent fallbacks**: Do not introduce automatic API client fallbacks
  (`chat.completions` ↔ `responses`, runtime parameter rewrites, etc.). Detect missing
  capabilities up-front and fail with a clear, actionable error.
- **Installer hygiene**: The end-user installer guarantees `pip` inside
  `~/agi-space/.venv` and uses `uv --preview-features extra-build-dependencies pip` afterwards. If an install reports
  `No module named pip`, rerun the latest installer or execute
  `uv --preview-features extra-build-dependencies run python -m ensurepip --upgrade` once in `~/agi-space`.
- **Missing dependency triage**: Whenever an app run fails because a module
  cannot be imported, check *both* `src/agilab/apps/<app>/pyproject.toml`
  (manager environment) and
  `src/agilab/apps/<app>/src/<app>_worker/pyproject.toml` to confirm the
  dependency is declared in the correct scope. If the symptom is a readiness
  warning rather than a Python traceback, first verify whether the reported
  module is a real runtime import: inspect the declaring requirement, package
  metadata such as `top_level.txt` / `RECORD`, and a direct import in the
  target manager or worker venv. Do not tell users to install typing-only
  packages, placeholder metadata modules such as `__dummy__`, or other probe
  artifacts; fix the readiness probe or its dependency mapping instead.
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
- **Higher-model fix review**: When a product or code fix was designed or implemented with model assistance, request a review from a stronger model before closing, pushing, or merging when that is available. The review should challenge root cause, regression chain, blast radius, security risk, and test coverage. If no stronger model is available in the current environment, state that explicitly and still perform the normal local review and validation path.
- **Dependency removal audit**: When removing a dependency from code, check the impact on the corresponding
  `pyproject.toml` files as part of the same change. Remove stale declarations when they are no longer needed,
  or keep them only when there is a clear runtime, packaging, or optional-feature reason.
- **Installer flags**: For automation, set `CLUSTER_CREDENTIALS` / `OPENAI_API_KEY` in the
  environment, then use `./install.sh --non-interactive`/`-y`. Optional flags:
  `--apps-repository`, `--install-path`, `--install-apps [all|builtin|comma list]`,
  `--test-apps`, `--test-core`.
- **Script-first app install/test**: When AGILAB itself is already installed or
  the task is only to install/test source apps, use the model-free app installer
  directly instead of composing a root install, hand-editing `~/.agilab/.env`, or
  running ad-hoc pytest loops. From the checkout root, run
  `cd src/agilab && APPS_REPOSITORY=/path/to/apps-repo AGILAB_DEV_APPS_REPOSITORY=1 BUILTIN_APPS=__AGILAB_ALL_APPS__ ./install_apps.sh`
  and add `--test-apps` when app tests are requested. Use a comma-separated
  `BUILTIN_APPS` value for a narrow app subset, for example
  `BUILTIN_APPS=flight_trajectory_project`. On Windows, use the matching
  `src\agilab\install_apps.ps1 -TestApps` surface with the same environment
  variables. Reserve root `install.sh` / `install.ps1` for root/core/end-user
  side effects such as first install, `.agilab-path` updates, dataset seeding,
  or full install validation.
- **Apps repository symlinks**: Set `APPS_REPOSITORY` in
  `~/.local/share/agilab/.env` to the path of your apps repository checkout. The installer can
  create symlinks so optional apps/pages resolve without manual action.
- **Built-in apps directory**: First-party apps such as `flight_telemetry_project` and `minimal_app_project` now live under
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
- **Docs source of truth**: Editable docs live in
  `../thales_agilab/docs/source`; `docs/source` is the managed public mirror and
  `docs/html` is generated local output. After canonical docs edits, refresh the
  mirror and stamp with `uv --preview-features extra-build-dependencies run
  python tools/sync_docs_source.py --apply --delete`. Never hand-edit, stage, or
  commit `docs/html/**`.
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

- Use the `agilab-local-llm` skill for local LLM workflow details. Quick entry
  points are `tools/launch_gpt_oss.py`, `tools/gpt_oss_prompt_helper.py`, and
  `./lq`; pass `--print-only` or `--help` before changing model, endpoint,
  backend, port, workdir, cache, or metadata behavior.

---

## Agent workflows and maintenance

Use `tools/agent_workflows.md` for executable agent workflows, context routing,
skill scans, run evidence, and CLI-first references. Keep this file focused on
hard operating rules and route to focused skills for details:

| Need | Primary source |
|---|---|
| Run configuration edits and launch wrappers | `tools/agent_workflows.md`, `.idea/runConfigurations/`, `tools/run_configs/` |
| Diff impact and generated artifact refresh | `tools/impact_validate.py`, `./dev impact` |
| Docs publication and screenshots | `agilab-docs` |
| Installer, app install, and cluster troubleshooting | `agilab-installer`, `agilab-runbook`, `agilab-security-review-patterns` |
| Release, PyPI, badges, and public proof | `agilab-release-verification`, `./dev release`, `./dev badge` |
| Local LLM / GPT-OSS helpers | `agilab-local-llm` |
| Streamlit UI and browser robots | `agilab-streamlit-pages`, `agilab-ui-robot-validation` |

When a detailed recipe becomes generally useful, put it in the focused skill or
workflow document and leave only the routing rule here. Regenerate wrappers after
`.idea/runConfigurations/*.xml` edits, and keep generated or ignored launch
artifacts out of commits unless the owning tool says they are part of the
contract.
