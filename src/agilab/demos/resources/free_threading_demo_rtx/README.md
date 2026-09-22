# Free-threading lab

An AGILAB CPU-scaling lab that measures how one Mandelbrot escape-count workload
scales on **this machine** across three execution strategies:

| Mode | Build | GIL | AGILAB pool backend |
|---|---|---|---|
| `gil-on-threads` | free-threaded CPython (`python3.14t`) | on (`-X gil=1`) | forced thread pool |
| `gil-off-threads` | free-threaded CPython (`python3.14t`) | off (`-X gil=0`) | AGILAB auto backend |
| `gil-on-processes` | free-threaded CPython (`python3.14t`) | on (`-X gil=1`) | forced **spawn** process pool |

All six measured cases (each mode x {1, N} workers) run in the **same**
free-threaded build. The only differences are the GIL flag and the pool backend,
so any speedup is attributable to the execution strategy itself. Nothing is
simulated, timings are never estimated, and the app never falls back to
ordinary Python — a missing free-threaded interpreter is an actionable error.

Adapted from the original AGILAB free-threading notebook, created September 19,
2026 (AGILAB contributors, BSD-3-Clause; see `LICENSE`).
Background: [Free-threaded CPython](https://docs.python.org/3.14/howto/free-threading-python.html).

## Files

| File | Role |
|---|---|
| `free_threading_core.py` | Stdlib Mandelbrot kernel + AGILAB engine adapter + per-case CLI |
| `agilab_pool.py` | Included, **unmodified** AGILAB pool engine (dispatch + reduction) |
| `benchmark.py` | Subprocess orchestrator: 6 cases, timeouts (process-group kill), `results.json` |
| `app.py` | Streamlit UI: deterministic preview, one **Run analysis** button, live progress, metrics, timelines, evidence download |
| `solution.ipynb` | Notebook walkthrough: probe → run → verify → `results.json` |
| `tests.py` | Unit tests (pytest or `python tests.py`) |

## Prerequisites

1. A free-threaded CPython (e.g. `python3.14t`), discoverable via
   `AGILAB_FREE_THREADING_PYTHON` (recommended) or on `PATH`.
2. The app/UI runtime: `pip install -r requirements.txt` (Streamlit ≥ 1.36).
3. Optional: `SPACE_CPU_CORES` and the standard cgroup/affinity limits are
   honored when capping the worker count (max 8).

## Run

```bash
# Streamlit app (first load shows an untimed preview; "Run analysis" measures)
streamlit run app.py

# Benchmark CLI (writes results.json next to the app)
python benchmark.py --width 192 --height 128 --iterations 160 --workers 4 --repeats 2

# Notebook (writes results.json in its execution directory)
jupyter notebook solution.ipynb

# Tests
python tests.py            # or: pytest
```

## What "honest" means here

- Each case is a separate child process with a **private scrubbed environment**
  (`PYTHON_GIL`, `PYTHONPATH`, `AGILAB_POOL_*` are reset per mode); the UI never
  mutates global environment state.
- Work items are deterministic, independently computed row tiles; the AGILAB
  engine dispatches them and reduces them back to row-major pixel order.
- Every mode and repeat must produce the **identical sha256 digest** and match
  the serial reference, or the run is reported as failed.
- Speedups are medians over repeats vs each mode's own 1-worker baseline.
  Per-child (60 s) and total (150 s in the UI / 180 s budget) timeouts terminate
  the whole process group — no orphaned children.
- Scope: **local CPU scaling** on this machine. Results are not portable across
  hardware, and the UI says so.
