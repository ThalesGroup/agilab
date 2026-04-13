from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import agi_env.hook_support as hook_support


def test_select_hook_prefers_local_candidate_and_fallback(tmp_path: Path):
    local_hook = tmp_path / "pre_install.py"
    local_hook.write_text("print('local')\n", encoding="utf-8")

    selected, shared = hook_support.select_hook(
        local_hook,
        "pre_install.py",
        "pre_install",
        resolve_hook=lambda _name: None,
    )
    assert selected == local_hook
    assert shared is False

    fallback = tmp_path / "shared.py"
    fallback.write_text("print('shared')\n", encoding="utf-8")
    missing = tmp_path / "missing.py"
    selected, shared = hook_support.select_hook(
        missing,
        "pre_install.py",
        "pre_install",
        resolve_hook=lambda _name: fallback,
    )
    assert selected == fallback
    assert shared is True


def test_select_hook_raises_when_no_candidate_found(tmp_path: Path):
    missing = tmp_path / "missing.py"

    with pytest.raises(FileNotFoundError, match="Unable to resolve pre_install script"):
        hook_support.select_hook(
            missing,
            "pre_install.py",
            "pre_install",
            resolve_hook=lambda _name: None,
        )


def test_resolve_worker_hook_prefers_installed_spec_location_and_resource_cache(tmp_path: Path, monkeypatch):
    installed_dir = tmp_path / "installed" / "agi_dispatcher"
    installed_dir.mkdir(parents=True)
    installed_hook = installed_dir / "pre_install.py"
    installed_hook.write_text("print('installed')\n", encoding="utf-8")

    hook_support.resolve_worker_hook.cache_clear()
    monkeypatch.setattr(
        hook_support.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(
            submodule_search_locations=[str(installed_dir)],
            origin=str(installed_dir / "__init__.py"),
        ),
    )
    assert hook_support.resolve_worker_hook("pre_install.py", module_file=str(tmp_path / "x" / "agi_env.py")) == installed_hook

    resource_root = tmp_path / "resources"
    resource_root.mkdir()
    resource_hook = resource_root / "post_install.py"
    resource_hook.write_text("print('resource')\n", encoding="utf-8")
    cache_parent = tmp_path / "cache-parent"
    cache_parent.mkdir()

    hook_support.resolve_worker_hook.cache_clear()
    monkeypatch.setattr(hook_support.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(hook_support.importlib_resources, "files", lambda _name: resource_root)
    monkeypatch.setattr(hook_support.tempfile, "gettempdir", lambda: str(cache_parent))

    resolved = hook_support.resolve_worker_hook(
        "post_install.py",
        module_file=str(tmp_path / "sandbox" / "nested" / "agi_env.py"),
    )

    assert resolved == cache_parent / "agi_node_hooks" / "post_install.py"
    assert resolved.read_text(encoding="utf-8") == "print('resource')\n"


def test_worker_hook_none_when_resource_missing(monkeypatch, tmp_path: Path):
    hook_support.resolve_worker_hook.cache_clear()
    monkeypatch.setattr(
        hook_support.importlib.util,
        "find_spec",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("missing")),
    )
    monkeypatch.setattr(
        hook_support.importlib_resources,
        "files",
        lambda _name: (_ for _ in ()).throw(AttributeError("no resources")),
    )
    with mock.patch.object(hook_support.Path, "exists", lambda self: False):
        assert hook_support.resolve_worker_hook(
            "pre_install.py",
            module_file=str(tmp_path / "sandbox" / "nested" / "agi_env.py"),
        ) is None

