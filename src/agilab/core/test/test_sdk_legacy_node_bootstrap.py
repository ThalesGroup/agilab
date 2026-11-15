"""Source cluster bootstraps before a released node's older policy API."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("source_mode", [None, "1", "0"])
def test_source_cluster_uses_own_policy_with_legacy_installed_node(
    tmp_path, source_mode
):
    core = tmp_path / "repo" / "src" / "agilab" / "core"
    cluster = core / "agi-cluster" / "src" / "agi_cluster" / "agi_distributor" / "api"
    cluster.mkdir(parents=True)
    module = cluster / "node_source_bootstrap.py"
    shutil.copy2(
        ROOT
        / "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/api/node_source_bootstrap.py",
        module,
    )
    node = core / "agi-node" / "src" / "agi_node"
    (node / "agi_dispatcher").mkdir(parents=True)
    (node / "__init__.py").write_text(
        "raise AssertionError('node initializer executed too early')\n",
        encoding="utf-8",
    )
    shutil.copy2(
        ROOT
        / "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/bootstrap_source_paths.py",
        node / "agi_dispatcher" / "bootstrap_source_paths.py",
    )
    installed = tmp_path / "site-packages"
    package = installed / "agi_node"
    (package / "agi_dispatcher").mkdir(parents=True)
    (package / "__init__.py").write_text(
        "raise AssertionError('installed initializer executed too early')\n",
        encoding="utf-8",
    )
    # This is the released resolver ABI, not a new helper relabelled as old.
    (package / "agi_dispatcher" / "bootstrap_source_paths.py").write_text(
        "def resolve_node_source_path(*, sys_prefix=None, source_file=None):\n"
        "    raise AssertionError('legacy policy selected before source bootstrap')\n",
        encoding="utf-8",
    )
    code = (
        "import sys,runpy,json\n"
        f"sys.path.insert(0, {str(installed)!r})\n"
        f"ns=runpy.run_path({str(module)!r})\n"
        "print(json.dumps({'node_src':ns['_node_src'],'node_loaded':'agi_node' in sys.modules}))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGI_", "AGILAB_"))}
    env.pop("IS_SOURCE_ENV", None)
    if source_mode is not None:
        env["IS_SOURCE_ENV"] = source_mode
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    expected = None if source_mode == "0" else str(node.parent)
    assert observed == {"node_src": expected, "node_loaded": False}


@pytest.mark.parametrize("layout", ["site-packages", "custom-target"])
@pytest.mark.parametrize("policy", ["legacy", "current"])
@pytest.mark.parametrize("source_mode", [None, "0", "1"])
def test_installed_cluster_handles_node_policy_abi_without_source_redirection(
    tmp_path, layout, policy, source_mode
):
    installed = tmp_path / layout
    cluster = installed / "agi_cluster" / "agi_distributor" / "api"
    cluster.mkdir(parents=True)
    module = cluster / "node_source_bootstrap.py"
    shutil.copy2(
        ROOT / "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/api/node_source_bootstrap.py",
        module,
    )
    node = installed / "agi_node"
    (node / "agi_dispatcher").mkdir(parents=True)
    (node / "__init__.py").write_text("raise AssertionError('early initializer')\n", encoding="utf-8")
    bootstrap = node / "agi_dispatcher" / "bootstrap_source_paths.py"
    if policy == "legacy":
        bootstrap.write_text(
            "def resolve_node_source_path(*, sys_prefix=None, source_file=None):\n"
            "    raise AssertionError('legacy permissive source search must not run')\n",
            encoding="utf-8",
        )
    else:
        shutil.copy2(
            ROOT / "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/bootstrap_source_paths.py",
            bootstrap,
        )
    prefix = tmp_path / "selected-prefix"
    candidate = prefix / "agi-node" / "src"
    candidate.mkdir(parents=True)
    code = (
        "import sys,runpy,json\n"
        f"sys.path.insert(0, {str(installed)!r})\n"
        f"sys.prefix = {str(prefix)!r}\n"
        f"ns=runpy.run_path({str(module)!r})\n"
        "print(json.dumps({'node_src':ns['_node_src'],'node_loaded':'agi_node' in sys.modules}))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGI_", "AGILAB_"))}
    env.pop("IS_SOURCE_ENV", None)
    if source_mode is not None:
        env["IS_SOURCE_ENV"] = source_mode
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code],
        env=env, capture_output=True, text=True, timeout=20,
    )
    if policy == "legacy" and source_mode == "1":
        assert result.returncode != 0
        assert "same source snapshot" in result.stderr
        assert "TypeError" not in result.stderr
        assert "legacy permissive source search" not in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        expected = str(candidate) if policy == "current" and source_mode == "1" else None
        assert json.loads(result.stdout) == {"node_src": expected, "node_loaded": False}
