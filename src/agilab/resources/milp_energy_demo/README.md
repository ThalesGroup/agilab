# MILP Energy Lab

Explore modular generation investment, hourly commitment and dispatch, solar availability, and optional load shedding with PyPSA and HiGHS. Explicitly run a scenario, inspect its constraints and solver status, keep comparisons, or measure the same scenario batch through the unchanged AGILAB process pool on one and several local workers.

## Run locally

Use Python 3.13 or newer on Linux or macOS in an isolated environment:

```sh
python -m pip install -r requirements.txt
python -m streamlit run app.py
python -m pytest -q tests.py
```

Execute `solution.ipynb` from this directory or import its `lab_stages.toml` into AGILAB. The notebook writes fresh deterministic `results.json` in its execution directory; runtime timings and process IDs are excluded from that reproducibility artifact. The notebook's ordinary cells form one workflow stage that preserves their shared Python state.

## Interpretation

The default four-hour reference has demand 4000, 6000, 5000 and 800 MW, 200 MW modules, an optimum of 30 installed modules, and objective 21879 in the configured horizon cost units. These are independently calculated reference values; the app displays fresh solver results only after Run analysis. Investment is a cost per MW per horizon. Integer active-module counts range from zero to installed capacity, rather than representing one binary unit. The model includes minimum loading, derived startup/shutdown counts, curtailment and optional shedding at 100000 per MWh. No incumbent means no claimed objective or schedule.

Batch benchmarks measure throughput of independent scenarios using the real AGILAB pool engine and one HiGHS solver thread per scenario. They record solving PIDs and intervals, wall and engine times, requested/resolved/observed workers, and independently checked outcome agreement. Startup and cleanup are included in wall time. Parallel execution may be slower; these measurements do not establish distributed scaling or acceleration of one MILP. Runs have bounded process lifetimes and worker counts based on available CPUs.

## Source and build

Adapted from PyPSA contributors' [Modular Expansion with Unit Commitment notebook](https://github.com/PyPSA/PyPSA/blob/c838aa498557cc8e27a9d3ed10d45e35c4b0b442/docs/examples/modular-committable.ipynb), pinned at the cited commit. The original notebook, provenance and CC BY 4.0 license are under `source/`; attribution is retained. PyPSA the library is MIT licensed. The unchanged AGILAB pool engine is BSD-3-Clause licensed with `AGILAB_LICENSE` included.

Application Python, bundled tests, and notebook cells were generated or repaired by local `ddalcu/Qwen3.8-27B-MLX-Serve-4bit`, without cloud code-generation fallback. A coordinating assistant prepared requests, reviewed output, maintained declarative packaging, and ran independent checks. Generation used the native local MLX API and is not claimed as a Tokki agent offload. The public app does not invoke Qwen when visitors use it. `result.json` records the exact model revisions, measured build duration including repairs and validation, immutable file hashes, and verification scope.
