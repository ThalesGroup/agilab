from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
from typing import Any


def _ensure_agilab_package_path() -> None:
    package_root = Path("src/agilab").resolve()
    package_spec = importlib.util.spec_from_file_location(
        "agilab",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    package = sys.modules.get("agilab")
    if package is None:
        assert package_spec is not None and package_spec.loader is not None
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["agilab"] = package
        package_spec.loader.exec_module(package)
        return

    package_paths = list(getattr(package, "__path__", []) or [])
    package_root_text = str(package_root)
    if package_root_text not in package_paths:
        package.__path__ = [package_root_text, *package_paths]
    package.__spec__ = package_spec
    package.__file__ = str(package_root / "__init__.py")
    package.__package__ = "agilab"


_ensure_agilab_package_path()
runtime_contract = importlib.import_module("agilab.workflow_runtime_contract")


def _state(*, run_status: str = "planned", units: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "run_status": run_status,
        "units": units
        if units is not None
        else [
            {"id": "queue", "dispatch_status": "runnable"},
            {"id": "relay", "dispatch_status": "blocked"},
        ],
        "events": [
            {
                "timestamp": "2026-05-12T08:00:00Z",
                "kind": "run_planned",
                "unit_id": "",
                "from_status": "",
                "to_status": "planned",
                "detail": "created",
            },
            {
                "timestamp": "2026-05-12T08:01:00Z",
                "kind": "unit_dispatched",
                "unit_id": "queue",
                "from_status": "runnable",
                "to_status": "running",
                "detail": "started",
            },
        ],
    }


def test_runtime_contract_exposes_phase_events_and_controls() -> None:
    contract = runtime_contract.build_workflow_runtime_contract(_state())

    assert contract["schema"] == runtime_contract.WORKFLOW_RUNTIME_CONTRACT_SCHEMA
    assert contract["phase"] == "planned"
    assert contract["unit_counts"] == {
        "total": 2,
        "runnable": 1,
        "blocked": 1,
        "running": 0,
        "completed": 0,
        "failed": 0,
    }
    assert contract["event_count"] == 2
    assert contract["last_event"]["kind"] == "unit_dispatched"
    assert runtime_contract.enabled_workflow_control_labels(contract) == (
        "Run next stage",
        "Run ready stages",
        "Pause",
        "Stop",
    )
    assert runtime_contract.validate_workflow_runtime_contract(contract) == ()


def test_runtime_contract_derives_waiting_and_resume_states() -> None:
    waiting = runtime_contract.build_workflow_runtime_contract(
        _state(
            units=[
                {"id": "relay", "dispatch_status": "blocked"},
            ]
        )
    )
    paused = runtime_contract.build_workflow_runtime_contract(_state(run_status="paused"))

    assert waiting["phase"] == "waiting"
    assert runtime_contract.enabled_workflow_control_labels(waiting) == ("Wake", "Stop")
    assert paused["phase"] == "paused"
    assert runtime_contract.enabled_workflow_control_labels(paused) == ("Resume", "Stop")


def test_runtime_contract_prioritizes_actionable_mixed_states() -> None:
    waiting_after_progress = runtime_contract.build_workflow_runtime_contract(
        _state(
            run_status="running",
            units=[
                {"id": "ingest", "dispatch_status": "completed"},
                {"id": "train", "dispatch_status": "blocked"},
            ],
        )
    )
    needs_help = runtime_contract.build_workflow_runtime_contract(
        _state(
            run_status="running",
            units=[
                {"id": "ingest", "dispatch_status": "completed"},
                {"id": "train", "dispatch_status": "needs_help"},
            ],
        )
    )

    assert waiting_after_progress["phase"] == "waiting"
    assert runtime_contract.enabled_workflow_control_labels(waiting_after_progress) == ("Wake", "Stop")
    assert needs_help["phase"] == "needs_help"
    assert runtime_contract.enabled_workflow_control_labels(needs_help) == ("Resume", "Stop")


def test_runtime_contract_validation_reports_bad_shapes() -> None:
    issues = runtime_contract.validate_workflow_runtime_contract(
        {
            "schema": "old",
            "phase": "mystery",
            "controls": [{"label": "", "enabled": "yes"}],
            "event_count": -1,
        }
    )

    assert "runtime contract schema is unsupported" in issues
    assert "runtime phase is unsupported: 'mystery'" in issues
    assert "runtime control #0 id is missing" in issues
    assert "runtime control #0 label is missing" in issues
    assert "runtime control #0 enabled flag must be boolean" in issues
    assert "runtime event_count must be non-negative" in issues
