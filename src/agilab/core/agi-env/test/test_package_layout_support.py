from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from agi_env import package_layout_support as pls
from agi_env.package_layout_support import (
    RuntimePackageSpec,
    discover_source_runtime_package_specs,
    load_runtime_package_specs,
    resolve_agilab_package_context,
    resolve_agilab_source_root_from_module_file,
    resolve_package_dir_from_module_file,
    resolve_package_layout,
    resolve_resource_root,
)


def test_resolve_agilab_package_context_prefers_installed_spec(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo" / "src" / "agilab"
    repo_root.mkdir(parents=True)
    site_pkg = tmp_path / ".venv" / "lib" / "python3.13" / "site-packages" / "agilab"
    site_pkg.mkdir(parents=True)
    origin = site_pkg / "__init__.py"
    origin.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(origin)) if name == "agilab" else None,
    )

    context = resolve_agilab_package_context(repo_agilab_dir=repo_root)

    assert context.package_dir == site_pkg.resolve()
    assert context.apps_root_hint == site_pkg.parent.resolve()
    assert context.is_installed is True


def test_resolve_package_layout_installed_falls_back_without_core_or_cluster(tmp_path):
    site_pkg = tmp_path / "site-packages" / "agilab"
    site_pkg.mkdir(parents=True)
    agi_env_pkg = tmp_path / "site-packages" / "agi_env"
    agi_env_pkg.mkdir(parents=True)
    agi_node_pkg = tmp_path / "site-packages" / "agi_node"
    agi_node_pkg.mkdir(parents=True)

    def _resolve(package, *, find_spec_fn=None, path_cls=Path):
        mapping = {
            "agi_env": agi_env_pkg,
            "agi_node": agi_node_pkg,
        }
        if package not in mapping:
            raise ModuleNotFoundError(package)
        return mapping[package]

    layout = resolve_package_layout(
        is_source_env=False,
        repo_agilab_dir=tmp_path / "repo",
        installed_package_dir=site_pkg,
        resolve_package_dir_fn=_resolve,
        find_spec_fn=lambda name: None,
        runtime_package_specs=(
            RuntimePackageSpec(
                role="worker",
                project_dir="worker-project",
                module_name="agi_node",
                cli_rel="dispatcher/cli.py",
            ),
        ),
    )

    assert layout.agilab_pck == site_pkg
    assert layout.env_pck == agi_env_pkg
    assert layout.runtime_packages["worker"].package_pck == agi_node_pkg
    assert layout.cli == agi_node_pkg / "dispatcher/cli.py"


def test_resolve_package_layout_uses_default_find_spec_when_not_provided(tmp_path, monkeypatch):
    site_pkg = tmp_path / "site-packages" / "agilab"
    site_pkg.mkdir(parents=True)
    agi_env_pkg = tmp_path / "site-packages" / "agi_env"
    agi_env_pkg.mkdir(parents=True)
    agi_node_pkg = tmp_path / "site-packages" / "agi_node"
    agi_node_pkg.mkdir(parents=True)

    def _resolve(package, *, find_spec_fn=None, path_cls=Path):
        mapping = {
            "agi_env": agi_env_pkg,
            "agi_node": agi_node_pkg,
        }
        if package not in mapping:
            raise ModuleNotFoundError(package)
        return mapping[package]

    calls: list[str] = []
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: calls.append(name) or None,
    )

    layout = resolve_package_layout(
        is_source_env=False,
        repo_agilab_dir=tmp_path / "repo",
        installed_package_dir=site_pkg,
        resolve_package_dir_fn=_resolve,
        runtime_package_specs=(
            RuntimePackageSpec(role="worker", project_dir="worker-project", module_name="agi_node"),
        ),
    )

    assert layout.agilab_pck == site_pkg
    assert calls == []


