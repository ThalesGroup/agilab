from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import threading
import types

import pytest

_IMPORT_GUARD_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "agilab" / "security" / "import_guard.py"
)
_SRC_ROOT = _IMPORT_GUARD_PATH.parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))
_IMPORT_GUARD_SPEC = importlib.util.spec_from_file_location("agilab_import_guard_test", _IMPORT_GUARD_PATH)
if _IMPORT_GUARD_SPEC is None or _IMPORT_GUARD_SPEC.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_IMPORT_GUARD_PATH}")
import_guard = importlib.util.module_from_spec(_IMPORT_GUARD_SPEC)
_IMPORT_GUARD_SPEC.loader.exec_module(import_guard)


def _load_independent_import_guard(name: str):
    spec = importlib.util.spec_from_file_location(name, _IMPORT_GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repo_src_root_is_not_a_python_package() -> None:
    assert not (_SRC_ROOT / "__init__.py").exists()


def _ensure_repo_agilab_package() -> None:
    """Make real-package imports deterministic when pytest installed a shim."""
    package_root = str(_SRC_ROOT / "agilab")
    package = sys.modules.get("agilab")
    if package is None or not hasattr(package, "__path__"):
        package = types.ModuleType("agilab")
        package.__path__ = [package_root]  # type: ignore[attr-defined]
        sys.modules["agilab"] = package
    else:
        package_paths = list(package.__path__)  # type: ignore[attr-defined]
        if package_root not in package_paths:
            package.__path__ = [package_root, *package_paths]  # type: ignore[attr-defined]
    package.__file__ = str(_SRC_ROOT / "agilab" / "__init__.py")
    package.__package__ = "agilab"
    package.__spec__ = importlib.util.spec_from_file_location(
        "agilab",
        _SRC_ROOT / "agilab" / "__init__.py",
        submodule_search_locations=[package_root],
    )
    importlib.invalidate_caches()


def _make_source_package(root: Path) -> Path:
    package = root / "src" / "agilab"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "main_page.py").write_text("", encoding="utf-8")
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


def test_fallback_load_restores_previous_module_after_failure(tmp_path: Path) -> None:
    fallback_name = "agilab_broken_fallback_test"
    previous = types.ModuleType(fallback_name)
    broken = tmp_path / "broken.py"
    broken.write_text("raise RuntimeError('broken fallback')\n", encoding="utf-8")
    sys.modules[fallback_name] = previous
    try:
        with pytest.raises(RuntimeError, match="broken fallback"):
            import_guard._load_module_from_path(
                "agilab.broken",
                broken,
                fallback_name=fallback_name,
            )
        assert sys.modules[fallback_name] is previous
    finally:
        sys.modules.pop(fallback_name, None)


def test_independent_import_guards_serialize_fallback_execution(tmp_path: Path) -> None:
    first_guard = _load_independent_import_guard("agilab_import_guard_concurrency_one")
    second_guard = _load_independent_import_guard("agilab_import_guard_concurrency_two")
    assert first_guard.FALLBACK_LOAD_LOCK is second_guard.FALLBACK_LOAD_LOCK

    state_name = "agilab_import_guard_concurrency_state"
    fallback_name = "agilab_import_guard_concurrency_fallback"
    state = types.ModuleType(state_name)
    state.counter_lock = threading.Lock()
    state.active = 0
    state.maximum = 0
    fallback = tmp_path / "concurrent.py"
    fallback.write_text(
        "\n".join(
            [
                "import time",
                f"import {state_name} as state",
                "with state.counter_lock:",
                "    state.active += 1",
                "    state.maximum = max(state.maximum, state.active)",
                "try:",
                "    time.sleep(0.05)",
                "finally:",
                "    with state.counter_lock:",
                "        state.active -= 1",
                "VALUE = True",
                "",
            ]
        ),
        encoding="utf-8",
    )
    start = threading.Barrier(2)
    failures: list[BaseException] = []

    def _load(guard) -> None:
        try:
            start.wait(timeout=2.0)
            guard._load_module_from_path(
                "agilab.concurrent",
                fallback,
                fallback_name=fallback_name,
            )
        except BaseException as exc:  # pragma: no cover - asserted below.
            failures.append(exc)

    sys.modules[state_name] = state
    try:
        threads = [
            threading.Thread(target=_load, args=(guard,))
            for guard in (first_guard, second_guard)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)
        assert not any(thread.is_alive() for thread in threads)
        assert failures == []
        assert state.maximum == 1
    finally:
        sys.modules.pop(state_name, None)
        sys.modules.pop(fallback_name, None)


