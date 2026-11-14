"""SDK source selection follows the executing package, not its venv ancestors."""

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

import pytest

from agi_node.agi_dispatcher import bootstrap_source_paths as bootstrap
import agi_cluster.agi_distributor.agi_distributor as distributor


@pytest.mark.parametrize(
    "venv_relative",
    [
        ".venv",
        "deep/build/env",
        "src/agilab/apps/probe_project/.venv",
        "src/agilab/core/agi-node/tests/env",
    ],
)
def test_installed_package_does_not_bootstrap_checkout_sdk(tmp_path, venv_relative):
    repo = tmp_path / "repo"
    node_src = repo / "src/agilab/core/agi-node/src"
    node_src.mkdir(parents=True)
    prefix = repo / venv_relative
    package = (
        prefix
        / "lib/python3.13/site-packages/agi_cluster/agi_distributor/api/agi_distributor.py"
    )
    package.parent.mkdir(parents=True)
    package.write_text("")
    paths = ["installed-canary", "other"]
    assert (
        distributor._bootstrap_node_src(
            sys_path=paths,
            sys_prefix=prefix,
            source_file=package,
        )
        is None
    )
    assert paths == ["installed-canary", "other"]
    assert (
        bootstrap.package_source_path_candidates(
            "agi-node",
            sys_prefix=prefix,
            source_file=package,
        )
        == ()
    )


def test_source_package_without_global_marker_selects_its_own_checkout(tmp_path):
    repo = tmp_path / "source"
    source = (
        repo
        / "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/api/agi_distributor.py"
    )
    source.parent.mkdir(parents=True)
    source.write_text("")
    node_src = repo / "src/agilab/core/agi-node/src"
    node_src.mkdir(parents=True)
    foreign_src = tmp_path / "other/agi-node/src"
    foreign_src.mkdir(parents=True)
    assert (
        bootstrap.resolve_node_source_path(
            sys_prefix=foreign_src.parents[1],
            source_file=source,
        )
        == node_src
    )


def test_unresolvable_package_does_not_guess_source_from_prefix(tmp_path, monkeypatch):
    node_src = tmp_path / "repo/agi-node/src"
    node_src.mkdir(parents=True)
    original = Path.resolve

    def broken(self, *args, **kwargs):
        if self.name == "broken.py":
            raise OSError("source unavailable")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", broken)
    assert (
        bootstrap.resolve_node_source_path(
            sys_prefix=tmp_path / "repo",
            source_file=tmp_path / "broken.py",
        )
        is None
    )


