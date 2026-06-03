from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from textwrap import dedent
from typing import Any, Sequence


DEFAULT_OUTPUT_DIR = Path.home() / "log" / "execute" / "native_rust_worker"
SCHEMA = "agilab.example.native_rust_worker.evidence.v1"
CREATED_AT = "2026-01-01T00:00:00Z"
SAMPLE_VALUES = tuple(float(index) / 10.0 for index in range(1, 129))
SAMPLE_WEIGHTS = tuple(1.0 + ((index % 7) * 0.125) for index in range(1, 129))
DEFAULT_PASSES = 24


PYPROJECT_TOML = """\
[build-system]
requires = ["maturin>=1.9,<2"]
build-backend = "maturin"

[project]
name = "agilab-native-worker-demo"
version = "0.1.0"
requires-python = ">=3.11"
description = "Optional Rust/PyO3 hot-kernel demo for an AGILAB worker."
readme = "README.md"

[tool.maturin]
python-source = "python"
module-name = "agilab_native_worker_demo._native"
features = ["pyo3/extension-module"]
"""


CARGO_TOML = """\
[package]
name = "agilab-native-worker-demo"
version = "0.1.0"
edition = "2021"

[lib]
name = "_native"
crate-type = ["cdylib"]
path = "src/lib.rs"

[dependencies]
pyo3 = { version = "0.28", features = ["extension-module"] }
"""


RUST_LIB_RS = """\
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyfunction]
fn score_kernel(values: Vec<f64>, weights: Vec<f64>, passes: usize) -> PyResult<f64> {
    if values.len() != weights.len() {
        return Err(PyValueError::new_err("values and weights must have the same length"));
    }
    let mut score = 0.0_f64;
    for pass_index in 0..passes {
        let scale = 1.0 + (pass_index as f64 * 0.0001);
        for (value, weight) in values.iter().zip(weights.iter()) {
            let adjusted = value * weight * scale;
            score += adjusted.sin().abs() + adjusted.cos().abs() * 0.5;
        }
    }
    Ok(score)
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(score_kernel, module)?)?;
    Ok(())
}
"""


PYTHON_INIT = """\
from __future__ import annotations


try:
    from ._native import score_kernel
except ImportError as exc:  # pragma: no cover - requires a local Rust build
    raise RuntimeError(
        "The Rust extension is not built. Run `maturin develop --release` "
        "inside the generated rust_worker directory first."
    ) from exc


__all__ = ["score_kernel"]
"""


WORKER_WRAPPER = """\
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def python_reference_score(values: list[float], weights: list[float], passes: int) -> float:
    score = 0.0
    for pass_index in range(passes):
        scale = 1.0 + (pass_index * 0.0001)
        for value, weight in zip(values, weights, strict=True):
            adjusted = value * weight * scale
            score += abs(math.sin(adjusted)) + abs(math.cos(adjusted)) * 0.5
    return score


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the generated Rust hot-kernel wrapper.")
    parser.add_argument("--payload", type=Path, default=Path("sample_payload.json"))
    parser.add_argument("--output", type=Path, default=Path("native_result.json"))
    args = parser.parse_args()

    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    values = [float(value) for value in payload["values"]]
    weights = [float(value) for value in payload["weights"]]
    passes = int(payload["passes"])

    from agilab_native_worker_demo import score_kernel

    native_score = score_kernel(values, weights, passes)
    reference_score = python_reference_score(values, weights, passes)
    args.output.write_text(
        json.dumps(
            {
                "native_score": native_score,
                "python_reference_score": reference_score,
                "absolute_delta": abs(native_score - reference_score),
            },
            indent=2,
            sort_keys=True,
        )
        + "\\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
"""


README = """\
# AGILAB Native Rust Worker Skeleton

This generated project is a worker-owned hot-kernel skeleton. AGILAB keeps the
app orchestration, dataframe I/O, artifact paths, and evidence in Python; the
small CPU-bound kernel lives in Rust and is exposed to Python through PyO3.

It is intentionally not part of the AGILAB base install. Build it only when a
worker has a measured hot loop that benefits from native code.

## Build

```bash
uv tool install maturin
maturin develop --release
```

## Run

```bash
python worker_wrapper.py --payload sample_payload.json --output native_result.json
```

## AGILAB Integration Pattern

1. Keep the normal AGILAB worker class and reducer artifacts in Python.
2. Move only the typed, CPU-bound kernel into `src/lib.rs`.
3. Import the built extension from the worker implementation.
4. Record the runtime, checksum, dtype contract, and fallback path in the
   reducer output.
"""


