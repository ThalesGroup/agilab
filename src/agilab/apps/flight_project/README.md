# Flight Project

Sample AGILab deployment that orchestrates flight simulations with the `flight_worker` bundle.

## Quick start

From the repository root:

```bash
cd src/agilab/examples/flight
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python AGI.get_distrib_flight.py
```

Generate and run a cluster-ready build:

```bash
cd src/agilab/apps/flight_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python ../../examples/flight/AGI.run_flight.py
```

## Test suite

Execute these targets from `src/agilab/apps/flight_project`:

```bash
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python app_test.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_call_worker.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_flight_manager.py
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python test/_test_flight_worker.py
```

## Worker packaging

Build the egg released to the worker virtual environment:

```bash
cd src/agilab/apps/flight_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python build.py \
  bdist_egg --packages "agent_worker, pandas_worker, polars_worker, dag_worker" \
  -d "$HOME/wenv/flight_worker"
```

Compile native extensions inside the worker environment:

```bash
cd "$HOME/wenv/flight_worker"
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python build.py \
  build_ext --packages "dag_worker, pandas_worker, polars_worker, agent_worker" \
  -b "$HOME/wenv/flight_worker"
```

## Post-install checks

Validate worker hooks once the bundle is deployed:

```bash
cd src/agilab/apps/flight_project
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python "$HOME/wenv/flight_worker/src/flight_worker/post_install.py" \
  src/agilab/apps/flight_project 1 "$HOME/data/flight"
PYTHONUNBUFFERED=1 UV_NO_SYNC=1 uv run python src/flight_worker/pre_install.py \
  remove_decorators --verbose --worker_path "$HOME/wenv/flight_worker/src/flight_worker/flight_worker.py"
```

Refer to `src/agilab/apps/README.md` for the full launch matrix and shared troubleshooting notes.