def test_symlink_to_installed_package_does_not_select_source(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src/agilab/core/agi-node/src").mkdir(parents=True)
    installed = repo / ".venv/lib/python3.13/site-packages/agi_node/build.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("")
    alias = tmp_path / "module_alias.py"
    alias.symlink_to(installed)
    assert (
        bootstrap.resolve_node_source_path(
            sys_prefix=repo / ".venv",
            source_file=alias,
        )
        is None
    )


@pytest.mark.parametrize("selected", [False, True])
def test_explicit_source_environment_controls_foreign_package(tmp_path, selected):
    node_src = tmp_path / "runtime/agi-node/src"
    node_src.mkdir(parents=True)
    source = tmp_path / "runtime/lib/python3.13/site-packages/agi_node/build.py"
    source.parent.mkdir(parents=True)
    source.write_text("")
    assert bootstrap.resolve_node_source_path(
        sys_prefix=tmp_path / "runtime",
        source_file=source,
        is_source_env=selected,
    ) == (node_src if selected else None)


def test_source_alias_uses_package_identity_and_absent_sibling_is_not_injected(
    tmp_path,
):
    source = tmp_path / "repo/src/agilab/core/agi-cluster/src/agi_cluster/api.py"
    source.parent.mkdir(parents=True)
    source.write_text("")
    alias = tmp_path / "source_alias.py"
    alias.symlink_to(source)
    node_src = tmp_path / "repo/src/agilab/core/agi-node/src"
    assert bootstrap.resolve_node_source_path(source_file=alias) is None
    node_src.mkdir(parents=True)
    assert bootstrap.resolve_node_source_path(source_file=alias) == node_src
    assert (
        bootstrap.resolve_node_source_path(source_file=alias, is_source_env=False)
        is None
    )


def test_installed_bootstrap_ignores_ambient_checkout_marker(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    node_src = repo / "src/agilab/core/agi-node/src"
    node_src.mkdir(parents=True)
    marker = tmp_path / ".local/share/agilab/.agilab-path"
    marker.parent.mkdir(parents=True)
    marker.write_text(str(repo / "src/agilab"))
    source = repo / ".venv/lib/python3.13/site-packages/agi_cluster/api.py"
    source.parent.mkdir(parents=True)
    source.write_text("")
    monkeypatch.delenv("IS_SOURCE_ENV", raising=False)
    assert (
        bootstrap.resolve_node_source_path(
            source_file=source,
            sys_prefix=repo / ".venv",
        )
        is None
    )


@pytest.fixture
def mixed_sdk_origins(tmp_path):
    """Real SDK code in distinguishable source and installed package layouts."""
    core = Path(__file__).resolve().parents[1]
    source = tmp_path / "source/src/agilab/core"
    installed = tmp_path / "wheel/lib/python3/site-packages"
    for package in ("agi-node", "agi-cluster"):
        namespace = package.replace("-", "_")
        shutil.copytree(
            core / package / "src" / namespace,
            source / package / "src" / namespace,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    shutil.copytree(source / "agi-node/src/agi_node", installed / "agi_node")
    for base, version, canary in (
        (source / "agi-node/src", "0.0.2", "source"),
        (installed, "0.0.1", "wheel"),
    ):
        metadata = base / f"agi_node-{version}.dist-info"
        metadata.mkdir(parents=True)
        (metadata / "METADATA").write_text(f"Name: agi-node\nVersion: {version}\n")
        for module, cls in (
            ("base_worker", "BaseWorker"),
            ("agi_dispatcher", "WorkDispatcher"),
        ):
            path = base / "agi_node/agi_dispatcher" / (module + ".py")
            with path.open("a") as stream:
                stream.write(f"\n{cls}.origin_canary = {canary!r}\n")
    return source, installed, core / "agi-env/src"


@pytest.mark.parametrize(
    "mode",
    [
        "mixed",
        "mixed-unset",
        "all-source",
        "all-source-unset",
        "disabled",
        "loaded-incompatible",
    ],
)
def test_fresh_cluster_import_keeps_actual_node_and_metadata_coherent(
    mixed_sdk_origins, mode
):
    source, installed, env_src = mixed_sdk_origins
    code = r"""
import importlib, importlib.metadata, json, os, pathlib, sys
source, installed, env_src = map(pathlib.Path, sys.argv[1:4])
mode = sys.argv[4]
sys.path[:] = [p for p in sys.path if not any(
    part in p for part in ("agi-node/src", "agi-cluster/src", "agi-env/src")
)]
sys.path[:0] = [str(source / "agi-cluster/src"), str(installed), str(env_src)]
if mode.startswith("all-source"):
    sys.path.insert(0, str(source / "agi-node/src"))
os.environ["IS_SOURCE_ENV"] = "0" if mode == "disabled" else "1"
if mode.endswith("-unset"):
    os.environ.pop("IS_SOURCE_ENV")
if mode == "loaded-incompatible":
    from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher
    old_paths = list(sys.path)
    old_metadata = str(importlib.metadata.distribution("agi-node")._path)
    try:
        importlib.import_module("agi_cluster.agi_distributor.api.agi_distributor")
    except (ImportError, RuntimeError) as exc:
        assert "already loaded" in str(exc) and "fresh" in str(exc), str(exc)
    else:
        raise AssertionError("incompatible already-loaded node was accepted")
    assert sys.path == old_paths
    assert str(importlib.metadata.distribution("agi-node")._path) == old_metadata
    from agi_node.agi_dispatcher import BaseWorker as current
    assert current is BaseWorker
    assert BaseWorker.origin_canary == WorkDispatcher.origin_canary == "wheel"
else:
    distributor = importlib.import_module("agi_cluster.agi_distributor.api.agi_distributor")
    expected = installed if mode == "disabled" else source / "agi-node/src"
    for cls in (distributor.BaseWorker, distributor.WorkDispatcher):
        module = importlib.import_module(cls.__module__)
        assert pathlib.Path(module.__file__).resolve().is_relative_to(expected), module.__file__
        assert cls.origin_canary == ("wheel" if mode == "disabled" else "source")
    dist = importlib.metadata.distribution("agi-node")
    assert pathlib.Path(dist._path).resolve().is_relative_to(expected), str(dist._path)
    assert dist.version == ("0.0.1" if mode == "disabled" else "0.0.2")
print(json.dumps({"mode": mode, "ok": True}))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            code,
            str(source),
            str(installed),
            str(env_src),
            mode,
        ],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {"mode": mode, "ok": True}
