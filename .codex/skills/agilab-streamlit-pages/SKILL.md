---
name: agilab-streamlit-pages
description: Streamlit page authoring patterns for AGILAB (session_state safety, keys, rerun, UX).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-16
---

# Streamlit Pages Skill (AGILAB)

Use this skill when editing:
- `src/agilab/main_page.py`
- `src/agilab/pages/*.py`
- `src/agilab/apps-pages/*/src/*/*.py`
- custom `app_args_form.py` views in AGILAB-managed app repos

## Session State Rules (Avoid Common Crashes)

- Never assign `st.session_state["k"] = …` **after** a widget with `key="k"` was created.
  - Prefer `st.session_state.setdefault("k", default)` before the widget.
  - Or use widget return values and compute derived state separately.
- Do not both pre-seed `st.session_state[key]` and pass a widget default/value/index for
  the same keyed widget. Pick one source of initialization:
  - use the widget default and leave `st.session_state` untouched before creation, or
  - pre-seed `st.session_state` before creation and omit the widget default.
  This avoids Streamlit warnings such as "created with a default value but also had its
  value set via the Session State API".
  Shared widget wrappers should drop their default argument when the key already
  exists in session state.

- If you need to “reset” a widget value:
  - Use a different key (versioned key pattern), or
  - Gate the reset behind a rerun and only mutate state before widget creation.

## Recommended Pattern

1. Initialize defaults with `setdefault` at the top of the page.
2. Render widgets.
3. Read values from widgets, compute derived state, store under *different* keys.

## Project-Scoped State Models

- If a page can switch between projects/apps in one Streamlit session, any persisted widget state that belongs to a specific project must use project-scoped keys.
  - Prefer patterns like `f"cluster_pool__{app_name}"`, not `"cluster_pool"`.
  - Apply the same rule to toggles, text inputs, password/auth fields, scheduler/worker fields, and similar per-project controls.
- Keep one clear source of truth for persisted settings.
  - File-backed or workspace-backed `app_settings` should hydrate widget keys on page init and after project switches.
  - Do not let a stale widget key silently override freshly loaded settings just because it already exists in `st.session_state`.
- On project change:
  - compute any preservation/override decision before popping tracking keys from `st.session_state`
  - then clear the old project's widget keys explicitly
  - then rehydrate the new project's widget state from persisted settings
- Treat `app_settings["cluster"]`, `app_settings["args"]`, or equivalent persisted payloads as the serializable config contract.
  - Widget keys are UI transport, not a second config layer.

## Page Bootstrap And Path Drift

- At page start, resolve the active app and apps root from the current launch context first:
  explicit CLI args, current source checkout, and packaged runtime location. Only then consult
  persisted user settings.
- Do not let stale persisted state override the current launch root:
  - `~/.agilab/.env`
  - `~/.local/share/agilab/.agilab-path`
  - a previous `st.session_state["env"]`
  - a previous `active_app` or `APPS_PATH`
- If the launch context says the page is running from source, UI readiness cards such as
  ORCHESTRATE `Manager env` must point at the source app path, not `$HOME/agi-space`.
- When the resolved app root changes, rebuild or realign the session `env` object before
  rendering headers, buttons, or action state. Rendering first and repairing later leaves
  stale paths visible to users and can make action buttons operate on the wrong project.
- Add regressions for both cold sessions and warm sessions with stale `st.session_state`
  when touching page bootstrap, sidebar project selection, or ORCHESTRATE header state.

## Derived Preview Metrics

- Treat previews as read-only explanations, not as another persisted config source.
- Compute any preview metric from the same backend helper used by the runtime or exported summary artifact.
- If a preview depends on existing generated files, label it explicitly as a previous-run value (for example, `Last generated ...`) rather than implying it reflects the current unsaved inputs.
- When both are available, show the distinction clearly:
  - current preview from present inputs
  - last generated metric from persisted output
- Do not write preview-only values back into `app_settings.toml` unless they are real app args.

## Cross-Page UX and KPI Headers

- Keep sidebar text short and action-oriented. Remove labels that only restate the active
  project/page or explain obvious scope such as "actions below apply to this project".
- Prefer page headers with a few read-only KPI cards over status banners that say
  `ready`, `not set`, or `missing` without useful context.
- Use the same visual semantics across pages:
  - green only for verified positive values
  - amber for incomplete, missing, or no-evidence-yet values
  - neutral for identity or purely informational values
