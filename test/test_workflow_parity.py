from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("tools/workflow_parity.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("workflow_parity_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_profile_commands_cover_expected_coverage_and_docs_contracts() -> None:
    module = _load_module()
    args = SimpleNamespace(components=None, skills=None, app_path=None, worker_copy=None)

    profiles = module._profile_commands(args)
    agi_env = profiles["agi-env"][0]
    agi_core_combined = profiles["agi-core-combined"]
    agi_node = profiles["agi-node"][0]
    agi_cluster = profiles["agi-cluster"][0]
    agi_gui = profiles["agi-gui"][0]
    docs = profiles["docs"][0]
    badges = profiles["badges"]
    strict_typing = profiles["shared-core-typing"][0]

    assert agi_env.timeout_seconds == 20 * 60
    assert agi_env.env["COVERAGE_FILE"] == ".coverage.agi-env"
    assert "--cov=agi_env" in agi_env.argv
    assert "coverage-agi-env.xml" in " ".join(agi_env.argv)
    assert agi_env.argv[-1] == "src/agilab/core/agi-env/test"

    assert len(agi_core_combined) == 3
    combined_run = agi_core_combined[0]
    combined_node_xml = agi_core_combined[1]
    combined_cluster_xml = agi_core_combined[2]
    assert combined_run.timeout_seconds == 20 * 60
    assert combined_run.argv[-1] == "src/agilab/core/test"
    assert "--data-file=.coverage.agi-core-combined" in combined_run.argv
    assert "pytest" in combined_run.argv
    assert combined_node_xml.timeout_seconds == 5 * 60
    assert "--data-file=.coverage.agi-core-combined" in combined_node_xml.argv
    assert "-o" in combined_node_xml.argv
    assert "coverage-agi-node.xml" in combined_node_xml.argv
    assert "--include=*/agi_node/*" in combined_node_xml.argv
    assert combined_cluster_xml.timeout_seconds == 5 * 60
    assert "--data-file=.coverage.agi-core-combined" in combined_cluster_xml.argv
    assert "-o" in combined_cluster_xml.argv
    assert "coverage-agi-cluster.xml" in combined_cluster_xml.argv
    assert "--include=*/agi_cluster/*" in combined_cluster_xml.argv

    assert agi_node.timeout_seconds == 20 * 60
    assert agi_node.env["COVERAGE_FILE"] == ".coverage.agi-node"
    assert "--cov=agi_node" in agi_node.argv
    assert "coverage-agi-node.xml" in " ".join(agi_node.argv)
    assert agi_node.argv[-1] == "src/agilab/core/test"

    assert agi_cluster.timeout_seconds == 20 * 60
    assert agi_cluster.env["COVERAGE_FILE"] == ".coverage.agi-cluster"
    assert "--cov=agi_cluster" in agi_cluster.argv
    assert "coverage-agi-cluster.xml" in " ".join(agi_cluster.argv)
    assert agi_cluster.argv[-1] == "src/agilab/core/test"

    assert agi_gui.timeout_seconds == 12 * 60
    assert agi_gui.env["AGILAB_DISABLE_BACKGROUND_SERVICES"] == "1"
    assert "coverage-agi-gui.xml" in " ".join(agi_gui.argv)
    assert "test/test_about_agilab_helpers.py" in agi_gui.argv
    assert "test/test_cluster_flight_validation.py" in agi_gui.argv
    assert "test/test_cluster_lan_discovery.py" in agi_gui.argv
    assert "test/test_notebook_colab_support.py" in agi_gui.argv
    assert "test/test_ui_pages.py" in agi_gui.argv
    assert "test/test_view*.py" not in agi_gui.argv
    assert "test/test_view_maps.py" in agi_gui.argv
    assert docs.argv[-2:] == ["docs/source", "docs/html"]
    assert badges[-1].label == "badge drift guard"
    assert badges[-1].argv == ["git", "diff", "--exit-code", "--", "badges/"]
    assert strict_typing.argv[-1] == "tools/shared_core_strict_typing.py"


def test_selected_profiles_skips_preflight_only_combined_core_profile_by_default() -> None:
    module = _load_module()
    args = SimpleNamespace(profile=None)

    selected = module._selected_profiles(args)

    assert "agi-core-combined" not in selected
    assert "agi-node" in selected
    assert "agi-cluster" in selected


def test_installer_profile_adds_contract_check_when_app_path_is_provided() -> None:
    module = _load_module()
    args = SimpleNamespace(
        components=None,
        skills=None,
        app_path="src/agilab/apps/builtin/flight_project",
        worker_copy="~/wenv/builtin/flight_worker",
    )

    profiles = module._profile_commands(args)
    installer_commands = profiles["installer"]

    assert len(installer_commands) == 3
    contract = installer_commands[-1]
    assert contract.label == "installer contract check"
    assert contract.argv[-4:] == [
        "--app-path",
        "src/agilab/apps/builtin/flight_project",
        "--worker-copy",
        "~/wenv/builtin/flight_worker",
    ]


def test_run_profiles_stops_on_first_failure_by_default() -> None:
    module = _load_module()
    args = SimpleNamespace(
        profile=["skills", "badges"],
        components=None,
        skills=None,
        app_path=None,
        worker_copy=None,
        keep_going=False,
    )
    seen = []

    def _fake_runner(spec):
        seen.append(spec.label)
        return module.CommandResult(
            label=spec.label,
            argv=spec.argv,
            returncode=1,
            duration_seconds=0.01,
            cwd=str(module.REPO_ROOT),
            env=spec.env,
        )

    results = module.run_profiles(["skills", "badges"], args=args, runner=_fake_runner)

    assert [result.profile for result in results] == ["skills"]
    assert seen == ["validate codex skills"]
    assert results[0].success is False


def test_main_print_only_json_lists_selected_profile_commands(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--profile", "skills", "--skills", "agilab-installer", "--print-only", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profiles"] == ["skills"]
    first = payload["commands"]["skills"][0]
    assert first["label"] == "sync shared skills"
    assert first["argv"] == [
        "python3",
        "tools/sync_agent_skills.py",
        "--skills",
        "agilab-installer",
    ]
