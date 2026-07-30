from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from agi_env.runtime import hot_source_support


@pytest.fixture(autouse=True)
def _isolate_hot_source_cache():
    hot_source_support._clear_aligned_module_cache()
    yield
    hot_source_support._clear_aligned_module_cache()


def test_aligned_module_callable_returns_existing_callable() -> None:
    module = ModuleType("agi_env.runtime.current")

    def existing() -> str:
        return "current"

    module.existing = existing

    assert hot_source_support.aligned_module_callable(module, "existing") is existing


def test_aligned_module_callable_loads_current_aligned_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "agi_env"
    source = package_root / "runtime" / "stale.py"
    source.parent.mkdir(parents=True)
    source.write_text("def added():\n    return 'fresh'\n", encoding="utf-8")
    stale = ModuleType("agi_env.runtime.stale")
    stale.__file__ = str(source)
    monkeypatch.setattr(hot_source_support, "_AGI_ENV_PACKAGE_ROOT", package_root)
    hot_source_support._clear_aligned_module_cache()

    resolved = hot_source_support.aligned_module_callable(stale, "added")

    assert resolved() == "fresh"


def test_aligned_module_callable_rejects_external_source_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "agi_env"
    package_root.mkdir()
    external = tmp_path / "external.py"
    external.write_text(
        "raise AssertionError('external source must not execute')\n",
        encoding="utf-8",
    )
    stale = ModuleType("agi_env.runtime.stale")
    stale.__file__ = str(external)
    monkeypatch.setattr(hot_source_support, "_AGI_ENV_PACKAGE_ROOT", package_root)

    with pytest.raises(
        hot_source_support.StaleRuntimeModuleError,
        match="outside the active agi_env package root",
    ):
        hot_source_support.aligned_module_callable(stale, "added")


def test_failed_aligned_source_load_does_not_leave_partial_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "agi_env"
    source = package_root / "runtime" / "broken.py"
    source.parent.mkdir(parents=True)
    source.write_text("raise RuntimeError('broken source')\n", encoding="utf-8")
    stale = ModuleType("agi_env.runtime.broken")
    stale.__file__ = str(source)
    monkeypatch.setattr(hot_source_support, "_AGI_ENV_PACKAGE_ROOT", package_root)
    hot_source_support._clear_aligned_module_cache()
    before = set(sys.modules)

    with pytest.raises(
        hot_source_support.StaleRuntimeModuleError,
        match="Unable to execute aligned runtime source",
    ):
        hot_source_support.aligned_module_callable(stale, "added")

    assert not {
        name for name in set(sys.modules) - before if name.startswith("agi_env.runtime._hot_source_")
    }


def test_aligned_module_cache_uses_source_content_not_file_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "agi_env"
    source = package_root / "runtime" / "stale.py"
    source.parent.mkdir(parents=True)
    stale = ModuleType("agi_env.runtime.stale")
    stale.__file__ = str(source)
    monkeypatch.setattr(hot_source_support, "_AGI_ENV_PACKAGE_ROOT", package_root)
    hot_source_support._clear_aligned_module_cache()
    source.write_text("def added():\n    return 'first'\n", encoding="utf-8")
    initial_stat = source.stat()

    first = hot_source_support.aligned_module_callable(stale, "added")
    source.write_text("def added():\n    return 'other'\n", encoding="utf-8")
    os.utime(source, ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns))
    second = hot_source_support.aligned_module_callable(stale, "added")

    assert first() == "first"
    assert second() == "other"


def test_identical_sources_at_different_paths_keep_distinct_module_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_root = tmp_path / "agi_env"
    sources = [
        package_root / "runtime" / "first.py",
        package_root / "runtime" / "second.py",
    ]
    for source in sources:
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("def added():\n    return __name__\n", encoding="utf-8")
    modules = [ModuleType(f"agi_env.runtime.{source.stem}") for source in sources]
    for module, source in zip(modules, sources, strict=True):
        module.__file__ = str(source)
    monkeypatch.setattr(hot_source_support, "_AGI_ENV_PACKAGE_ROOT", package_root)

    resolved = [
        hot_source_support.aligned_module_callable(module, "added")
        for module in modules
    ]

    assert resolved[0]() != resolved[1]()