- Do not color a value green just because it is present when the value means "no run",
  "not configured", or "no artifact discovered".
- Use product-facing labels instead of internal implementation terms:
  - `Workflow graph` instead of `DAG shape`
  - `Stages` and `dependencies` for project workflow instead of graph-only jargon such as nodes and edges
  - `Plan`, `steps`, `outputs`, `Creates`, and `Uses` for multi-app workplans
    before technical DAG, artifact, node, or edge wording
  - hide generated graphs behind an explicit `Show graph` control when the
    graph can be too small to read
  - `Project name` when the widget selects a project
- Derived header values must be computed locally from existing evidence when possible.
  For example, count ORCHESTRATE runs from `run_*.log` files under the app run
  environment instead of adding another persisted setting.
- When a generic page has no app-specific semantic data, show an honest fallback such
  as execution stages, output files, or discovered dataframes rather than inventing a
  domain-specific metric.
- Keep one navigation surface per action. If a page already exposes compact sidebar
  launch links, do not duplicate the same action as in-page sidecar cards, repeated
  `Open` buttons, or another selector unless the second surface adds a distinct
  workflow stage.
- For lightweight page routing, prefer compact Markdown/HTML links with encoded
  query parameters such as `current_page` over a selectbox plus `Open` button when
  the user only needs to jump to a target. Add a tiny helper to construct and test
  the encoded URL instead of inlining query-string formatting in the render block.
- Treat legacy “default view” UI as configuration debt when a project already has a
  selected view list. Persist the selected list in `pages.view_module`; remove stale
  `default_view`/`default_views` values only when that behavior is intentionally
  replaced by the new launcher model.
- Update focused page tests when changing visible labels, header cards, or sidebar
  structure. Grep old wording before closing the task so stale copy does not survive in
  tests, docs, or screenshots.

## First-Proof Onboarding UX

- Treat the first-proof panel as a new-user wizard, not as an expert shortcut
  list. Every visible action must state whether it runs the built-in demo,
  imports AGILAB's included notebook, or uploads the user's own notebook.
- Do not hide packaged sample assets behind vague labels such as `example
  notebook` when the user cannot know where that file is. Prefer explicit copy
  such as `Use included notebook`, and show the project that will be created.
- Keep first-proof alternatives symmetric: the built-in demo lane should expose
  install, run, and analysis actions; the notebook lane should expose the
  included sample and a separate upload path for a user notebook.
- When changing first-proof labels, update ABOUT tests, PROJECT notebook-import
  tests, newcomer docs, and stale-wording greps in the same change.

## App-Specific Page Defaults

- Prefer app-declared defaults in `app_settings.toml` over page-level hardcoded paths.
- For apps-pages, use `pages.<page_name>` for app-specific defaults that should be portable across apps and machines.
- Remember that versioned app seeds and workspace settings are different:
  - `src/.../app_settings.toml` is only the seed.
  - mutable user/HF settings can live under `~/.agilab/apps/<app>/app_settings.toml`.
  - if a bug is caused by a stale default already persisted in the workspace, changing only the seed will not fix existing deployments.
- When changing app analysis defaults, add a narrow migration for the stale workspace value when needed.
  - Scope migrations to the affected app and legacy value.
  - Preserve custom user defaults when the legacy value is absent.
  - Write the migrated config before widgets/options are built.
- For app/page visibility, prefer explicit exclusions over global restrictions when the app should still see generic pages.
  - Example: for `flight_project`, exclude `view_maps_network` while keeping generic views such as `view_maps`, `view_maps_3d`, and `view_barycentric` available.
  - Avoid setting a broad `restrict_to_view_module` unless hiding every undeclared generic view is the intended product behavior.
- For `view_maps_network`, supported defaults now include:
  - `dataset_base_choice`
  - `dataset_custom_base`
  - `dataset_subpath`
  - `default_traj_globs`
  - `default_allocation_globs`
  - `default_baseline_globs`
  - `cloudmap_sat_path`
  - `cloudmap_ivdl_path`
- Keep persisted `view_maps_network` state for user choices, but put repo/app conventions under `pages.view_maps_network`.

## DAG And Worker-Type UI

- For generic ORCHESTRATE/WORKFLOW page behavior that depends on whether an app is
  DAG-based, use `AgiEnv.base_worker_cls` first. `AgiEnv` already populates this
  from worker source inspection, so page code should not import app worker classes
  just to decide which controls to show.
