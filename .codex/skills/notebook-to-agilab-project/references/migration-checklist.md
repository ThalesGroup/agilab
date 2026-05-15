# Migration Checklist

## Source side

- Name the notebooks in execution order.
- Keep one target variable.
- Keep one artifact folder.
- Replace hidden state with explicit input/output files.
- Put reusable project notebooks under `<app_project>/notebooks/`.
- Keep generated notebook exports and import sidecars out of the app source tree.

## AGILAB side

- `app_settings.toml` carries the stable args.
- `lab_stages.toml` captures the semantic sequence.
- `pipeline_view.dot` explains the pipeline in business terms.
- `ANALYSIS` reads exported files instead of rerunning notebook code when the
  result is productized as an AGI page.
- `notebook_import_views.toml` lives with the app project and maps imported
  notebook artifacts to Analysis views.
- WORKFLOW notebook import writes to the selected export workspace and looks up
  view manifests from the selected app project.
- ANALYSIS notebook launch reads from `<app_project>/notebooks/` and persists
  the selected notebook list.
- AGI snippets remain a valid reuse surface for code-centric logic; do not
  describe notebook/snippet reuse as local-runtime-only. Only the embedded
  ANALYSIS Jupyter sidecar is the local interactive launch path.

## Migration value to show

- parameters are centralized
- reruns are explicit
- artifacts are comparable across runs
- the analysis page is reusable without reopening notebooks
- notebooks remain available for interactive exploration without becoming the
  source of truth for pipeline state
- AGI snippets can carry reusable technical logic without forcing a full AGI
  page before the analysis surface is stable
- notebook logic can later move to manager/worker code without changing the story
