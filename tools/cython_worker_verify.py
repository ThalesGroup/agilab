"""Project-agnostic raw-vs-preprocessed Cython worker verification and benchmarking.

This tool takes ANY worker project path (no app-name knowledge) and:

- locates ``src/<name>_worker/<name>_worker.py`` using the same runtime-target
  convention pre_install/AgiEnv use;
- builds the requested variants in a temporary sandbox with the same pipeline
  pieces as the worker build (``remove_decorators`` + optional
  ``preprocess_source`` + real ``cythonize``, honoring the resolved
  ``AGILAB_CYTHON_DIRECTIVES`` channel where the build module is importable);
- runs an optional workload from ``--entry 'module:function[:json-args]'``
  (import-only smoke when omitted);
- asserts deep equivalence between the pure-Python and compiled variants
  (``math.isclose`` for floats, ``==`` otherwise; numpy arrays / DataFrames are
  supported best-effort through a ``repr`` fallback when ``==`` does not return
  a plain bool);
- reports per-variant median/min/max wall time plus speedups, as JSON or CSV.

The process exits non-zero when any compiled variant diverges from the pure
Python reference.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import statistics
import subprocess
import sys
import sysconfig
import tempfile
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
AGI_ENV_SRC = ROOT / "src/agilab/core/agi-env/src"
AGI_NODE_SRC = ROOT / "src/agilab/core/agi-node/src"

MODE_RAW = "raw"
MODE_PREPROCESSED = "preprocessed"
MODE_BOTH = "both"
VARIANT_PYTHON = "python"
VARIANT_RAW = "cython_raw"
VARIANT_PREPROCESSED = "cython_preprocessed"
DEFAULT_REPEATS = 5
DEFAULT_WARMUPS = 1
FLOAT_REL_TOL = 1e-9
FLOAT_ABS_TOL = 1e-12
_REPR_PREVIEW_LIMIT = 200


class WorkerCompileError(RuntimeError):
    """Raised when cythonize/build_ext fails for one source variant."""


@dataclass(frozen=True)
class EntrySpec:
    """Parsed ``module:function[:json-args]`` workload entry."""

    module: str
    function: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


def ensure_core_paths() -> None:
    """Make agi_env / agi_node importable from the repo source layout."""

    for path in (AGI_ENV_SRC, AGI_NODE_SRC):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def parse_entry(spec: str) -> EntrySpec:
    """Parse ``module:function[:json-args]`` into an :class:`EntrySpec`.

    The JSON payload maps to positional args when it is a list, keyword args
    when it is an object, and a single positional arg otherwise.
    """

    parts = str(spec).split(":", 2)
    if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError(
            f"Invalid --entry {spec!r}; expected 'module:function[:json-args]'"
        )
    module, function = parts[0].strip(), parts[1].strip()
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = {}
    if len(parts) == 3 and parts[2].strip():
        payload = json.loads(parts[2])
        if isinstance(payload, list):
            args = tuple(payload)
        elif isinstance(payload, dict):
            kwargs = dict(payload)
        else:
            args = (payload,)
    return EntrySpec(module=module, function=function, args=args, kwargs=kwargs)


def _best_effort_equal(left: Any, right: Any) -> bool:
    """Best-effort fallback for values whose ``==`` is overloaded (numpy,
    DataFrames): compare ``repr`` output instead of elementwise truthiness."""

    try:
        return repr(left) == repr(right)
    # Defensive: arbitrary worker objects may raise from __repr__ too.
    except Exception:
        return False


def deep_equal(
    left: Any,
    right: Any,
    *,
    rel_tol: float = FLOAT_REL_TOL,
    abs_tol: float = FLOAT_ABS_TOL,
) -> bool:
    """Deep equivalence: ``math.isclose`` for floats, ``==`` otherwise.

    Containers (list/tuple/dict) recurse; NaN compares equal to NaN so numeric
    kernels with NaN sentinels stay comparable. Values whose ``==`` is
    overloaded and does not return a plain bool (numpy arrays, DataFrames) are
    compared best-effort through ``repr``.
    """

    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if isinstance(left, float) or isinstance(right, float):
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            return _best_effort_equal(left, right)
        if math.isnan(left) and math.isnan(right):
            return True
        return math.isclose(left, right, rel_tol=rel_tol, abs_tol=abs_tol)
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return False
        return all(
            deep_equal(left[key], right[key], rel_tol=rel_tol, abs_tol=abs_tol)
            for key in left
        )
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if isinstance(left, list) is not isinstance(right, list):
            return False
        if len(left) != len(right):
            return False
        return all(
            deep_equal(item_left, item_right, rel_tol=rel_tol, abs_tol=abs_tol)
            for item_left, item_right in zip(left, right)
        )
    try:
        verdict = left == right
        if isinstance(verdict, bool):
            return verdict
    # Defensive: overloaded __eq__ may raise (e.g. shape mismatches).
    except Exception:
        pass
    return _best_effort_equal(left, right)


def _fallback_runtime_target(project_name: str) -> str:
    """Directory-name convention used when agi_env is not importable."""

    normalized = str(project_name or "").strip().replace("-", "_")
    if normalized.endswith("_project"):
        normalized = normalized.removesuffix("_project")
    elif normalized.endswith("_worker"):
        normalized = normalized.removesuffix("_worker")
    return normalized


def _resolve_runtime_target(project_root: Path) -> str:
    ensure_core_paths()
    try:
        from agi_env.project.app_provider_registry import resolve_app_runtime_target
    # Defensive: stripped checkouts may not ship agi_env; fall back to the
    # directory-name convention pre_install relies on.
    except Exception:
        return _fallback_runtime_target(project_root.name)
    return resolve_app_runtime_target(project_root, project_root.name)


def locate_worker_source(project: str | Path) -> Path:
    """Locate ``src/<target>_worker/<target>_worker.py`` for any project."""

    project_root = Path(project).expanduser().resolve()
    if not project_root.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_root}")
    target = _resolve_runtime_target(project_root)
    worker_target = f"{target}_worker"
    worker_path = project_root / "src" / worker_target / f"{worker_target}.py"
    if not worker_path.is_file():
        raise FileNotFoundError(
            f"Worker source not found for project {project_root.name!r}; "
            f"expected {worker_path}"
        )
    return worker_path


def strip_worker_decorators(source_text: str) -> str:
    """Run the pipeline's ``remove_decorators`` pass on a worker source."""

    ensure_core_paths()
    from agi_node.agi_dispatcher.pre_install import remove_decorators

    return remove_decorators(source_text, verbose=False)