def test_source_runtime_package_specs_are_package_owned(tmp_path):
    repo_agilab_dir = tmp_path / "src" / "agilab"
    manifest = repo_agilab_dir / "core" / "worker-project" / "src" / "worker_package" / "agi_env_runtime.py"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "RUNTIME_PACKAGE_SPEC = {\n"
        "    'role': 'worker',\n"
        "    'project_dir': 'worker-project',\n"
        "    'module_name': 'worker_package',\n"
        "    'cli_rel': 'dispatcher/cli.py',\n"
        "}\n",
        encoding="utf-8",
    )

    specs = discover_source_runtime_package_specs(repo_agilab_dir)

    assert specs == (
        RuntimePackageSpec(
            role="worker",
            project_dir="worker-project",
            module_name="worker_package",
            cli_rel="dispatcher/cli.py",
        ),
    )


def test_resolve_package_layout_uses_source_runtime_package_specs(tmp_path):
    repo_agilab_dir = tmp_path / "src" / "agilab"
    manifest = repo_agilab_dir / "core" / "worker-project" / "src" / "worker_package" / "agi_env_runtime.py"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "RUNTIME_PACKAGE_SPEC = {\n"
        "    'role': 'worker',\n"
        "    'project_dir': 'worker-project',\n"
        "    'module_name': 'worker_package',\n"
        "    'cli_rel': 'dispatcher/cli.py',\n"
        "    'worker_pre_install_rel': 'dispatcher/pre_install.py',\n"
        "    'worker_post_install_module': 'worker_package.dispatcher.post_install',\n"
        "}\n",
        encoding="utf-8",
    )

    layout = resolve_package_layout(
        is_source_env=True,
        repo_agilab_dir=repo_agilab_dir,
        installed_package_dir=tmp_path / "site-packages" / "agilab",
        resolve_package_dir_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unused")),
        find_spec_fn=lambda name: None,
    )

    runtime_package = layout.runtime_packages["worker"]
    assert runtime_package.package_pck == manifest.parent
    assert runtime_package.project_pck == repo_agilab_dir / "core" / "worker-project"
    assert layout.cli == manifest.parent / "dispatcher/cli.py"
    assert layout.worker_pre_install == manifest.parent / "dispatcher/pre_install.py"
    assert layout.worker_post_install_module == "worker_package.dispatcher.post_install"


def test_load_runtime_package_specs_uses_entry_points():
    class _EntryPoint:
        def load(self):
            return {
                "role": "worker",
                "project_dir": "worker-project",
                "module_name": "worker_package",
            }

    specs = load_runtime_package_specs(
        repo_agilab_dir=None,
        include_source=False,
        entry_points_fn=lambda group: [_EntryPoint()],
    )

    assert specs == (
        RuntimePackageSpec(
            role="worker",
            project_dir="worker-project",
            module_name="worker_package",
        ),
    )


def test_resolve_resource_root_prefers_existing_resources_dir(tmp_path):
    agilab_pck = tmp_path / "agilab"
    resources = agilab_pck / "resources"
    resources.mkdir(parents=True)

    assert resolve_resource_root(agilab_pck) == resources


def test_resolve_package_dir_from_classified_module_file(tmp_path):
    package_dir = tmp_path / "agi_env"
    module_file = package_dir / "runtime" / "installation_support.py"
    module_file.parent.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    module_file.write_text("", encoding="utf-8")

    assert resolve_package_dir_from_module_file(module_file, "agi_env") == package_dir


def test_resolve_agilab_source_root_handles_classified_and_legacy_paths(tmp_path):
    source_root = tmp_path / "src" / "agilab"
    module_file = source_root / "core" / "agi-env" / "src" / "agi_env" / "runtime" / "agi_env.py"
    module_file.parent.mkdir(parents=True)
    (source_root / "core" / "agi-env").mkdir(parents=True, exist_ok=True)
    (source_root / "apps").mkdir()
    module_file.write_text("", encoding="utf-8")

    assert resolve_agilab_source_root_from_module_file(module_file) == source_root

    legacy_module = tmp_path / "one" / "two" / "three" / "four" / "agi_env.py"
    legacy_module.parent.mkdir(parents=True)
    legacy_module.write_text("", encoding="utf-8")

    assert (
        resolve_agilab_source_root_from_module_file(
            legacy_module,
            legacy_parent_index=4,
        )
        == tmp_path
    )


