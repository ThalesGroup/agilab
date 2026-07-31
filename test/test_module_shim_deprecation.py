from __future__ import annotations

import importlib.util
import sys
import warnings
from pathlib import Path
from types import ModuleType

import pytest


MODULE_PATH = Path("src/agilab/compat/module_shim.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("module_shim_deprecation_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _legacy_module(module, legacy_name: str, target_name: str) -> ModuleType:
    legacy = ModuleType(legacy_name)
    legacy.__dict__["activate"] = module.activate_compat_module
    exec(
        "def activate_legacy():\n"
        f"    return activate(__name__, {target_name!r}, legacy_name={legacy_name!r})\n",
        legacy.__dict__,
    )
    return legacy


def test_external_legacy_import_emits_replacement_and_removal_warning(monkeypatch) -> None:
    module = _load_module()
    legacy_name = "agilab.legacy_example"
    target_name = "agilab.workflow.example"
    legacy = _legacy_module(module, legacy_name, target_name)
    target = ModuleType(target_name)
    target.VALUE = 42
    consumer = ModuleType("external_consumer")
    consumer.__dict__["activate_legacy"] = legacy.activate_legacy
    exec("def import_legacy():\n    return activate_legacy()\n", consumer.__dict__)
    monkeypatch.setitem(sys.modules, legacy_name, legacy)
    monkeypatch.setattr(module.importlib, "import_module", lambda name: target)

    with pytest.warns(
        DeprecationWarning,
        match=r"agilab\.legacy_example is deprecated; import agilab\.workflow\.example instead",
    ):
        consumer.import_legacy()

    assert legacy.VALUE == 42


def test_first_party_legacy_import_does_not_emit_deprecation_warning(monkeypatch) -> None:
    module = _load_module()
    legacy_name = "agilab.legacy_example"
    target_name = "agilab.workflow.example"
    legacy = _legacy_module(module, legacy_name, target_name)
    target = ModuleType(target_name)
    consumer = ModuleType("agilab.internal_consumer")
    consumer.__dict__["activate_legacy"] = legacy.activate_legacy
    exec("def import_legacy():\n    return activate_legacy()\n", consumer.__dict__)
    monkeypatch.setitem(sys.modules, legacy_name, legacy)
    monkeypatch.setattr(module.importlib, "import_module", lambda name: target)

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        consumer.import_legacy()

    assert not recorded
