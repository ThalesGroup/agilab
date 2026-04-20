from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SERVICE_RUNTIME_SUPPORT_PATH = (
    Path(__file__).resolve().parents[4]
    / "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/service_runtime_support.py"
)


def test_service_runtime_support_reexports_service_helpers(monkeypatch):
    source_path = _SERVICE_RUNTIME_SUPPORT_PATH

    agi_cluster_pkg = ModuleType("agi_cluster")
    agi_cluster_pkg.__path__ = []  # type: ignore[attr-defined]
    distributor_pkg = ModuleType("agi_cluster.agi_distributor")
    distributor_pkg.__path__ = []  # type: ignore[attr-defined]

    lifecycle_module = ModuleType("agi_cluster.agi_distributor.service_lifecycle_support")
    state_module = ModuleType("agi_cluster.agi_distributor.service_state_support")

    lifecycle_exports = {
        "serve",
        "service_auto_restart_unhealthy",
        "service_recover",
        "service_restart_workers",
        "submit",
        "wrap_worker_chunk",
    }
    state_exports = {
        "init_service_queue",
        "reset_service_queue_state",
        "service_apply_queue_root",
        "service_apply_runtime_config",
        "service_cleanup_artifacts",
        "service_clear_state",
        "service_connected_workers",
        "service_finalize_response",
        "service_health_path",
        "service_health_payload",
        "service_heartbeat_timeout_value",
        "service_public_args",
        "service_queue_counts",
        "service_queue_paths",
        "service_read_heartbeat_payloads",
        "service_read_heartbeats",
        "service_read_state",
        "service_safe_worker_name",
        "service_state_path",
        "service_state_payload",
        "service_unhealthy_workers",
        "service_worker_health",
        "service_write_health_payload",
        "service_write_state",
    }

    expected_exports = {}
    for name in lifecycle_exports:
        sentinel = object()
        setattr(lifecycle_module, name, sentinel)
        expected_exports[name] = sentinel
    for name in state_exports:
        sentinel = object()
        setattr(state_module, name, sentinel)
        expected_exports[name] = sentinel

    monkeypatch.setitem(sys.modules, "agi_cluster", agi_cluster_pkg)
    monkeypatch.setitem(sys.modules, "agi_cluster.agi_distributor", distributor_pkg)
    monkeypatch.setitem(sys.modules, "agi_cluster.agi_distributor.service_lifecycle_support", lifecycle_module)
    monkeypatch.setitem(sys.modules, "agi_cluster.agi_distributor.service_state_support", state_module)

    spec = importlib.util.spec_from_file_location(
        "agi_cluster.agi_distributor.service_runtime_support",
        source_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    assert set(module.__all__) == set(expected_exports)
    assert len(module.__all__) == len(set(module.__all__))
    for name, exported in expected_exports.items():
        assert getattr(module, name) is exported
