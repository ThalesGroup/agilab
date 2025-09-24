# MyCode Project

Minimal AGILab scaffold used for quick experimentation.

## Quick start

```bash
cd src/agilab/examples/mycode
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python AGI.get_distrib_mycode.py
```

```bash
cd src/agilab/apps/mycode_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python ../../examples/mycode/AGI.run_mycode.py
```

## Test suite

Run from `src/agilab/apps/mycode_project`:

```bash
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python app_test.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_call_worker.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_mycode_manager.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_mycode_worker.py
```

## Worker packaging

```bash
cd src/agilab/apps/mycode_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python build.py \
  bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" \
  -d "$HOME/wenv/mycode_worker"
```

```bash
cd "$HOME/wenv/mycode_worker"
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python build.py \
  build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" \
  -b "$HOME/wenv/mycode_worker"
```

## Post-install checks

```bash
cd src/agilab/apps/mycode_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python "$HOME/wenv/mycode_worker/src/mycode_worker/post_install.py" \
  src/agilab/apps/mycode_project 1 "$HOME/data/mycode"
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python src/mycode_worker/pre_install.py \
  remove_decorators --verbose --worker_path "$HOME/wenv/mycode_worker/src/mycode_worker/mycode_worker.py"
```

Refer to `src/agilab/apps/README.md` for the complete launch matrix.
