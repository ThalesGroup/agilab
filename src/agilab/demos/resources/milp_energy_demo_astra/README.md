# MILP Energy Lab

The fifth Tokki × AGILAB public lab: build gas capacity in integer modules,
schedule those modules hour by hour, and measure independent scenarios with
the actual supplied AGILAB worker engine. No providers, credentials, downloads,
paid services or user-supplied executable code.

## Run and reproduce

With the declared dependencies already installed:

```bash
streamlit run app.py --server.address=127.0.0.1
python tests.py
python tests.py --browser
python energy_core.py single --input milp-settings.json --output replay.json
python energy_core.py batch --input batch-input.json --output batch-results.json
```

Use **Run analysis** in Experiment, inspect the checked result, save named
alternatives in Compare, and explicitly start a scaling experiment in Scale.
Reproduce provides settings, results, comparisons, benchmark JSON and exact
mathematical model text (not an LP file). Saved results identify their own
inputs: editing controls does not relabel an old solve. Session saves are
limited to ten and disappear when the browser session ends.

Batch input has `batch` (4, 8 or 12 settings objects) and `workers` (an integer
from 1 through the effective CPU limit, capped at 4). APIs: default_settings()
and solve_scenario(settings) in energy_core.py; run_batch and run_benchmark in
energy_runner.py. Partial settings fill defaults. Invalid types, unknown
fields, booleans masquerading as numbers, NaN, infinity and invalid bounds fail
before process launch.

solution.ipynb performs fresh default and infeasible solves, then a four-case
actual AGILAB batch comparison when two CPUs are available. It works from an
arbitrary directory with PROJECT_ROOT supplied or the project on sys.path,
and writes fresh results.json in the execution directory. No IPython features
are required. The supplied verifier executes code cells directly; nbclient
and ipykernel are not needed and are absent in the supplied environment. An
external Jupyter host would need its own kernel installation.

## Model and hand-checkable reference

The upstream four-hour demand is `[4000, 6000, 5000, 800]` MW. Twelve- and
24-hour cases repeat that synthetic stress pattern. Solar uses fixed fractions
`[0, 0.6, 0.9, 0]` at four hours and a deterministic daylight half-wave for
longer horizons. These are experiments, not forecasts. Each snapshot is one hour.

An integer installed module count bounds integer hourly commitment. Dispatch
lies between minimum loading and module rating times commitment. Integer
startup/shutdown counts exactly equal positive/negative commitment changes;
all modules initially start off, with no terminal commitment obligation.
A binary direction variable prevents simultaneous startup and shutdown.
This tightens PyPSA's transition inequalities so zero-cost starts/stops still
have meaningful counts. No linearized unit commitment is used.

Gas, used solar and shed demand balance hourly demand. Solar can be curtailed
freely and is a fixed sunk investment. Shedding costs 100,000 units/MWh.
Without shedding a capacity-limited case may be physically infeasible; allowing
shedding admits unserved demand, not extra physical supply. Positive shedding
describes the returned schedule; it is not a separate proof that every possible
full-service schedule is infeasible.

Costs use illustrative units: investment per MW **for this horizon**, gas and
shedding per MWh, standby per module-hour, startup per module-start. No
annualization, network, storage, ramp constraints or minimum up/down duration.
Downloaded model text specifies all equations and exact inputs.

At defaults, 30 × 200 MW = 6,000 MW are installed. Hourly active modules are
`[20, 30, 25, 4]`, dispatch equals demand, starts are `[20, 10, 0, 0]`, and stops
are `[0, 0, 5, 21]`. The objective is exactly **21,879**:

`6000 × 1 + (4000 + 6000 + 5000 + 800) × 1 + (20 + 30 + 25 + 4) × 1`.

For a deliberate tradeoff compare 12 hours with startup costs 0 and 1,000.
Keeping modules online during valleys can avoid later starts. Compare retains
both input sets. Costs only compare meaningfully across comparable horizons,
demand and service requirements.

## Solver evidence

PyPSA **1.2.4**, Linopy **0.9.1**, highspy **1.15.1** are pinned. Every solve
specifies solver_name='highs', one thread, a 0.1–10 second solver limit and
relative MIP tolerance 0–0.05 (default 0.0001). 'Optimal' means HiGHS reports
optimal within this configured tolerance, not an exact-arithmetic proof.
True HiGHS objective bound/gap are reported when available, otherwise null.
A time-limited incumbent is 'feasible' only after independent checks. Without
an incumbent, objective/capacity/modules are null and schedules empty;
infeasibility is distinguished from other failures ('error').

