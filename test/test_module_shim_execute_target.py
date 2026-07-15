"""Regression for finding #19: the exec fallback must not re-run module bodies.

``_execute_target_in_current_module`` (in ``src/agilab/compat/module_shim.py``)
executes the target module's source into the caller namespace. Before the fix
it never registered ``sys.modules[target_name]``, so a later normal ``import``
of the target re-executed its body and duplicated module-level side effects.

This test loads the real helper, execs a temp target into a throwaway namespace,
then imports the target normally and asserts its body ran only once.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

_MODULE_SHIM_PATH = (
    Path(__file__).resolve().parents[1] / "src/agilab/compat/module_shim.py"
)


def _load_module_shim():
    spec = importlib.util.spec_from_file_location(
        "agilab_compat_module_shim_under_test", _MODULE_SHIM_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_execute_target_registers_sys_modules_to_avoid_double_execution(
    tmp_path, monkeypatch
):
    module_shim = _load_module_shim()

    # Build a temp importable package with a target module that records every
    # time its body executes.
    pkg_root = tmp_path / "shimpkg"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    target_src = pkg_root / "target.py"
    target_src.write_text(
        "import sys\n"
        "sys.modules.setdefault('_shim_exec_counter', []).append(1)\n"
        "VALUE = 7\n",
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    # Ensure a clean slate for the counter and target module.
    for name in ("_shim_exec_counter", "shimpkg.target"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    target_name = "shimpkg.target"
    namespace: dict[str, object] = {"__name__": "legacy.alias"}

    result = module_shim._execute_target_in_current_module(
        "legacy.alias", target_name, namespace=namespace
    )

    # Exec fallback returns None (it populated the namespace in place).
    assert result is None
    assert namespace["VALUE"] == 7
    # Body ran exactly once so far.
    assert len(sys.modules["_shim_exec_counter"]) == 1
    # The target is now cached so a later import reuses it.
    assert target_name in sys.modules

    reimported = importlib.import_module(target_name)
    assert reimported.VALUE == 7
    # Crucially, the body did NOT run a second time.
    assert len(sys.modules["_shim_exec_counter"]) == 1


def test_execute_target_registers_target_spec_instead_of_legacy_spec(
    tmp_path, monkeypatch
):
    module_shim = _load_module_shim()

    pkg_root = tmp_path / "shimpkg_metadata"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    target_src = pkg_root / "target.py"
    target_src.write_text("VALUE = 9\n", encoding="utf-8")
    legacy_src = tmp_path / "legacy_alias.py"
    legacy_src.write_text("# synthetic compatibility shim\n", encoding="utf-8")

    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    target_name = "shimpkg_metadata.target"
    monkeypatch.delitem(sys.modules, target_name, raising=False)
    legacy_spec = importlib.util.spec_from_file_location("legacy.alias", legacy_src)
    assert legacy_spec and legacy_spec.loader
    namespace: dict[str, object] = {
        "__name__": "legacy.alias",
        "__package__": "legacy",
        "__file__": str(legacy_src),
        "__loader__": legacy_spec.loader,
        "__spec__": legacy_spec,
    }

    module_shim._execute_target_in_current_module(
        "legacy.alias", target_name, namespace=namespace
    )

    registered = sys.modules[target_name]
    assert registered.__name__ == target_name
    assert registered.__package__ == "shimpkg_metadata"
    assert registered.__file__ == str(target_src)
    assert registered.__spec__ is not None
    assert registered.__spec__.name == target_name
    assert registered.__spec__.origin == str(target_src)
    assert importlib.util.find_spec(target_name).origin == str(target_src)

    second_namespace = dict(namespace)
    second_namespace.pop("VALUE", None)
    module_shim._execute_target_in_current_module(
        "legacy.second_alias", target_name, namespace=second_namespace
    )
    assert second_namespace["VALUE"] == 9


def test_execute_target_does_not_clobber_in_progress_import(tmp_path, monkeypatch):
    module_shim = _load_module_shim()

    pkg_root = tmp_path / "shimpkg2"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    (pkg_root / "target.py").write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    target_name = "shimpkg2.target"
    monkeypatch.delitem(sys.modules, target_name, raising=False)

    # Pre-seed sys.modules to simulate an in-progress / already-present import.
    sentinel = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(target_name, loader=None)
    )
    sentinel.VALUE = "pre-existing"
    monkeypatch.setitem(sys.modules, target_name, sentinel)

    namespace: dict[str, object] = {"__name__": "legacy.alias2"}
    module_shim._execute_target_in_current_module(
        "legacy.alias2", target_name, namespace=namespace
    )

    # The pre-existing entry must be left untouched.
    assert sys.modules[target_name] is sentinel
    assert sys.modules[target_name].VALUE == "pre-existing"