def test_resolve_agilab_source_root_returns_none_for_short_legacy_path(tmp_path):
    module_file = tmp_path / "agi_env.py"
    module_file.write_text("", encoding="utf-8")

    assert resolve_agilab_source_root_from_module_file(module_file, legacy_parent_index=20) is None


def test_entry_point_discovery_handles_legacy_metadata_api(monkeypatch):
    class _LegacyEntryPoints:
        def get(self, group, default):
            assert group == pls.RUNTIME_PACKAGE_ENTRY_POINT_GROUP
            assert default == ()
            return ()

    monkeypatch.setattr(pls.importlib_metadata, "entry_points", lambda: _LegacyEntryPoints())

    assert load_runtime_package_specs(repo_agilab_dir=None, include_source=False) == ()


def test_source_runtime_package_specs_skip_unloadable_manifest(tmp_path, monkeypatch):
    repo_agilab_dir = tmp_path / "src" / "agilab"
    manifest = repo_agilab_dir / "core" / "worker-project" / "src" / "worker_package" / "agi_env_runtime.py"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("RUNTIME_PACKAGE_SPEC = {}\n", encoding="utf-8")
    monkeypatch.setattr(pls.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)

    assert discover_source_runtime_package_specs(repo_agilab_dir) == ()


def test_runtime_package_spec_coercion_accepts_callable_object_and_none():
    class _SpecObject:
        role = "worker"
        project_dir = "worker-project"
        module_name = "worker_package"
        order = 5

    class _EntryPoint:
        def __init__(self, raw_spec):
            self._raw_spec = raw_spec

        def load(self):
            return self._raw_spec

    specs = load_runtime_package_specs(
        repo_agilab_dir=None,
        include_source=False,
        entry_points_fn=lambda _group: [
            _EntryPoint(lambda: None),
            _EntryPoint(RuntimePackageSpec(role="existing", project_dir="existing-project", module_name="existing_pkg")),
            _EntryPoint(_SpecObject()),
        ],
    )

    assert specs == (
        RuntimePackageSpec(role="worker", project_dir="worker-project", module_name="worker_package", order=5),
        RuntimePackageSpec(role="existing", project_dir="existing-project", module_name="existing_pkg"),
    )


def test_load_runtime_package_specs_skips_broken_entry_points():
    class _BrokenEntryPoint:
        def __init__(self, error):
            self._error = error

        def load(self):
            raise self._error

    class _ValidEntryPoint:
        def load(self):
            return {"role": "worker", "project_dir": "worker-project", "module_name": "worker_package"}

    specs = load_runtime_package_specs(
        repo_agilab_dir=None,
        include_source=False,
        entry_points_fn=lambda _group: [
            _BrokenEntryPoint(AttributeError("broken")),
            _BrokenEntryPoint(ImportError("broken")),
            _BrokenEntryPoint(ModuleNotFoundError("broken")),
            _ValidEntryPoint(),
        ],
    )

    assert specs == (RuntimePackageSpec(role="worker", project_dir="worker-project", module_name="worker_package"),)


def test_resolve_package_layout_skips_missing_installed_runtime_package(tmp_path):
    site_pkg = tmp_path / "site-packages" / "agilab"
    env_pkg = tmp_path / "site-packages" / "agi_env"
    site_pkg.mkdir(parents=True)
    env_pkg.mkdir(parents=True)

    def _resolve(package, *, find_spec_fn=None, path_cls=Path):
        if package == "agi_env":
            return env_pkg
        raise ModuleNotFoundError(package)

    layout = resolve_package_layout(
        is_source_env=False,
        repo_agilab_dir=tmp_path / "repo",
        installed_package_dir=site_pkg,
        resolve_package_dir_fn=_resolve,
        runtime_package_specs=(
            RuntimePackageSpec(role="worker", project_dir="worker-project", module_name="missing_worker"),
        ),
    )

    assert layout.runtime_packages == {}