def test_import_guard_bootstraps_before_rejecting_foreign_agilab_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    foreign_package = tmp_path / "foreign" / "agilab"
    foreign_package.mkdir(parents=True)
    (foreign_package / "__init__.py").write_text("", encoding="utf-8")
    foreign = types.ModuleType("agilab")
    foreign.__file__ = str(foreign_package / "__init__.py")
    foreign.__path__ = [str(foreign_package)]
    monkeypatch.setitem(sys.modules, "agilab", foreign)

    guard = _load_independent_import_guard("agilab_import_guard_foreign_bootstrap")

    with pytest.raises(guard.MixedCheckoutImportError, match="Mixed AGILAB checkout"):
        guard.assert_agilab_checkout_alignment(_IMPORT_GUARD_PATH)


def test_import_guard_rejects_invalid_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "_agilab_import_guard_process_state",
        types.ModuleType("_agilab_import_guard_process_state"),
    )

    with pytest.raises(RuntimeError, match="Invalid AGILAB import-guard process state"):
        _load_independent_import_guard("agilab_import_guard_invalid_process_state")


def test_import_agilab_symbols_refreshes_stale_compat_shim_from_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_target = types.ModuleType("agilab.classified_stale")
    stale_target.VALUE = "stale"
    stale_shim = types.ModuleType("agilab.legacy_stale")
    stale_shim.VALUE = "stale"
    stale_shim._AGILAB_COMPAT_TARGET_MODULE = stale_target
    refreshed = types.ModuleType("agilab_stale_fallback")
    refreshed.__file__ = str(_SRC_ROOT / "agilab" / "app_surface.py")
    refreshed.VALUE = "fresh"
    refreshed.ADDED = "available"
    fallback_calls: list[tuple[str, Path, str | None]] = []

    monkeypatch.setattr(
        import_guard,
        "import_agilab_module",
        lambda *_args, **_kwargs: stale_shim,
    )

    def _load_fallback(module_name, fallback_path, fallback_name=None):
        fallback_calls.append((module_name, Path(fallback_path), fallback_name))
        return refreshed

    monkeypatch.setattr(import_guard, "_load_module_from_path", _load_fallback)
    target_globals: dict[str, object] = {}

    loaded = import_guard.import_agilab_symbols(
        target_globals,
        "agilab.legacy_stale",
        {"VALUE": "value", "ADDED": "added"},
        current_file=_SRC_ROOT / "agilab" / "pages" / "2_ORCHESTRATE.py",
        fallback_path=_SRC_ROOT / "agilab" / "app_surface.py",
        fallback_name="agilab_app_surface_fallback",
    )

    assert loaded is refreshed
    assert target_globals == {"value": "fresh", "added": "available"}
    assert fallback_calls == [
        (
            "agilab.legacy_stale",
            _SRC_ROOT / "agilab" / "app_surface.py",
            "agilab_app_surface_fallback",
        )
    ]


def test_import_agilab_symbols_rejects_external_compat_refresh_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stale_target = types.ModuleType("agilab.classified_stale")
    stale_shim = types.ModuleType("agilab.legacy_stale")
    stale_shim._AGILAB_COMPAT_TARGET_MODULE = stale_target
    external_fallback = tmp_path / "outside.py"
    external_fallback.write_text(
        "raise AssertionError('external fallback must not execute')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        import_guard,
        "import_agilab_module",
        lambda *_args, **_kwargs: stale_shim,
    )

    with pytest.raises(import_guard.MixedCheckoutImportError, match="Mixed AGILAB"):
        import_guard.import_agilab_symbols(
            {},
            "agilab.legacy_stale",
            ["ADDED"],
            current_file=_SRC_ROOT / "agilab" / "pages" / "2_ORCHESTRATE.py",
            fallback_path=external_fallback,
        )