def python_reference_score(
    values: Sequence[float],
    weights: Sequence[float],
    passes: int,
) -> float:
    import math

    if len(values) != len(weights):
        raise ValueError("values and weights must have the same length")
    score = 0.0
    for pass_index in range(passes):
        scale = 1.0 + (pass_index * 0.0001)
        for value, weight in zip(values, weights, strict=True):
            adjusted = value * weight * scale
            score += abs(math.sin(adjusted)) + abs(math.cos(adjusted)) * 0.5
    return score


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).strip() + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _hash_file(path)}


def build_preview(*, output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output_dir = output_dir.expanduser()
    rust_worker = output_dir / "rust_worker"
    package_dir = rust_worker / "python" / "agilab_native_worker_demo"
    source_dir = rust_worker / "src"

    payload = {
        "values": list(SAMPLE_VALUES),
        "weights": list(SAMPLE_WEIGHTS),
        "passes": DEFAULT_PASSES,
    }
    score = python_reference_score(SAMPLE_VALUES, SAMPLE_WEIGHTS, DEFAULT_PASSES)
    reference = {
        "sample_count": len(SAMPLE_VALUES),
        "passes": DEFAULT_PASSES,
        "python_reference_score": round(score, 12),
        "checksum": sha256(f"{score:.12f}".encode("utf-8")).hexdigest(),
    }

    files = {
        "pyproject": rust_worker / "pyproject.toml",
        "cargo": rust_worker / "Cargo.toml",
        "readme": rust_worker / "README.md",
        "rust_lib": source_dir / "lib.rs",
        "python_init": package_dir / "__init__.py",
        "worker_wrapper": rust_worker / "worker_wrapper.py",
        "sample_payload": rust_worker / "sample_payload.json",
    }
    _write_text(files["pyproject"], PYPROJECT_TOML)
    _write_text(files["cargo"], CARGO_TOML)
    _write_text(files["readme"], README)
    _write_text(files["rust_lib"], RUST_LIB_RS)
    _write_text(files["python_init"], PYTHON_INIT)
    _write_text(files["worker_wrapper"], WORKER_WRAPPER)
    _write_json(files["sample_payload"], payload)

    artifacts = {name: _artifact(path) for name, path in files.items()}
    evidence = {
        "schema": SCHEMA,
        "created_at": CREATED_AT,
        "execution_model": "python_worker_with_optional_rust_hot_kernel",
        "base_install_impact": "none",
        "requires_rust_toolchain_for_native_run": True,
        "recommended_build_backend": "maturin",
        "python_binding": "PyO3",
        "agilab_boundary": {
            "stays_in_python": [
                "AGILAB app orchestration",
                "worker class",
                "dataframe I/O",
                "artifact and evidence writing",
            ],
            "moves_to_rust": ["typed CPU-bound hot kernel"],
        },
        "python_reference": reference,
        "artifacts": artifacts,
        "commands": [
            "uv tool install maturin",
            "cd rust_worker && maturin develop --release",
            "cd rust_worker && python worker_wrapper.py --payload sample_payload.json --output native_result.json",
        ],
        "notes": [
            "This preview does not compile Rust by default.",
            "Use Cython first when the worker hot path already maps cleanly to typed Python.",
            "Use Rust/PyO3 when ownership, safety, or a reusable native crate justifies the packaging cost.",
        ],
    }
    evidence_path = output_dir / "native_rust_worker_evidence.json"
    _write_json(evidence_path, evidence)
    evidence["artifacts"]["evidence"] = _artifact(evidence_path)
    _write_json(evidence_path, evidence)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the AGILAB Rust/PyO3 worker preview.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    evidence = build_preview(output_dir=args.output_dir)
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
