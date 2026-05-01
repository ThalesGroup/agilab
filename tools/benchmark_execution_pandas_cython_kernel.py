from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import json
import statistics
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "src/agilab/apps/builtin/execution_pandas_project/src"
WORKER_SOURCE = APP_SRC / "execution_pandas_worker/execution_pandas_worker.py"
SOURCE_MODULE = "execution_pandas_worker.execution_pandas_worker"
COMPILED_MODULE = "_execution_pandas_typed_kernel_cy"
KERNEL_NAME = "_typed_numeric_score_kernel"
DEFAULT_ROWS = 100_000
DEFAULT_COMPUTE_PASSES = 32


def _ensure_app_path() -> None:
    path = str(APP_SRC)
    if path not in sys.path:
        sys.path.insert(0, path)


def _load_source_worker() -> ModuleType:
    _ensure_app_path()
    return importlib.import_module(SOURCE_MODULE)


def _build_compiled_worker(tmp_root: Path) -> ModuleType:
    pyx_path = tmp_root / f"{COMPILED_MODULE}.pyx"
    pyx_path.write_text(WORKER_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    setup_path = tmp_root / "setup.py"
    setup_path.write_text(
        "\n".join(
            [
                "from setuptools import Extension, setup",
                "from Cython.Build import cythonize",
                f"extension = Extension({COMPILED_MODULE!r}, [{pyx_path.name!r}])",
                "setup(",
                f"    name={COMPILED_MODULE!r},",
                "    ext_modules=cythonize([extension], language_level=3, quiet=True),",
                ")",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, str(setup_path), "build_ext", "--inplace"],
        cwd=tmp_root,
        check=True,
        capture_output=True,
        text=True,
    )
    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    extension_path = tmp_root / f"{COMPILED_MODULE}{suffix}"
    if not extension_path.exists():
        candidates = sorted(tmp_root.glob(f"{COMPILED_MODULE}*.so"))
        if not candidates:
            candidates = sorted(tmp_root.glob(f"{COMPILED_MODULE}*.pyd"))
        if not candidates:
            raise FileNotFoundError(f"Compiled module not found under {tmp_root}")
        extension_path = candidates[0]

    spec = importlib.util.spec_from_file_location(COMPILED_MODULE, extension_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to import compiled module from {extension_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(COMPILED_MODULE, None)
    sys.modules[COMPILED_MODULE] = module
    spec.loader.exec_module(module)
    return module


def _make_arrays(rows: int, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    row_idx = np.arange(rows, dtype=np.float64)
    x_values = np.ascontiguousarray(rng.random(rows, dtype=np.float64) * 100.0)
    y_values = np.ascontiguousarray(rng.random(rows, dtype=np.float64) * 50.0)
    signal_values = np.ascontiguousarray(((row_idx % 97.0) - 48.0) * 0.15)
    weight_values = np.ascontiguousarray(1.0 + (row_idx % 11.0) * 0.05)
    return x_values, y_values, signal_values, weight_values


def _execute_kernel(
    module: ModuleType,
    arrays: tuple[np.ndarray, ...],
    compute_passes: int,
) -> tuple[float, np.ndarray, np.ndarray]:
    score_0 = np.empty(arrays[0].shape[0], dtype=np.float64)
    score_last = np.empty(arrays[0].shape[0], dtype=np.float64)
    kernel = getattr(module, KERNEL_NAME)
    checksum = float(
        kernel(
            arrays[0],
            arrays[1],
            arrays[2],
            arrays[3],
            score_0,
            score_last,
            compute_passes,
            64,
        )
    )
    return checksum, score_0, score_last


def _run_kernel(module: ModuleType, arrays: tuple[np.ndarray, ...], compute_passes: int) -> float:
    checksum, _, _ = _execute_kernel(module, arrays, compute_passes)
    return checksum


def _validate_kernel_equivalence(
    source_worker: ModuleType,
    compiled_worker: ModuleType,
    arrays: tuple[np.ndarray, ...],
    compute_passes: int,
) -> None:
    python_checksum, python_score_0, python_score_last = _execute_kernel(
        source_worker,
        arrays,
        compute_passes,
    )
    cython_checksum, cython_score_0, cython_score_last = _execute_kernel(
        compiled_worker,
        arrays,
        compute_passes,
    )
    if not np.isclose(python_checksum, cython_checksum, rtol=1e-11, atol=1e-8):
        raise RuntimeError(
            "Cython kernel checksum does not match Python kernel checksum: "
            f"{python_checksum} != {cython_checksum}"
        )
    if not np.allclose(python_score_0, cython_score_0, rtol=1e-12, atol=1e-12):
        raise RuntimeError("Cython kernel score_0 output does not match Python output")
    if not np.allclose(python_score_last, cython_score_last, rtol=1e-12, atol=1e-12):
        raise RuntimeError("Cython kernel score_last output does not match Python output")


def _measure(
    module: ModuleType,
    arrays: tuple[np.ndarray, ...],
    *,
    compute_passes: int,
    repeats: int,
    warmups: int,
) -> dict[str, Any]:
    samples: list[float] = []
    checksum = 0.0
    for idx in range(warmups + repeats):
        t0 = time.perf_counter()
        checksum = _run_kernel(module, arrays, compute_passes)
        seconds = time.perf_counter() - t0
        if idx >= warmups:
            samples.append(seconds)
    return {
        "samples_seconds": samples,
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "checksum": checksum,
    }


def _rows_for_csv(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    speedup = results["speedup_vs_python"]
    row_count = int(results["environment"]["rows"])
    for runtime, data in results["runtimes"].items():
        median = float(data["median_seconds"])
        rows.append(
            {
                "runtime": runtime,
                "median_seconds": f"{median:.6f}",
                "min_seconds": f"{float(data['min_seconds']):.6f}",
                "max_seconds": f"{float(data['max_seconds']):.6f}",
                "rows_per_second": f"{row_count / median:.0f}" if median else "",
                "speedup_vs_python": f"{speedup:.2f}" if runtime == "cython" and speedup else "1.00",
                "checksum": f"{float(data['checksum']):.6f}",
            }
        )
    return rows


def _write_csv(path: Path, results: dict[str, Any]) -> None:
    rows = _rows_for_csv(results)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "runtime",
                "median_seconds",
                "min_seconds",
                "max_seconds",
                "rows_per_second",
                "speedup_vs_python",
                "checksum",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def run_benchmark(
    *,
    rows: int,
    compute_passes: int,
    repeats: int,
    warmups: int,
    seed: int,
) -> dict[str, Any]:
    source_worker = _load_source_worker()
    arrays = _make_arrays(rows, seed)
    with tempfile.TemporaryDirectory(prefix="agilab-cython-kernel-") as tmp_dir:
        compiled_worker = _build_compiled_worker(Path(tmp_dir))
        _validate_kernel_equivalence(
            source_worker,
            compiled_worker,
            arrays,
            compute_passes,
        )
        python_result = _measure(
            source_worker,
            arrays,
            compute_passes=compute_passes,
            repeats=repeats,
            warmups=warmups,
        )
        cython_result = _measure(
            compiled_worker,
            arrays,
            compute_passes=compute_passes,
            repeats=repeats,
            warmups=warmups,
        )

    speedup = python_result["median_seconds"] / cython_result["median_seconds"]
    return {
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "rows": rows,
            "compute_passes": compute_passes,
            "repeats": repeats,
            "warmups": warmups,
            "seed": seed,
            "kernel": KERNEL_NAME,
            "dtype_contract": "float64-contiguous",
        },
        "runtimes": {
            "python": python_result,
            "cython": cython_result,
        },
        "speedup_vs_python": speedup,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the typed numeric kernel used by execution_pandas_project."
    )
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--compute-passes", type=int, default=DEFAULT_COMPUTE_PASSES)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--csv-out", type=Path)
    args = parser.parse_args()

    results = run_benchmark(
        rows=args.rows,
        compute_passes=args.compute_passes,
        repeats=args.repeats,
        warmups=args.warmups,
        seed=args.seed,
    )
    payload = json.dumps(results, indent=2, sort_keys=True)
    print(payload)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload + "\n", encoding="utf-8")
    if args.csv_out:
        _write_csv(args.csv_out, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
