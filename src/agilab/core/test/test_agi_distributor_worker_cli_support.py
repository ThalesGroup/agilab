from __future__ import annotations

from types import SimpleNamespace

from agi_cluster.agi_distributor.api.worker_cli_support import resolve_worker_cli_path


def test_resolve_worker_cli_path_prefers_node_owned_env_cli(tmp_path):
    node_cli = tmp_path / "agi_node" / "agi_dispatcher" / "cli.py"
    cluster_pck = tmp_path / "agi_cluster"

    assert resolve_worker_cli_path(SimpleNamespace(cli=node_cli, cluster_pck=cluster_pck)) == node_cli


def test_resolve_worker_cli_path_keeps_legacy_cluster_env_fallback(tmp_path):
    cluster_pck = tmp_path / "agi_cluster"

    assert resolve_worker_cli_path(SimpleNamespace(cluster_pck=cluster_pck)) == (
        cluster_pck / "agi_distributor" / "cli.py"
    )