- Treat `DagWorker`, known DAG-derived workers such as `Sb3TrainerWorker`, and
  custom `*Dag*Worker` base names as DAG-capable for UI decisions.
- Keep name-token fallbacks narrow and explicit for planning-only or synthetic apps
  that intentionally have no DAG worker base yet, such as global DAG draft/demo
  projects.
- Reuse one helper for DAG detection across sidebars, execute controls, and
  distribution/workplan rendering. Do not leave page-local string checks such as
  `endswith("dag-worker")`; they drift from the `AgiEnv` contract and silently fail
  for real base names like `DagWorker`.
- DAG-only planning projects should expose run/workflow actions, not dataframe
  load/export/delete controls, unless the app has an explicit dataframe artifact
  contract.

## Rerun API

- Do not use `st.experimental_rerun()`; use `st.rerun()`.

## Diagnostics Rendering

- Render long diagnostics and tracebacks as code blocks, not message-box text:
  - `st.error("Short actionable summary.")`
  - `st.caption("Full diagnostic")`
  - `st.code(diagnostic_text, language="text")`
- Do not embed Markdown code fences inside `st.error()` or `st.code()`.
- Do not pass `traceback.format_exc()` directly to `st.error()`; Streamlit message
  boxes collapse readability and can flatten newlines.
- If a diagnostic arrives as a single long line, format a display-only copy with
  line breaks or wrapping before passing it to `st.code`; keep the original
  exception/message unchanged for logs and assertions that depend on exact text.
- Add a focused helper test for display formatting and keep the repository scan
  guard in `test/test_streamlit_diagnostic_rendering.py` green when touching
  diagnostic rendering paths.

## Action Results and Runtime Logs

- Do not classify a page action as failed only because stderr is non-empty.
  AGILAB runtime helpers, package managers, and subprocess wrappers may write
  normal progress or warnings to stderr.
- Treat action success/failure as a typed result contract first:
  - subprocess return code or raised exception
  - `ActionResult.status`
  - explicit fatal markers in logs such as tracebacks, non-zero exit status,
    missing imports, or worker/build failure phrases
- Keep log classifiers narrow. Avoid broad predicates such as `"failed" in line`
  unless the surrounding phrase is part of a known fatal contract; benign warnings
  can contain words like `failed`.
- Apply the same action-result semantics to sibling workflow actions. If INSTALL
  and RUN already use typed results or fatal-log heuristics, do not leave CHECK,
  DISTRIBUTE, LOAD, EXPORT, or service actions on older `stderr == failure` rules.
- Add a regression with a realistic noisy stderr log for any action whose runtime
  can emit progress on stderr. The regression should prove benign stderr stays
  successful and a concrete fatal marker still fails.

## WORKFLOW Assistant UX

- Default generated dataframe work to a safe-action mode: the model returns a
  versioned JSON action contract, AGILAB validates it, and the UI displays the
  deterministic pandas code derived from that contract.
- Keep raw Python generation as an explicit advanced choice with clear wording.
  Do not imply a container or VM is required for the normal safe-action path.
- Persist the generation mode and action contract beside the saved stage so a
  reopened `lab_stages.toml` explains whether code came from safe actions or
  raw Python.
- When generation fails validation, keep the existing stage code intact and show
  the contract error; do not silently replace it with partial or arbitrary code.

## Long-Running Action Timers

- For long async actions such as ORCHESTRATE install/run/serve, render a live
  elapsed-time placeholder before awaiting the subprocess or background task.
- Prefer `asyncio.create_task(...)`, yield once with `await asyncio.sleep(0)`,
  then poll at a short fixed interval and update the placeholder until the task
  is done. Do not depend only on log callbacks; quiet processes still need a
  visible timer.
- Keep the final duration visible after completion and record it in action
  history when that history is user-facing evidence.
- Store timer values under non-widget session-state keys such as
  `last_run_elapsed_seconds` and `last_run_elapsed_label`; never mutate a key
  already owned by a rendered widget.
- Add focused tests for both the formatting helper and the action path that
  records the elapsed label, without requiring a real long-running process.

## Key Hygiene

- Every widget must have a stable, unique key.
- Prefer namespaced keys: `f\"{page_id}:df_files\"`, not `"df_files"`.
