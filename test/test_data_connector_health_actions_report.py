from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_health_actions_report.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_health_actions_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_health_actions_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_health_actions.json",
    )

    assert report["report"] == "Data connector health actions report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_health_actions.v1"
    assert report["summary"]["run_status"] == "ready_for_operator_trigger"
    assert report["summary"]["execution_mode"] == "operator_trigger_contract_only"
    assert report["summary"]["action_count"] == 5
    assert report["summary"]["connector_count"] == 5
    assert report["summary"]["operator_trigger_count"] == 5
    assert report["summary"]["pending_action_count"] == 5
    assert report["summary"]["pending_operator_trigger_count"] == 5
    assert report["summary"]["executed_probe_count"] == 0
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["operator_context_required_count"] == 5
    assert report["summary"]["credential_gated_count"] == 4
    assert report["summary"]["no_credential_required_count"] == 1
    assert report["summary"]["probe_types"] == [
        "bucket_prefix_list",
        "driver_connectivity",
        "index_head",
    ]
    assert report["summary"]["default_status_values"] == ["unknown_not_probed"]
    assert report["summary"]["result_status_values"] == ["unknown_not_probed"]
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_health_actions_schema",
        "data_connector_health_actions_rows",
        "data_connector_health_actions_operator_trigger",
        "data_connector_health_actions_no_network",
        "data_connector_health_actions_credential_boundary",
        "data_connector_health_actions_persistence",
        "data_connector_health_actions_docs_reference",
    }


def test_data_connector_health_actions_persist_trigger_rows(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_health_actions_json_test_module")
    output_path = tmp_path / "data_connector_health_actions.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=output_path)

    assert report["status"] == "pass"
    payload = module.json.loads(output_path.read_text(encoding="utf-8"))
    actions = payload["actions"]
    assert {action["trigger_mode"] for action in actions} == {"operator_explicit_opt_in"}
    assert {action["execution_status"] for action in actions} == {
        "not_executed_awaiting_operator"
    }
    assert {action["ui_control"] for action in actions} == {"button"}
    assert {action["default_status"] for action in actions} == {"unknown_not_probed"}
    assert sum(1 for action in actions if action["requires_credentials"]) == 4
    assert sum(1 for action in actions if not action["requires_credentials"]) == 1
    assert all(action["network_probe_executed"] is False for action in actions)
    assert all(action["safe_for_public_evidence"] is True for action in actions)
