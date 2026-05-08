# Migration Checklist

## Source side

- Name the notebooks in execution order.
- Keep one target variable.
- Keep one artifact folder.
- Replace hidden state with explicit input/output files.

## AGILAB side

- `app_settings.toml` carries the stable args.
- `lab_stages.toml` captures the semantic sequence.
- `pipeline_view.dot` explains the pipeline in business terms.
- `ANALYSIS` reads exported files instead of rerunning notebook code.

## Migration value to show

- parameters are centralized
- reruns are explicit
- artifacts are comparable across runs
- the analysis page is reusable without reopening notebooks
- notebook logic can later move to manager/worker code without changing the story
