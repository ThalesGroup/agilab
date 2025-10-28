# ILP Project

Operational notes for the ILP routing demo.

## Routing strategy

- Demands are routed with an AGILab-native solver that evaluates every path
  produced by `Flyenv`, selecting the option with the highest available
  throughput (minimum residual bandwidth along the path).
- Bearer families are prioritised in the order `OPTICAL` → `IVL` → `SATCOM`
  → `LEGACY` when two paths have the same bandwidth.
- Latency ceilings from each demand are enforced, so high-bandwidth but slow
  bearers (e.g. SATCOM) are bypassed automatically when they breach the limit.
- Allocation results now expose both the requested and delivered bandwidth,
  per-hop bearer choices, and the total latency to ease debugging in notebooks
  such as `traffic-gen.ipynb`.

## Quick start

```bash
cd src/agilab/examples/ilp
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python AGI.get_distrib_ilp.py
```

```bash
cd src/agilab/apps/ilp_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python ../../examples/ilp/AGI.run_ilp.py
```

## Test suite

Run from `src/agilab/apps/ilp_project`:

```bash
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python app_test.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_ilp_manager.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_ilp_worker.py
```

## Worker packaging

```bash
cd src/agilab/apps/ilp_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python build.py \
  bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" \
  -d "$HOME/wenv/ilp_worker"
```

```bash
cd "$HOME/wenv/ilp_worker"
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python build.py \
  build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" \
  -b "$HOME/wenv/ilp_worker"
```

## Post-install checks

```bash
cd src/agilab/apps/ilp_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python "$HOME/wenv/ilp_worker/src/ilp_worker/post_install.py" \
  src/agilab/apps/ilp_project 1 "$HOME/data/ilp"
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python src/ilp_worker/pre_install.py \
  remove_decorators --verbose --worker_path "$HOME/wenv/ilp_worker/src/ilp_worker/ilp_worker.py"
```

Refer to `src/agilab/apps/README.md` for the complete launch matrix and shared troubleshooting notes.