def preprocess_worker_source(source_text: str, *, filename: str) -> tuple[str, dict[str, Any]]:
    """Run the pipeline's ``preprocess_source`` pass, returning text + report."""

    ensure_core_paths()
    from agi_node.agi_dispatcher.cython_type_preprocess import preprocess_source

    preprocessed, preview = preprocess_source(source_text, filename=filename)
    return preprocessed, preview.to_report(input_path=filename)


def resolve_compiler_directives(project_dir: str | Path | None = None) -> dict[str, bool]:
    """Resolve compiler directives through the build module where importable.

    ``project_dir`` mirrors the real build pipeline, where ``build.py main()``
    chdirs to ``--app-path`` before resolving, so a project's
    ``[tool.agilab.cython].directives`` declaration is honored during
    verification exactly as it is during a worker build.
    """

    ensure_core_paths()
    pyvers_worker = "t" if sysconfig.get_config_var("Py_GIL_DISABLED") else ""
    try:
        from agi_node.agi_dispatcher.build import _resolve_cython_compiler_directives

        return _resolve_cython_compiler_directives(
            pyvers_worker=pyvers_worker,
            environ=os.environ,
            project_dir=project_dir,
        )
    # Defensive: build.py needs Cython at import time; fall back to no
    # directives so verification still works in minimal environments.
    except Exception:
        return {}


def load_python_module(module_name: str, source_text: str, *, filename: str) -> ModuleType:
    """Exec a worker source as a standalone pure-CPython module."""

    module = types.ModuleType(module_name)
    module.__file__ = filename
    code = compile(source_text, filename, "exec")
    sys.modules.pop(module_name, None)
    sys.modules[module_name] = module
    exec(code, module.__dict__)
    return module