Checks independently reconstruct integrality, nonnegativity, demand balance,
dispatch bounds, capacity, solar/shedding limits, exact transitions and cost.
Physical/integer tolerance is 1e-5, relative objective tolerance 1e-7. Tests also
reconstruct equations outside this checker. JSON is finite/None and serialized
with allow_nan=False.

## Honest scaling and execution bounds

agilab_pool.py is unchanged actual public worker_pool_support.py. The picklable
ScenarioWorker/list-frame adapter invokes PoolFrameHooks, run_works and its
mono/process paths. The engine owns submission and aggregation; its executor
factory selects Python's spawn context. No custom executor replaces AGILAB.

Paired runs receive the exact same deterministic varied batch, bound by SHA-256.
Worker PIDs and monotonic start/end times are real. Full wall time includes
startup/imports, model construction, solving, checks and cleanup. Engine time
is separate; timeline starts at the first work item in each run. Throughput is
cases/full-wall-second and speedup is sequential wall / parallel wall. There
is no guaranteed improvement and no timing cache. This measures independent
local scenarios, not a distributed cluster or a faster single MILP. Matching
statuses/objectives use abs 1e-4 / rel 1e-7 tolerance; alternate optimal schedules
may differ. Errors never count as successful matches.

Limits consider os.cpu_count, os.process_cpu_count where available, affinity,
visible cgroup v1/v2 quotas and ancestors, SPACE CPU_CORES and a maximum of 4.
Fractional quotas round down (minimum one). One CPU disables scaling.

All solver work runs via sys.executable in isolated child process groups,
private temporary directories and single-thread BLAS environments. The web
process imports no solver or AGILAB runtime. A nonblocking OS lock rejects
overlapping requests with a busy message and spans both benchmark phases.
Single solves have a 45-second outer deadline; batch/benchmark computation
has 145 seconds plus bounded cleanup within the 150-second total budget.
Timed-out child groups and recorded descendants are terminated and waited for.
Per-run directories/logs are removed. A stable empty lock file remains in the
OS temporary directory to prevent lock-inode races. Nested outer runners are
rejected; nesting is limited to one supervisor and one AGILAB worker layer.
The public runtime targets POSIX (Linux/macOS).

Native status updates remain visible during work; other web sessions remain
available and overlapping analyses fail fast. The app never installs packages
or executes uploaded code. The outer gallery supplies source/ZIP/build evidence;
this standalone app does not invent or duplicate a build duration.

## Attribution and distinct licenses

Adapted from **Modular Expansion with Unit Commitment**, **PyPSA contributors**:
[pinned original notebook](https://github.com/PyPSA/PyPSA/blob/c838aa498557cc8e27a9d3ed10d45e35c4b0b442/docs/examples/modular-committable.ipynb).
The supplied provenance records commit c838aa498557cc8e27a9d3ed10d45e35c4b0b442
and SHA-256 f7ea554af73cb21b3eb8c0569c7c21eac0b327e0ce35c29cf23806d74af926b8.
Introduced 2026-02-17; updated 2026-08-05 for matplotlib compatibility.
The supplied source-selection metadata records 2,154 stars on 2026-09-19
(historical metadata, not a live count).

**The notebook, including its code, is CC-BY-4.0**, under upstream REUSE.toml's
docs/**/*.ipynb rule. [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
terms are preserved in source/LICENSE. The installed PyPSA library's MIT
license does not apply to this source notebook. Derived lab portions are also
CC-BY-4.0; see LICENSE for file scope. Changes: interactive lab, HiGHS,
parameters, synthetic solar/shedding, exact transitions, solver checks,
isolation and AGILAB batch measurement. The upstream link example is outside
this gas-generator lab's scope.

The supplied agilab_pool.py remains BSD-3-Clause under unchanged AGILAB_LICENSE.
All source files and both supplied licenses remain unchanged. The original
notebook was inspected as data and never executed.

## Validation scope

The focused suite runs real MILPs, independent physical/cost assertions,
the startup tradeoff, boundary rejection, process cleanup and Streamlit AppTest.
The supplied notebook/app verifier additionally executes solution.ipynb from
a fresh directory and clicks Run analysis. It verifies execution/interface
behavior, not scientific equivalence to the original notebook.

The optional `--browser` check uses an already-installed Playwright/Chromium,
captures console/page/network errors, checks the five sections and downloads,
and records desktop/mobile screenshots. It never installs browsers. The build
sandbox forbids localhost socket binding, so that browser check could not run
here; actual browser layout and console/network behavior remain unverified.
