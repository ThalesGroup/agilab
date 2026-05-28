# Native Rust Worker Example

## Example Class

**Read-only preview.** The preview writes a Rust/PyO3 worker skeleton and evidence. It does not compile Rust or install an AGILAB app project.


## Purpose

Shows the optional Rust/PyO3 acceleration lane for an AGILAB worker:

```text
Python AGILAB worker -> typed hot kernel in Rust -> Python evidence and artifacts
```

The preview writes a small `maturin` project with a PyO3 extension module, a
worker wrapper, a sample payload, and machine-readable evidence. It does not
compile Rust by default, so the packaged example stays runnable on machines
without a Rust toolchain.

## What You Learn

- Rust can be used as a worker-owned hot-kernel implementation without moving
  AGILAB orchestration, dataframe I/O, reducers, or evidence out of Python.
- `maturin` plus PyO3 is the production-oriented Rust extension path.
- This is an advanced, optional lane. It should not become a base AGILAB
  dependency and should not replace the existing Cython worker proof.
- The useful boundary is small: move only typed, CPU-bound code that has a
  measured bottleneck.

## Install

There is no AGILAB project install for this preview. Install AGILAB first. To
only generate the skeleton, Python is enough.

To build the generated native module afterwards, install Rust and `maturin`:

```bash
uv tool install maturin
```

## Run

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/native_rust_worker/preview_native_rust_worker.py
```

From an installed AGILAB package, locate the packaged script:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'native_rust_worker' / 'preview_native_rust_worker.py')"
```

Then run it:

```bash
python preview_native_rust_worker.py
```

## Expected Input

The script creates a deterministic numeric payload:

- `values`
- `weights`
- `passes`

It does not read private data and does not require a compiler for the preview
step.

## Expected Output

The script writes:

```text
~/log/execute/native_rust_worker/native_rust_worker_evidence.json
~/log/execute/native_rust_worker/rust_worker/pyproject.toml
~/log/execute/native_rust_worker/rust_worker/Cargo.toml
~/log/execute/native_rust_worker/rust_worker/src/lib.rs
~/log/execute/native_rust_worker/rust_worker/python/agilab_native_worker_demo/__init__.py
~/log/execute/native_rust_worker/rust_worker/worker_wrapper.py
~/log/execute/native_rust_worker/rust_worker/sample_payload.json
```

Read `native_rust_worker_evidence.json` first. It records the Python reference
checksum, the generated file hashes, the build backend, and the AGILAB boundary
between Python orchestration and Rust native code.

## Expected Preview

The generated project is a proof skeleton, not a published wheel:

| Artifact | Purpose |
|---|---|
| `Cargo.toml` | Rust crate metadata and PyO3 dependency. |
| `pyproject.toml` | `maturin` build configuration for Python packaging. |
| `src/lib.rs` | Native `score_kernel` exposed as a Python function. |
| `worker_wrapper.py` | Python side of the worker-owned hot-kernel call. |
| `native_rust_worker_evidence.json` | Hashes and adoption-boundary evidence. |

## Read The Script

Open `preview_native_rust_worker.py` and look for these functions first:

- `python_reference_score()` keeps a Python checksum for the same kernel.
- `build_preview()` writes the Rust/PyO3 project skeleton and evidence.
- `main()` exposes the deterministic preview as a local command.

## Change One Thing

Run the preview with a custom output directory:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/native_rust_worker/preview_native_rust_worker.py --output-dir /tmp/agilab-rust-worker
```

Then open `/tmp/agilab-rust-worker/rust_worker/src/lib.rs`, change the kernel,
and rebuild from inside the generated `rust_worker` directory:

```bash
maturin develop --release
python worker_wrapper.py --payload sample_payload.json --output native_result.json
```

## Troubleshooting

- If `maturin` is missing, install it with `uv tool install maturin`.
- If Rust is missing, install the Rust toolchain before building the generated
  module. The preview itself does not require Rust.
- If import fails after editing `src/lib.rs`, rerun `maturin develop --release`
  from inside the generated `rust_worker` directory.
- If the native score differs from the Python reference, treat that as a kernel
  correctness bug before benchmarking speed.