def compile_python_module(
    build_root: str | Path,
    module_name: str,
    source_text: str,
    *,
    compiler_directives: dict[str, bool] | None = None,
) -> ModuleType:
    """Cythonize + build_ext one source into ``build_root`` and import it."""

    build_dir = Path(build_root)
    build_dir.mkdir(parents=True, exist_ok=True)
    pyx_path = build_dir / f"{module_name}.pyx"
    pyx_path.write_text(source_text, encoding="utf-8")
    directives = dict(compiler_directives or {})
    setup_path = build_dir / f"setup_{module_name}.py"
    setup_path.write_text(
        "\n".join(
            [
                "from setuptools import Extension, setup",
                "from Cython.Build import cythonize",
                f"extension = Extension({module_name!r}, [{pyx_path.name!r}])",
                "setup(",
                f"    name={module_name!r},",
                "    ext_modules=cythonize(",
                "        [extension],",
                "        language_level=3,",
                "        quiet=True,",
                f"        compiler_directives={directives!r},",
                "    ),",
                ")",
                "",
            ]
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(setup_path), "build_ext", "--inplace"],
        cwd=build_dir,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise WorkerCompileError(
            f"cythonize/build_ext failed for {module_name}:\n{detail[-2000:]}"
        )

    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    extension_path = build_dir / f"{module_name}{suffix}"
    if not extension_path.exists():
        candidates = sorted(build_dir.glob(f"{module_name}*.so"))
        if not candidates:
            candidates = sorted(build_dir.glob(f"{module_name}*.pyd"))
        if not candidates:
            raise WorkerCompileError(f"Compiled module not found under {build_dir}")
        extension_path = candidates[0]

    spec = importlib.util.spec_from_file_location(module_name, extension_path)
    if spec is None or spec.loader is None:
        raise WorkerCompileError(f"Unable to import compiled module from {extension_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(module_name, None)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def call_entry(module: ModuleType, entry: EntrySpec) -> Any:
    function = getattr(module, entry.function)
    return function(*entry.args, **entry.kwargs)


def workload_outcome(module: ModuleType, entry: EntrySpec) -> dict[str, Any]:
    """Call the workload and capture either its value or its exception."""

    try:
        return {"kind": "value", "value": call_entry(module, entry)}
    # Worker code boundary: the workload is arbitrary user code; record the
    # failure so variants can be compared on exception type.
    except Exception as exc:
        return {"kind": "exception", "type": type(exc).__name__, "detail": str(exc)}


def outcomes_equivalent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Two workload outcomes match on kind, then value/exception type."""

    if left.get("kind") != right.get("kind"):
        return False
    if left.get("kind") == "exception":
        return left.get("type") == right.get("type")
    if left.get("kind") == "import-only":
        return True
    return deep_equal(left.get("value"), right.get("value"))


def _outcome_for_report(outcome: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe view of an outcome (values are repr-truncated)."""

    if outcome.get("kind") == "value":
        return {
            "kind": "value",
            "value_repr": repr(outcome.get("value"))[:_REPR_PREVIEW_LIMIT],
        }
    return dict(outcome)


def measure_callable(
    fn: Callable[[], Any],
    *,
    repeats: int,
    warmups: int,
) -> dict[str, Any]:
    """Median/min/max wall-time samples for a zero-arg callable."""

    samples: list[float] = []
    result: Any = None
    for index in range(warmups + repeats):
        start = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - start
        if index >= warmups:
            samples.append(elapsed)
    return {
        "samples_seconds": samples,
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "result": result,
    }


def _ensure_workload_paths(worker_path: Path) -> None:
    ensure_core_paths()
    src_dir = str(worker_path.parents[1])
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)


def run_verification(
    *,
    project: str | Path,
    entry: str | EntrySpec | None = None,
    mode: str = MODE_BOTH,
    repeats: int = DEFAULT_REPEATS,
    warmups: int = DEFAULT_WARMUPS,
) -> dict[str, Any]:
    """Build the requested variants, check equivalence, and time the workload."""

    if mode not in (MODE_RAW, MODE_PREPROCESSED, MODE_BOTH):
        raise ValueError(f"Unsupported mode {mode!r}")
    project_root = Path(project).expanduser().resolve()
    worker_path = locate_worker_source(project_root)
    _ensure_workload_paths(worker_path)
    source_text = worker_path.read_text(encoding="utf-8")
    stripped = strip_worker_decorators(source_text)
    entry_spec = parse_entry(entry) if isinstance(entry, str) else entry
    # Resolve against the verified project so its pyproject [tool.agilab.cython]
    # directives apply, matching the real build (which chdirs to --app-path).
    directives = resolve_compiler_directives(project_root)

    preprocess_summary: dict[str, Any] | None = None
    variants: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="agilab-cython-verify-") as tmp_dir:
        build_root = Path(tmp_dir)
        modules: dict[str, ModuleType] = {
            VARIANT_PYTHON: load_python_module(
                f"_agilab_verify_python_{worker_path.stem}",
                stripped,
                filename=str(worker_path),
            )
        }
        if mode in (MODE_RAW, MODE_BOTH):
            modules[VARIANT_RAW] = compile_python_module(
                build_root,
                f"_agilab_verify_raw_{worker_path.stem}",
                stripped,
                compiler_directives=directives,
            )
        if mode in (MODE_PREPROCESSED, MODE_BOTH):
            preprocessed, report = preprocess_worker_source(
                stripped,
                filename=str(worker_path),
            )
            preprocess_summary = {
                "typed_count": len(report.get("declarations", ())),
                "skipped_count": len(report.get("skipped", ())),
                "report": report,
            }
            modules[VARIANT_PREPROCESSED] = compile_python_module(
                build_root,
                f"_agilab_verify_preprocessed_{worker_path.stem}",
                preprocessed,
                compiler_directives=directives,
            )

        for name, module in modules.items():
            if entry_spec is None:
                outcomes[name] = {"kind": "import-only"}
                variants[name] = {
                    "workload": "import-only",
                    "outcome": {"kind": "import-only"},
                }
                continue
            outcome = workload_outcome(module, entry_spec)
            outcomes[name] = outcome
            variants[name] = {
                "workload": f"{entry_spec.module}:{entry_spec.function}",
                "outcome": _outcome_for_report(outcome),
            }

        # Timings stay inside the TemporaryDirectory context: the loaded
        # extension modules are backed by files under build_root.
        if entry_spec is not None:
            for name, module in modules.items():
                if outcomes[name].get("kind") != "value":
                    continue
                timing = measure_callable(
                    lambda module=module: call_entry(module, entry_spec),
                    repeats=repeats,
                    warmups=warmups,
                )
                timing.pop("result", None)
                variants[name].update(timing)

    python_median = variants[VARIANT_PYTHON].get("median_seconds")
    equivalent = True
    for name in (VARIANT_RAW, VARIANT_PREPROCESSED):
        if name not in variants:
            continue
        variant_equivalent = outcomes_equivalent(outcomes[VARIANT_PYTHON], outcomes[name])
        variants[name]["equivalent_to_python"] = variant_equivalent
        equivalent = equivalent and variant_equivalent
        median = variants[name].get("median_seconds")
        if python_median and median:
            variants[name]["speedup_vs_python"] = python_median / median

    results: dict[str, Any] = {
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "project": str(Path(project).expanduser().resolve()),
            "worker_source": str(worker_path),
            "entry": (
                f"{entry_spec.module}:{entry_spec.function}" if entry_spec else None
            ),
            "mode": mode,
            "repeats": repeats,
            "warmups": warmups,
            "compiler_directives": directives,
        },
        "preprocess": preprocess_summary,
        "variants": variants,
        "equivalent": equivalent,
    }
    raw_median = variants.get(VARIANT_RAW, {}).get("median_seconds")
    preprocessed_median = variants.get(VARIANT_PREPROCESSED, {}).get("median_seconds")
    if raw_median and preprocessed_median:
        results["speedup_preprocessed_vs_raw"] = raw_median / preprocessed_median
    return results


