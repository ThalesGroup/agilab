from __future__ import annotations

import importlib.util
from pathlib import Path

_IMPORT_GUARD_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "import_guard.py"
_IMPORT_GUARD_SPEC = importlib.util.spec_from_file_location("agilab_import_guard_test", _IMPORT_GUARD_PATH)
if _IMPORT_GUARD_SPEC is None or _IMPORT_GUARD_SPEC.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_IMPORT_GUARD_PATH}")
import_guard = importlib.util.module_from_spec(_IMPORT_GUARD_SPEC)
_IMPORT_GUARD_SPEC.loader.exec_module(import_guard)


def test_import_agilab_module_loads_local_fallback() -> None:
    package_root = Path(import_guard.__file__).resolve().parent
    fallback = package_root / "_tmp_import_guard_module_fallback.py"
    fallback.write_text("VALUE = 7\n", encoding="utf-8")
    try:
        module = import_guard.import_agilab_module(
            "agilab.test_missing_module",
            current_file=Path(import_guard.__file__),
            fallback_path=fallback,
            fallback_name="agilab_test_import_guard_module_fallback",
        )
    finally:
        fallback.unlink(missing_ok=True)

    assert module.VALUE == 7


def test_import_agilab_symbols_remains_backward_compatible() -> None:
    package_root = Path(import_guard.__file__).resolve().parent
    fallback = package_root / "_tmp_import_guard_symbols_fallback.py"
    fallback.write_text("VALUE = 11\n", encoding="utf-8")
    target_globals: dict[str, object] = {}

    try:
        module = import_guard.import_agilab_symbols(
            target_globals,
            "agilab.test_missing_symbols",
            {"VALUE": "loaded_value"},
            current_file=Path(import_guard.__file__),
            fallback_path=fallback,
            fallback_name="agilab_test_import_guard_symbols_fallback",
        )
    finally:
        fallback.unlink(missing_ok=True)

    assert module.VALUE == 11
    assert target_globals["loaded_value"] == 11


def test_pipeline_run_controls_uses_explicit_module_aliases() -> None:
    package_root = Path(import_guard.__file__).resolve().parent
    module_path = package_root / "pipeline_run_controls.py"
    spec = importlib.util.spec_from_file_location("agilab_pipeline_run_controls_test", module_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load pipeline_run_controls.py from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module._pipeline_steps.step_summary)
    assert callable(module._pipeline_runtime.start_mlflow_run)
    assert module._logging_utils.LOG_PATH_LIMIT > 0
    assert not hasattr(module, "_step_summary")
    assert not hasattr(module, "LOG_PATH_LIMIT")