def test_import_agilab_symbols_recovers_stale_shim_and_stale_agi_env_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agi_env.runtime import import_layout_support
    import agilab.app_surface as stale_shim

    monkeypatch.delattr(stale_shim, "app_editable_import_roots")
    monkeypatch.delattr(
        import_layout_support,
        "hosted_editable_source_import_roots",
    )
    app = tmp_path / "demo_project"
    target_globals: dict[str, object] = {}

    import_guard.import_agilab_symbols(
        target_globals,
        "agilab.app_surface",
        ["app_editable_import_roots"],
        current_file=_SRC_ROOT / "agilab" / "pages" / "2_ORCHESTRATE.py",
        fallback_path=_SRC_ROOT / "agilab" / "app_surface.py",
        fallback_name="agilab_app_surface_hot_refresh_test",
    )

    recovered = target_globals["app_editable_import_roots"]
    assert callable(recovered)
    assert recovered(app) == (app.resolve() / "src",)


def test_python_environment_alignment_rejects_other_source_root(tmp_path, monkeypatch) -> None:
    current_package = _make_source_package(tmp_path / "current")
    other_root = tmp_path / "other"
    _make_source_package(other_root)
    current_file = current_package / "main_page.py"

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
    current_file = current_package / "main_page.py"
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
    current_file = current_package / "main_page.py"

    monkeypatch.setattr(sys, "executable", str(current_root / ".venv" / "bin" / "python"))

    assert import_guard.assert_python_environment_alignment(current_file) == current_package.resolve()


