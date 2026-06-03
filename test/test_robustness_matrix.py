from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "robustness_matrix.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("robustness_matrix_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_robustness_matrix_p0_passes_against_current_contracts() -> None:
    module = _load_module()

    report = module.build_report(repo_root=Path.cwd())

    assert report["schema"] == module.SCHEMA
    assert report["status"] == "pass"
    assert report["profile"] == "p0"
    assert report["summary"]["scenario_count"] >= 10
    assert report["summary"]["failed"] == 0
    assert report["summary"]["cleanup_status"] == "removed"
    scenarios = {scenario["id"]: scenario for scenario in report["scenarios"]}
    assert scenarios["cluster_share_same_as_local_fails_closed"]["status"] == "pass"
    assert scenarios["cluster_share_missing_fails_closed"]["status"] == "pass"
    assert scenarios["public_streamlit_bind_without_controls_refused"]["status"] == "pass"
    assert scenarios["missing_run_manifest_fails_verification"]["status"] == "pass"
    assert scenarios["invalid_notebook_import_fails_preflight"]["status"] == "pass"
    assert scenarios["streamlit_routes_do_not_hardcode_pages_directory"]["status"] == "pass"
    assert "replay_command" in scenarios["invalid_run_manifest_fails_verification"]


def test_robustness_matrix_reports_synthetic_failed_scenario() -> None:
    module = _load_module()

    def _bad_state_was_accepted(_repo_root: Path, _tmp_root: Path):
        return module.ScenarioObservation(
            passed=False,
            observed="bad state was accepted",
            details={"accepted": True},
        )

    scenario = module.RobustnessScenario(
        id="synthetic_bad_state",
        domain="test",
        fault="Synthetic bad state.",
        expected_behavior="Reject the bad state.",
        remediation="Fix the synthetic scenario.",
        replay_command="python tools/robustness_matrix.py --scenario synthetic_bad_state",
        runner=_bad_state_was_accepted,
    )

    report = module.build_report(repo_root=Path.cwd(), scenario_specs=[scenario])

    assert report["status"] == "fail"
    assert report["summary"]["failed"] == 1
    assert report["scenarios"][0]["status"] == "fail"
    assert report["scenarios"][0]["observed"] == "bad state was accepted"
    assert report["scenarios"][0]["cleanup_status"] == "removed"


def test_robustness_matrix_unknown_scenario_returns_cli_usage_error(capsys) -> None:
    module = _load_module()

    code = module.main(["--scenario", "does_not_exist", "--compact"])

    captured = capsys.readouterr()
    assert code == 2
    assert "Unknown robustness scenario" in captured.err
    assert captured.out == ""


def test_robustness_matrix_cli_writes_output_and_compact_json(tmp_path: Path, capsys) -> None:
    module = _load_module()
    output = tmp_path / "robustness.json"

    code = module.main(
        [
            "--scenario",
            "public_streamlit_bind_without_controls_refused",
            "--output",
            str(output),
            "--compact",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    stdout_payload = json.loads(captured.out)
    persisted_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["status"] == "pass"
    assert persisted_payload["status"] == "pass"
    assert stdout_payload["summary"]["scenario_count"] == 1
    assert persisted_payload["scenarios"][0]["id"] == "public_streamlit_bind_without_controls_refused"


def test_robustness_matrix_lists_scenarios(capsys) -> None:
    module = _load_module()

    code = module.main(["--list-scenarios"])

    captured = capsys.readouterr()
    assert code == 0
    assert "cluster_share_same_as_local_fails_closed\tcluster" in captured.out
    assert "streamlit_routes_do_not_hardcode_pages_directory\tui-routing" in captured.out
