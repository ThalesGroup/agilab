# MILP Energy Lab

An interactive, self-contained laboratory for **modular expansion with unit
commitment** — a mixed-integer linear program (MILP) solved with PyPSA and the
HiGHS solver. The lab turns a static notebook into a repeatable, parameterized
experiment with bounded inputs, exact solver-result checks, and a measured
parallel batch.

## Provenance and attribution

This lab is an adaptation of the public PyPSA example notebook
**"Modular Expansion with Unit Commitment"**, authored by the **PyPSA
contributors**.

- Pinned original notebook:
  <https://github.com/PyPSA/PyPSA/blob/c838aa498557cc8e27a9d3ed10d45e35c4b0b442/docs/examples/modular-committable.ipynb>
- Source license: **Creative Commons Attribution 4.0 International (CC BY 4.0)**
  - <https://creativecommons.org/licenses/by/4.0/>
- The unchanged source notebook and its license are preserved under `source/`
  (`source/original.ipynb`, `source/LICENSE`). The PyPSA software library is
  MIT, but this source notebook (and its code) is CC BY 4.0.

Full file-by-file licensing, including the CC BY 4.0 terms for the derived lab
and the BSD 3-Clause terms for the unchanged AGILAB worker-pool engine, is in
[`LICENSE`](LICENSE) and [`AGILAB_LICENSE`](AGILAB_LICENSE).

## What changed relative to the original notebook

The original notebook demonstrates the model as a one-shot example. This lab
makes it an instrumented, reproducible experiment. Concretely it adds:

- An **interactive experiment lab** (Streamlit `app.py`) with bounded,
  validated parameters and a single "Run analysis" action.
- **Explicit HiGHS solving** with a single worker thread for deterministic,
  comparable results.
- **Bounded parameters and synthetic profiles** so every run is reproducible
  and finite.
- **Fixed solar with curtailment** and **optional load shedding** (cost-based)
  as first-class model options.
- **Exact startup/shutdown transitions** from an initially-off state, with
  per-unit binary commitment.
- **Independent solver-result checks**: the objective and physical constraints
  are reconstructed from the returned solution and compared against the model,
  and a hand-computable reference optimum is asserted.
- **Isolated execution** of each scenario (no cross-run solver state).
- **Actual AGILAB batch measurement** of parallel vs. sequential solving.
- **Reproducible JSON and mathematical-model exports** (`results.json`,
  `model.lp`, `model.mps`).

## Repository layout

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit interactive lab UI. |
| `energy_core.py` | Model construction and scenario solving (PyPSA + HiGHS). |
| `energy_runner.py` | Sequential and parallel batch execution and benchmarking. |
| `agilab_pool.py` | Unchanged AGILAB worker-pool engine (BSD 3-Clause). |
| `solution.ipynb` | Self-contained notebook pipeline (writes `results.json`). |
| `tests.py` | Focused, fast checks of the core solver results. |
| `source/` | Unchanged original notebook, its license, and provenance. |
| `lab_stages.toml` | Lab stage metadata. |
| `pyproject.toml`, `requirements.txt` | Project metadata and pinned dependencies. |

## Installation

Requires Python 3.11 or newer.

```bash
python -m pip install -r requirements.txt
```

The three solver/MILP libraries (`pypsa`, `highspy`, `linopy`) are pinned
exactly in `requirements.txt`.

## Running the lab

```bash
streamlit run app.py
```

Then click **Run analysis** to solve the current parameter set and view the
results, model, and benchmark exports.

## Running the notebook

```bash
jupyter nbconvert --execute solution.ipynb --inplace
```

The notebook writes a fresh `results.json` in its execution directory.

## Running the tests

```bash
python tests.py
```

The tests are focused and fast: they solve a small default scenario and assert
the independently computed optimum, physical feasibility, a capacity-limited
infeasible case, and a load-shedding case.
