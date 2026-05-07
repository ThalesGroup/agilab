---
name: agilab-streamlit-pages
description: Streamlit page authoring patterns for AGILAB (session_state safety, keys, rerun, UX).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-05-07
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
  - `Stages` and `dependencies` instead of graph-only jargon such as nodes and edges
  - `Project name` when the widget selects a project
- Derived header values must be computed locally from existing evidence when possible.
  For example, count ORCHESTRATE runs from `run_*.log` files under the app run
  environment instead of adding another persisted setting.
- When a generic page has no app-specific semantic data, show an honest fallback such
  as execution steps, output files, or discovered dataframes rather than inventing a
  domain-specific metric.
- Keep one navigation surface per action. If a page already exposes compact sidebar
  launch links, do not duplicate the same action as in-page sidecar cards, repeated
  `Open` buttons, or another selector unless the second surface adds a distinct
  workflow step.
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
