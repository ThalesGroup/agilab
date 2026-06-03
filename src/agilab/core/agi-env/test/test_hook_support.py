from contextlib import contextmanager
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


def test_resolve_worker_hook_handles_repo_fallback_oserror_and_propagates_runtime_bug(tmp_path: Path, monkeypatch):
    hook_support.resolve_worker_hook.cache_clear()
    monkeypatch.setattr(hook_support.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(
        hook_support.importlib_resources,
        "files",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("missing resources")),
    )

    original_exists = Path.exists

    def _oserror_exists(self):
        if self.name == "pre_install.py":
            raise OSError("exists failed")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _oserror_exists, raising=False)
    assert hook_support.resolve_worker_hook(
        "pre_install.py",
        module_file=str(tmp_path / "repo" / "pkg" / "one" / "two" / "agi_env.py"),
    ) is None

    hook_support.resolve_worker_hook.cache_clear()

    def _runtime_exists(self):
        if self.name == "pre_install.py":
            raise RuntimeError("exists bug")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _runtime_exists, raising=False)
    with pytest.raises(RuntimeError, match="exists bug"):
        hook_support.resolve_worker_hook(
            "pre_install.py",
            module_file=str(tmp_path / "repo" / "pkg" / "one" / "two" / "agi_env.py"),
        )


def test_resolve_worker_hook_handles_non_init_origin_and_missing_resource(tmp_path: Path, monkeypatch):
    hook_support.resolve_worker_hook.cache_clear()
    module_file = tmp_path / "one" / "two" / "three" / "four" / "agi_env.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")
    missing_resource_root = tmp_path / "resources"
    missing_resource_root.mkdir()

    monkeypatch.setattr(
        hook_support.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(
            submodule_search_locations=[""],
            origin=str(tmp_path / "installed" / "module.py"),
        ),
    )
    monkeypatch.setattr(hook_support.importlib_resources, "files", lambda _name: missing_resource_root)

    assert hook_support.resolve_worker_hook("pre_install.py", module_file=str(module_file)) is None


def test_resolve_worker_hook_handles_missing_spec_origin(tmp_path: Path, monkeypatch):
    hook_support.resolve_worker_hook.cache_clear()
    module_file = tmp_path / "one" / "two" / "three" / "four" / "agi_env.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")
    missing_resource_root = tmp_path / "resources"
    missing_resource_root.mkdir()

    monkeypatch.setattr(
        hook_support.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(submodule_search_locations=[], origin=None),
    )
    monkeypatch.setattr(hook_support.importlib_resources, "files", lambda _name: missing_resource_root)

    assert hook_support.resolve_worker_hook("pre_install.py", module_file=str(module_file)) is None


def test_resolve_worker_hook_uses_repo_package_fallback(tmp_path: Path, monkeypatch):
    hook_support.resolve_worker_hook.cache_clear()
    module_file = tmp_path / "one" / "two" / "three" / "four" / "agi_env.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")
    pkg_hook = tmp_path / "core" / "agi-node" / "agi_dispatcher" / "pre_install.py"
    pkg_hook.parent.mkdir(parents=True)
    pkg_hook.write_text("print('pkg')\n", encoding="utf-8")

    monkeypatch.setattr(hook_support.importlib.util, "find_spec", lambda _name: None)

    assert hook_support.resolve_worker_hook("pre_install.py", module_file=str(module_file)) == pkg_hook


def test_resolve_worker_hook_handles_cached_resource_without_copy_and_missing_as_file(tmp_path: Path, monkeypatch):
    resource_root = tmp_path / "resources"
    resource_root.mkdir()
    resource_hook = resource_root / "post_install.py"
    resource_hook.write_text("print('resource')\n", encoding="utf-8")
    cache_parent = tmp_path / "cache-parent"
    cache_parent.mkdir()
    cached = cache_parent / "agi_node_hooks" / "post_install.py"
    cached.parent.mkdir(parents=True)
    cached.write_text("print('cached')\n", encoding="utf-8")

    hook_support.resolve_worker_hook.cache_clear()
    monkeypatch.setattr(hook_support.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(hook_support.importlib_resources, "files", lambda _name: resource_root)
    monkeypatch.setattr(hook_support.tempfile, "gettempdir", lambda: str(cache_parent))

    @contextmanager
    def _yield_cached(_resource):
        yield cached

    monkeypatch.setattr(hook_support.importlib_resources, "as_file", _yield_cached)
    monkeypatch.setattr(hook_support.shutil, "copy2", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("copy should not run")))

    assert hook_support.resolve_worker_hook(
        "post_install.py",
        module_file=str(tmp_path / "sandbox" / "nested" / "agi_env.py"),
    ) == cached

    hook_support.resolve_worker_hook.cache_clear()

    @contextmanager
    def _missing_as_file(_resource):
        raise FileNotFoundError("gone")
        yield  # pragma: no cover

    monkeypatch.setattr(hook_support.importlib_resources, "as_file", _missing_as_file)

    assert hook_support.resolve_worker_hook(
        "post_install.py",
        module_file=str(tmp_path / "sandbox" / "nested" / "agi_env.py"),
    ) is None
