---
name: agilab-streamlit-pages
description: Streamlit page authoring patterns for AGILAB (session_state safety, keys, rerun, UX).
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-03-31
---

# Streamlit Pages Skill (AGILAB)

Use this skill when editing:
- `src/agilab/About_agilab.py`
- `src/agilab/pages/*.py`
- `src/agilab/apps-pages/*/src/*/*.py`
- custom `app_args_form.py` views in AGILAB-managed app repos

## Session State Rules (Avoid Common Crashes)

- Never assign `st.session_state["k"] = …` **after** a widget with `key="k"` was created.
  - Prefer `st.session_state.setdefault("k", default)` before the widget.
  - Or use widget return values and compute derived state separately.

- If you need to “reset” a widget value:
  - Use a different key (versioned key pattern), or
  - Gate the reset behind a rerun and only mutate state before widget creation.

## Recommended Pattern

1. Initialize defaults with `setdefault` at the top of the page.
2. Render widgets.
3. Read values from widgets, compute derived state, store under *different* keys.

## Derived Preview Metrics

- Treat previews as read-only explanations, not as another persisted config source.
- Compute any preview metric from the same backend helper used by the runtime or exported summary artifact.
- If a preview depends on existing generated files, label it explicitly as a previous-run value (for example, `Last generated ...`) rather than implying it reflects the current unsaved inputs.
- When both are available, show the distinction clearly:
  - current preview from present inputs
  - last generated metric from persisted output
- Do not write preview-only values back into `app_settings.toml` unless they are real app args.

## App-Specific Page Defaults

- Prefer app-declared defaults in `app_settings.toml` over page-level hardcoded paths.
- For apps-pages, use `pages.<page_name>` for app-specific defaults that should be portable across apps and machines.
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

## Key Hygiene

- Every widget must have a stable, unique key.
- Prefer namespaced keys: `f\"{page_id}:df_files\"`, not `"df_files"`.
