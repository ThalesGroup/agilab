from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from agi_env.package_layout_support import (
    resolve_agilab_package_context,
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
    )

    assert layout.agilab_pck == site_pkg
    assert layout.env_pck == agi_env_pkg
    assert layout.node_pck == agi_node_pkg
    assert layout.core_pck == agi_env_pkg.parent
    assert layout.cluster_pck == layout.core_pck
    assert layout.cli == layout.cluster_pck / "agi_distributor/cli.py"


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
    )

    assert layout.agilab_pck == site_pkg
    assert calls == ["agi_cluster.agi_distributor.cli"]


def test_resolve_resource_root_prefers_existing_resources_dir(tmp_path):
    agilab_pck = tmp_path / "agilab"
    resources = agilab_pck / "resources"
    resources.mkdir(parents=True)

    assert resolve_resource_root(agilab_pck) == resources
