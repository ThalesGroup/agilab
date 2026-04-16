from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/impact_validate.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("impact_validate_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_analyze_paths_flags_shared_core_and_gui_actions() -> None:
    module = _load_module()

    report = module.analyze_paths(
        [
            "src/agilab/core/agi-env/src/agi_env/bootstrap_support.py",
            "src/agilab/orchestrate_execute.py",
        ]
    )

    assert report.overall_risk == "high"
    assert any(zone.key == "shared-core" for zone in report.risk_zones)
    assert any(gate.key == "shared-core-approval" for gate in report.push_gates)
    assert any(action.key == "agi-env-tests" for action in report.required_validations)
    targeted = next(action for action in report.required_validations if action.key == "targeted-pytest")
    assert "test/test_orchestrate_execute.py" in targeted.commands[0]
    gui_parity = next(
        action for action in report.required_validations if action.key == "workflow-parity-agi-gui"
    )
    assert "tools/workflow_parity.py --profile agi-gui" in gui_parity.commands[0]


def test_analyze_paths_adds_skill_sync_and_index_refresh() -> None:
    module = _load_module()

    report = module.analyze_paths(
        [".claude/skills/codex-session-learning/SKILL.md", ".codex/skills/README.md"]
    )

    assert report.overall_risk == "medium"
    artifact = next(action for action in report.artifact_actions if action.key == "skill-sync")
    assert artifact.commands[0] == "python3 tools/sync_agent_skills.py --skills codex-session-learning"
    assert "python3 tools/codex_skills.py --root .codex/skills validate --strict" in artifact.commands
    assert "python3 tools/codex_skills.py --root .codex/skills generate" in artifact.commands
    parity = next(action for action in report.artifact_actions if action.key == "workflow-parity-skills")
    assert "tools/workflow_parity.py --profile skills" in parity.commands[0]


def test_analyze_paths_adds_badge_refresh_with_component_hint() -> None:
    module = _load_module()

    report = module.analyze_paths(
        [
            "tools/generate_component_coverage_badges.py",
            "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py",
        ]
    )

    artifact = next(action for action in report.artifact_actions if action.key == "badge-refresh")
    assert any("test/test_generate_component_coverage_badges.py" in command for command in artifact.commands)
    assert any("--components agi-gui" in command for command in artifact.commands)
    parity = next(action for action in report.artifact_actions if action.key == "workflow-parity-badges")
    assert "tools/workflow_parity.py --profile badges" in parity.commands[0]


def test_main_json_output_for_explicit_files(capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--files",
            ".idea/runConfigurations/agilab_run_dev.xml",
            "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_risk"] == "medium"
    assert any(zone["key"] == "runconfig" for zone in payload["risk_zones"])
    assert any(action["key"] == "runconfig-regenerate" for action in payload["artifact_actions"])
    assert "test/test_view_maps_network.py" in payload["guessed_tests"]


def test_analyze_paths_adds_install_contract_check_for_install_entrypoint() -> None:
    module = _load_module()

    report = module.analyze_paths(["src/agilab/apps/install.py"])

    assert report.overall_risk == "high"
    assert any(gate.key == "install-contract" for gate in report.push_gates)
    contract_check = next(
        action for action in report.required_validations if action.key == "install-contract-check"
    )
    assert "tools/install_contract_check.py" in contract_check.commands[0]
    parity = next(
        action for action in report.required_validations if action.key == "workflow-parity-installer"
    )
    assert "tools/workflow_parity.py --profile installer" in parity.commands[0]


def test_analyze_paths_adds_docs_workflow_parity_for_docs_source() -> None:
    module = _load_module()

    report = module.analyze_paths(["docs/source/faq.rst"])

    artifact = next(action for action in report.artifact_actions if action.key == "workflow-parity-docs")
    assert "tools/workflow_parity.py --profile docs" in artifact.commands[0]
