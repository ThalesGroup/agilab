# Free-threading lab

A reusable native Streamlit app and three-stage analysis notebook for **local CPU
scaling**. The original AGILAB notebook was created September 19, 2026. Its exact
complex-number Mandelbrot escape-count algorithm uses the rectangle
[-2, 1] × [-1.2, 1.2], with endpoint-inclusive coordinates and no artificial work.
Source material and BSD-3-Clause notices remain in `source/` and `LICENSE`.
[Python free-threading documentation](https://docs.python.org/3.14/howto/free-threading-python.html).

## Run with existing environments

The UI needs normal Python 3.13+ with the dependencies declared in
`pyproject.toml` / `requirements.txt` already installed. Measured children use
only the standard library and the unchanged `agilab_pool.py`. Set
`AGILAB_FREE_THREADING_PYTHON` to an existing free-threaded Python executable;
otherwise the runner searches for `python3.14t`. A missing interpreter, an ordinary
Python build, or an incorrect GIL state causes an actionable error. There is no
fallback, simulation, download, installation or network operation.

```bash
python -B -m streamlit run app.py --server.address=127.0.0.1
python -B tests.py
```

Run `solution.ipynb` with this project on `sys.path` and `PROJECT_ROOT` supplied.
It can run in any fresh working directory. Stage 1 imports and plans; stage 2
measures six real cases with one repeat; stage 3 checks every digest and writes
`results.json` in the notebook's working directory. Choose a scratch directory
for notebook execution to preserve a sealed app bundle. The public UI writes no
result files: JSON downloads are in memory. Child working directories and the
host lock file live in the system temporary directory. The outer showcase owns
the build-agent receipt, heading, build duration and build-your-own instructions.

## What is measured

Every case runs the same free-threaded Python build:

| Mode | GIL flag | AGILAB selection |
| --- | --- | --- |
| GIL-on threads | `-X gil=1` | forced `thread` |
| GIL-off threads | `-X gil=0` | `auto`, verified as thread |
| GIL-on processes | `-X gil=1` | forced `process`, spawn context |

The GIL-on control is **not stock CPython**. This demonstrates the included
AGILAB pool engine, not free-threaded compatibility of AGILAB's entire dependency
stack. Build capability (`Py_GIL_DISABLED`) and actual GIL state are checked before
and after execution. Every tile records its actual GIL state, PID, native thread
ID and monotonic start/end timestamps. The displayed timeline is recorded task
activity after a run, not a live monitor.

Each mode runs pool widths 1 and N. N is bounded by CPU count, process CPU count
where available, affinity, Linux cgroup v1/v2 quotas (including ancestors),
`CPU_CORES` / `SPACE_CPU_CORES`, and a maximum of 8. Fractional quotas are rounded
down, with one worker minimum; one CPU cannot demonstrate parallel scaling.
Selected width, resolved pool width and observed active workers are distinct in
the evidence. Very small workloads may not activate every available worker.

The same deterministic three-row tile plan is interleaved by bit-reversed tile
index, independent of backend and width. The engine's own batching, submission,
normalization and `work_done` reduction are used via `PoolFrameHooks`,
`exec_multi_process`, `exec_mono_process` and `run_works`. The application never
submits futures itself. Worker tasks only read immutable inputs; parent-side
reduction validates unique complete tiles and restores pixel order. SHA-256 uses
row-major unsigned 16-bit big-endian counts. Digests must match for every case
and repeat before a successful report is returned.

Engine elapsed time covers `run_works`, including executor startup and validated
image reduction. End-to-end wall time additionally includes child creation,
interpreter startup, imports, checksum, JSON transfer and exit. Median wall and
engine speedups each use their own mode's one-worker baseline; throughput is
pixels divided by median wall time. Small cases often measure mostly startup
overhead. There is no guarantee of linear speedup and no memory-use claim.
Mode order rotates and baseline/scaled order reverses between repeats.

## Bounds and isolation

The UI offers Small (192×128, 160 iterations) and Medium (288×192, 240 iterations),
finite worker choices and 1–3 repeats (default 2). Core bounds are width 2–384,
height 2–256 and iterations 1–300; booleans and nonintegers are rejected.
Dimensions of one are invalid because the original endpoint formula divides by
dimension minus one. Timed runs are never cached. Only the deterministic preview
is cached. Session state retains evidence and marks it old when controls change.

The runner requires POSIX process groups and file locking (Linux/macOS).
A nonblocking thread/file lock serializes benchmark requests across sessions and
server processes for the same host user. Busy requests are visibly rejected.
The lock is held only during measurement, never through a full Streamlit render.
Other host workloads are outside this lock's control. Each case has a 15-second
timeout and the run has a 50-second total budget, plus bounded cleanup grace.
Timeouts terminate the owned process group, including spawned descendants, and
reap the direct child. The engine parent normally reaps its process workers
during termination; after a forced kill, the OS reaper handles orphaned processes.

Child environments are private copies: inherited `PYTHON_GIL` and all
`AGILAB_POOL_*` values are removed, then required pool settings are applied.
Python site initialization and Python environment overrides are disabled in measured
children, preventing optional site packages from entering the measured process.
The UI never changes global environment variables or its working directory.
The configured interpreter is deployment-controlled; visitors cannot choose an
executable, enter code, install dependencies or launch a provider.

`tests.py` checks original-reference equivalence, all backends, multiple image
sizes, malformed inputs/results, environment scrubbing, CPU caps, locking and
process-group timeout cleanup. The supplied external verifier additionally
checks fresh notebook execution, `results.json`, UI startup and button interaction;
that verifier alone is not proof of scientific equivalence.
