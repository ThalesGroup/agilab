"""Cluster executor choices respect only usable discovered worker platforms."""

import json

import pytest

from agilab.orchestrate import orchestrate_cluster as cluster


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("", ""),
        ("Win32", "windows"),
        ("NT", "windows"),
        ("Windows Server 2025", "windows"),
        ("Mac OS X", "darwin"),
        ("Darwin-24", "darwin"),
        ("Linux x86_64", "linux"),
        ("FreeBSD 14", "freebsd14"),
    ],
)
def test_pool_platform_normalization_handles_discovery_labels(raw, expected):
    assert cluster._pool_executor_platform_family(raw) == expected


@pytest.mark.parametrize("nodes", [None, "invalid", {"worker": "linux"}])
def test_cluster_executor_ignores_non_list_node_payload(tmp_path, nodes):
    path = tmp_path / "lan.json"
    path.write_text(json.dumps({"nodes": nodes}))
    assert cluster._lan_discovery_ready_worker_os_families(path) == ()
    options, explanation = cluster._pool_executor_options_for_cluster_os(
        path, local_system=""
    )
    assert options == cluster.POOL_EXECUTOR_OPTIONS
    assert explanation == ""


def test_cluster_executor_filters_failed_nodes_and_deduplicates_os_aliases(tmp_path):
    path = tmp_path / "lan.json"
    path.write_text(
        json.dumps(
            {
                "nodes": [
                    None,
                    "invalid",
                    {"status": "failed", "os_name": "Windows"},
                    {"status": "ready", "platform": "Linux"},
                    {"os": "linux-gnu"},
                    {"status": "ready", "system": "MacOS"},
                    {"status": "ready"},
                ]
            }
        )
    )
    assert cluster._lan_discovery_ready_worker_os_families(path) == ("linux", "darwin")
    options, explanation = cluster._pool_executor_options_for_cluster_os(
        path, local_system="Linux"
    )
    assert "process" in options
    assert explanation == ""


def test_local_windows_alone_restricts_process_executor(tmp_path):
    path = tmp_path / "lan.json"
    path.write_text('{"nodes":[]}')
    options, explanation = cluster._pool_executor_options_for_cluster_os(
        path, local_system="Windows"
    )
    assert options == cluster.POOL_EXECUTOR_OS_SAFE_OPTIONS
    assert "process" not in options
    assert "Windows" in explanation