def rows_for_csv(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a verification report into per-variant CSV rows."""

    rows: list[dict[str, Any]] = []
    for runtime, data in results.get("variants", {}).items():
        median = data.get("median_seconds")
        speedup = data.get("speedup_vs_python")
        equivalent = data.get("equivalent_to_python")
        rows.append(
            {
                "runtime": runtime,
                "median_seconds": f"{float(median):.6f}" if median is not None else "",
                "min_seconds": (
                    f"{float(data['min_seconds']):.6f}"
                    if data.get("min_seconds") is not None
                    else ""
                ),
                "max_seconds": (
                    f"{float(data['max_seconds']):.6f}"
                    if data.get("max_seconds") is not None
                    else ""
                ),
                "speedup_vs_python": (
                    f"{float(speedup):.2f}"
                    if speedup is not None
                    else ("1.00" if runtime == VARIANT_PYTHON and median else "")
                ),
                "equivalent": "" if equivalent is None else str(bool(equivalent)).lower(),
            }
        )
    return rows


CSV_FIELDNAMES = (
    "runtime",
    "median_seconds",
    "min_seconds",
    "max_seconds",
    "speedup_vs_python",
    "equivalent",
)


def write_csv(path: Path, results: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(CSV_FIELDNAMES),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows_for_csv(results))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify (and optionally benchmark) any AGILAB worker project by "
            "compiling raw and type-preprocessed Cython variants and asserting "
            "behavioral equivalence against pure CPython."
        )
    )
    parser.add_argument(
        "--project",
        type=Path,
        required=True,
        help="Path to any worker project (contains src/<name>_worker/<name>_worker.py).",
    )
    parser.add_argument(
        "--entry",
        help=(
            "Workload spec 'module:function[:json-args]'. JSON list -> positional "
            "args, JSON object -> keyword args. Import-only smoke when omitted."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=(MODE_RAW, MODE_PREPROCESSED, MODE_BOTH),
        default=MODE_BOTH,
        help="Which compiled variant(s) to build and compare (default: both).",
    )
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--json-out", type=Path, help="Write the JSON report here.")
    parser.add_argument("--csv-out", type=Path, help="Write the per-variant CSV here.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    results = run_verification(
        project=args.project,
        entry=args.entry,
        mode=args.mode,
        repeats=args.repeats,
        warmups=args.warmups,
    )
    payload = json.dumps(results, indent=2, sort_keys=True)
    print(payload)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload + "\n", encoding="utf-8")
    if args.csv_out:
        write_csv(args.csv_out, results)

    if not results.get("equivalent", False):
        print(
            "ERROR: compiled variant behavior diverged from pure Python.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