def test_sys_path_alignment_rejects_other_source_root(tmp_path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_package = _make_source_package(current_root)
    other_root = tmp_path / "other"
    _make_source_package(other_root)
    current_file = current_package / "main_page.py"

    monkeypatch.setattr(sys, "path", [str(current_root / "src"), str(other_root / "src")])

    with pytest.raises(import_guard.MixedCheckoutImportError, match="Mixed AGILAB sys.path"):
        import_guard.assert_sys_path_checkout_alignment(current_file)


def test_sys_path_alignment_reports_stale_venv_site_packages(tmp_path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_package = _make_source_package(current_root)
    other_root = tmp_path / "other"
    _make_source_package(other_root)
    current_file = current_package / "main_page.py"
    other_site_packages = other_root / ".venv" / "lib" / "python3.13" / "site-packages"

    monkeypatch.setattr(sys, "path", [str(current_root / "src"), str(other_site_packages)])

    with pytest.raises(import_guard.MixedCheckoutImportError, match="virtualenv site-packages"):
        import_guard.assert_sys_path_checkout_alignment(current_file)


def test_sys_path_alignment_allows_matching_source_root(tmp_path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_package = _make_source_package(current_root)
    current_file = current_package / "main_page.py"

    monkeypatch.setattr(sys, "path", [str(current_root), str(current_root / "src")])

    assert import_guard.assert_sys_path_checkout_alignment(current_file) == current_package.resolve()


def test_import_agilab_module_reports_wrong_python_before_stale_sys_path(tmp_path, monkeypatch) -> None:
    current_root = tmp_path / "current"
    current_package = _make_source_package(current_root)
    other_root = tmp_path / "other"
    _make_source_package(other_root)
    current_file = current_package / "main_page.py"
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
    _ensure_repo_agilab_package()
    module = importlib.import_module("agilab.pipeline_run_controls")

    assert callable(module._pipeline_stages.stage_summary)
    assert callable(module._pipeline_runtime.start_mlflow_run)
    assert callable(module._pipeline_runtime.start_tracker_run)
    assert module._logging_utils.LOG_PATH_LIMIT > 0
    assert not hasattr(module, "_stage_summary")
    assert not hasattr(module, "LOG_PATH_LIMIT")


def test_import_guard_low_level_edge_branches(tmp_path, monkeypatch) -> None:
    package_root = _make_source_package(tmp_path / "current")
    current_file = package_root / "main_page.py"

    with pytest.raises(RuntimeError, match="Unable to resolve"):
        import_guard.resolve_package_root(tmp_path / "outside.py")

    module = types.SimpleNamespace(
        __file__=str(package_root / "__init__.py"),
        __path__=[str(package_root), str(package_root)],
    )
    assert import_guard._module_origin_paths(module) == [
        (package_root / "__init__.py").resolve(),
        package_root.resolve(),
    ]

    monkeypatch.delitem(sys.modules, "agilab", raising=False)
    assert import_guard.assert_agilab_checkout_alignment(current_file) == package_root.resolve()

    assert import_guard._source_root_for_package_root(Path("/agilab")) is None
    assert import_guard._source_root_for_package_root(tmp_path / "not" / "src" / "agilab") is None
    assert import_guard._source_root_for_python_executable("/usr/bin/python") is None
    assert import_guard._source_root_for_python_executable(".venv/bin/python") is None
    flat_package = tmp_path / "flat" / "agilab"
    flat_package.mkdir(parents=True)
    (flat_package / "__init__.py").write_text("", encoding="utf-8")
    (flat_package / "main_page.py").write_text("", encoding="utf-8")
    assert import_guard.assert_sys_path_checkout_alignment(flat_package / "main_page.py") == flat_package.resolve()
    assert import_guard._should_fallback_module_not_found(
        ModuleNotFoundError(name="agilab.sub.dependency"),
        "agilab.target",
        "agilab",
    ) is True


def test_import_guard_import_error_and_symbol_edges(tmp_path, monkeypatch) -> None:
    package_root = _make_source_package(tmp_path / "current")
    current_file = package_root / "main_page.py"
    fallback = package_root / "fallback.py"
    fallback.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "current" / ".venv" / "bin" / "python"))
    monkeypatch.setattr(sys, "path", [str(tmp_path / "current" / "src")])
    monkeypatch.setitem(
        sys.modules,
        "agilab",
        types.SimpleNamespace(__file__=str(package_root / "__init__.py"), __path__=[str(package_root)]),
    )

    def _raise_dependency_missing(_module_name):
        raise ModuleNotFoundError("missing dependency", name="external_dependency")

    monkeypatch.setattr(import_guard.importlib, "import_module", _raise_dependency_missing)
    with pytest.raises(ModuleNotFoundError, match="missing dependency"):
        import_guard.import_agilab_module(
            "agilab.target",
            current_file=current_file,
            fallback_path=fallback,
        )

    outside_module = types.ModuleType("agilab.outside")
    outside_root = tmp_path / "outside" / "agilab"
    outside_root.mkdir(parents=True)
    outside_file = outside_root / "outside.py"
    outside_file.write_text("", encoding="utf-8")
    outside_module.__file__ = str(outside_file)
    monkeypatch.setattr(import_guard.importlib, "import_module", lambda _name: outside_module)
    with pytest.raises(import_guard.MixedCheckoutImportError, match="Mixed AGILAB checkout"):
        import_guard.import_agilab_module(
            "agilab.outside",
            current_file=current_file,
            fallback_path=fallback,
        )

    def _raise_import_error(_module_name):
        raise ImportError("boom")

    monkeypatch.setattr(import_guard.importlib, "import_module", _raise_import_error)
    with pytest.raises(ImportError, match="boom"):
        import_guard.import_agilab_module(
            "agilab.boom",
            current_file=current_file,
            fallback_path=fallback,
        )

    def _raise_import_error_with_mixed(_module_name):
        monkeypatch.setitem(
            sys.modules,
            "agilab",
            types.SimpleNamespace(__file__=str(outside_file), __path__=[str(outside_root)]),
        )
        raise ImportError("boom")

    monkeypatch.setattr(import_guard.importlib, "import_module", _raise_import_error_with_mixed)
    with pytest.raises(import_guard.MixedCheckoutImportError):
        import_guard.import_agilab_module(
            "agilab.mixed",
            current_file=current_file,
            fallback_path=fallback,
        )

    fallback.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        import_guard,
        "import_agilab_module",
        lambda *_args, **_kwargs: types.SimpleNamespace(VALUE=1),
    )
    target_globals: dict[str, object] = {}
    import_guard.import_agilab_symbols(
        target_globals,
        "agilab.symbols",
        ["VALUE"],
        current_file=current_file,
        fallback_path=fallback,
    )
    assert target_globals["VALUE"] == 1
    with pytest.raises(ImportError, match="cannot import name"):
        import_guard.import_agilab_symbols(
            {},
            "agilab.symbols",
            ["MISSING"],
            current_file=current_file,
            fallback_path=fallback,
        )
