from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

_IMPORT_GUARD_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "import_guard.py"
_IMPORT_GUARD_SPEC = importlib.util.spec_from_file_location("agilab_import_guard_test", _IMPORT_GUARD_PATH)
if _IMPORT_GUARD_SPEC is None or _IMPORT_GUARD_SPEC.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_IMPORT_GUARD_PATH}")
import_guard = importlib.util.module_from_spec(_IMPORT_GUARD_SPEC)
_IMPORT_GUARD_SPEC.loader.exec_module(import_guard)


def _make_source_package(root: Path) -> Path:
    package = root / "src" / "agilab"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "About_agilab.py").write_text("", encoding="utf-8")
    return package


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


def test_python_environment_alignment_rejects_other_source_root(tmp_path, monkeypatch) -> None:
    current_package = _make_source_package(tmp_path / "current")
    other_root = tmp_path / "other"
    _make_source_package(other_root)
    current_file = current_package / "About_agilab.py"

    monkeypatch.setattr(sys, "executable", str(other_root / ".venv" / "bin" / "python"))

    with pytest.raises(import_guard.MixedCheckoutImportError) as exc_info:
        import_guard.assert_python_environment_alignment(current_file)

    message = str(exc_info.value)
    assert "Mixed AGILAB Python environment detected." in message
    assert "AGILAB is being launched from one source checkout" in message
    assert f"- Expected checkout: {tmp_path / 'current'}" in message
    assert f"- Detected Python checkout: {other_root}" in message
    assert "How to fix this checkout:" in message
    assert "AGILAB_PYCHARM_ALLOW_SDK_REBIND=1" in message
    assert "Expected PyCharm uv SDK path (macOS/Linux):" in message
    assert "Expected PyCharm uv SDK path (Windows):" in message
    assert "Windows PowerShell:" in message


def test_python_environment_alignment_rejects_symlinked_uv_python(tmp_path, monkeypatch) -> None:
    current_package = _make_source_package(tmp_path / "current")
    other_root = tmp_path / "other"
    _make_source_package(other_root)
    current_file = current_package / "About_agilab.py"
    other_python = other_root / ".venv" / "bin" / "python"
    other_python.parent.mkdir(parents=True)
    try:
        other_python.symlink_to(sys.executable)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    monkeypatch.setattr(sys, "executable", str(other_python))

    with pytest.raises(import_guard.MixedCheckoutImportError, match="sys.executable"):
        import_guard.assert_python_environment_alignment(current_file)


def test_python_environment_alignment_allows_matching_source_root(tmp_path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_package = _make_source_package(current_root)
    current_file = current_package / "About_agilab.py"

    monkeypatch.setattr(sys, "executable", str(current_root / ".venv" / "bin" / "python"))

    assert import_guard.assert_python_environment_alignment(current_file) == current_package.resolve()


def test_sys_path_alignment_rejects_other_source_root(tmp_path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_package = _make_source_package(current_root)
    other_root = tmp_path / "other"
    _make_source_package(other_root)
    current_file = current_package / "About_agilab.py"

    monkeypatch.setattr(sys, "path", [str(current_root / "src"), str(other_root / "src")])

    with pytest.raises(import_guard.MixedCheckoutImportError, match="Mixed AGILAB sys.path"):
        import_guard.assert_sys_path_checkout_alignment(current_file)


def test_sys_path_alignment_reports_stale_venv_site_packages(tmp_path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_package = _make_source_package(current_root)
    other_root = tmp_path / "other"
    _make_source_package(other_root)
    current_file = current_package / "About_agilab.py"
    other_site_packages = other_root / ".venv" / "lib" / "python3.13" / "site-packages"

    monkeypatch.setattr(sys, "path", [str(current_root / "src"), str(other_site_packages)])

    with pytest.raises(import_guard.MixedCheckoutImportError, match="virtualenv site-packages"):
        import_guard.assert_sys_path_checkout_alignment(current_file)


def test_sys_path_alignment_allows_matching_source_root(tmp_path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_package = _make_source_package(current_root)
    current_file = current_package / "About_agilab.py"

    monkeypatch.setattr(sys, "path", [str(current_root), str(current_root / "src")])

    assert import_guard.assert_sys_path_checkout_alignment(current_file) == current_package.resolve()


def test_import_agilab_module_reports_wrong_python_before_stale_sys_path(tmp_path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_package = _make_source_package(current_root)
    other_root = tmp_path / "other"
    _make_source_package(other_root)
    current_file = current_package / "About_agilab.py"
    other_site_packages = other_root / ".venv" / "lib" / "python3.13" / "site-packages"
    fallback = current_package / "unused_fallback.py"
    fallback.write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(sys, "executable", str(other_root / ".venv" / "bin" / "python"))
    monkeypatch.setattr(sys, "path", [str(current_root / "src"), str(other_site_packages)])

    with pytest.raises(import_guard.MixedCheckoutImportError, match="Mixed AGILAB Python environment"):
        import_guard.import_agilab_module(
            "agilab.test_missing_wrong_python",
            current_file=current_file,
            fallback_path=fallback,
        )


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
    assert callable(module._pipeline_runtime.start_tracker_run)
    assert module._logging_utils.LOG_PATH_LIMIT > 0
    assert not hasattr(module, "_step_summary")
    assert not hasattr(module, "LOG_PATH_LIMIT")
