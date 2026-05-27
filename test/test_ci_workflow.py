import ast
import importlib.util
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace


WORKFLOW_PATH = Path(".github/workflows/ci.yml")
COVERAGE_WORKFLOW_PATH = Path(".github/workflows/coverage.yml")
DOCS_SOURCE_GUARD_WORKFLOW_PATH = Path(".github/workflows/docs-source-guard.yaml")
DOCS_PUBLISH_WORKFLOW_PATH = Path(".github/workflows/docs-publish.yaml")
ENSURE_ROADMAP_LABEL_WORKFLOW_PATH = Path(".github/workflows/ensure-roadmap-label.yaml")
UI_ROBOT_MATRIX_WORKFLOW_PATH = Path(".github/workflows/ui-robot-matrix.yml")
ROOT_CONFTEST_PATH = Path("test/conftest.py")
WORKFLOW_PARITY_PATH = Path("tools/workflow_parity.py")

VALIDATION_WORKFLOW_PATHS = (
    WORKFLOW_PATH,
    COVERAGE_WORKFLOW_PATH,
    DOCS_SOURCE_GUARD_WORKFLOW_PATH,
    ENSURE_ROADMAP_LABEL_WORKFLOW_PATH,
)

VALIDATION_CONCURRENCY_GROUP = (
    "group: ${{ github.workflow }}-${{ github.event.pull_request.head.repo.full_name || "
    "github.repository }}-${{ github.head_ref || github.ref_name }}"
)


def _load_workflow_parity_module():
    spec = importlib.util.spec_from_file_location("ci_workflow_parity_test_module", WORKFLOW_PARITY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ui_robot_matrix_workflow_shards() -> dict[str, list[str]]:
    shards: dict[str, list[str]] = {}
    current_shard = ""
    collecting = False
    for line in UI_ROBOT_MATRIX_WORKFLOW_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- shard:"):
            current_shard = stripped.split(":", 1)[1].strip()
            shards[current_shard] = []
            collecting = False
            continue
        if current_shard and stripped == "scenarios: >-":
            collecting = True
            continue
        if collecting:
            if line.startswith("              ") and stripped:
                shards[current_shard].append(stripped)
                continue
            collecting = False
    assert shards
    return shards


def _ui_robot_matrix_parity_commands():
    module = _load_workflow_parity_module()
    args = SimpleNamespace(components=None, skills=None, app_path=None, worker_copy=None)
    return list(module._profile_commands(args)["ui-robot-matrix"])


def _option_values(argv: list[str], option: str) -> list[str]:
    return [argv[index + 1] for index, arg in enumerate(argv[:-1]) if arg == option]


def _single_option(argv: list[str], option: str) -> str:
    values = _option_values(argv, option)
    assert len(values) == 1
    return values[0]


def _ui_robot_matrix_option(argv: list[str], option: str) -> str:
    value = _single_option(argv, option)
    workflow_defaults = {
        "--apps": {"${robot_apps}": "all"},
        "--timeout": {"${robot_timeout}": "90"},
        "--widget-timeout": {"${robot_widget_timeout}": "3"},
    }
    return workflow_defaults.get(option, {}).get(value, value)


def _ui_robot_matrix_command_contract(argv: list[str]) -> dict[str, object]:
    return {
        "script": "tools/agilab_widget_robot_matrix.py" in argv,
        "scenarios": _option_values(argv, "--scenario"),
        "apps": _ui_robot_matrix_option(argv, "--apps"),
        "timeout": _ui_robot_matrix_option(argv, "--timeout"),
        "widget_timeout": _ui_robot_matrix_option(argv, "--widget-timeout"),
        "json": "--json" in argv,
        "quiet_progress": "--quiet-progress" in argv,
        "no_result_cache": "--no-result-cache" in argv,
        "output_dir": _single_option(argv, "--output-dir"),
        "screenshot_dir": _single_option(argv, "--screenshot-dir"),
        "failure_bundle_dir": _single_option(argv, "--failure-bundle-dir"),
        "retry_failed_with_artifacts": "--retry-failed-with-artifacts" in argv,
        "retry_trace_dir": _single_option(argv, "--retry-trace-dir"),
        "retry_har_dir": _single_option(argv, "--retry-har-dir"),
        "retry_video_dir": _single_option(argv, "--retry-video-dir"),
    }


def _ui_robot_matrix_workflow_contracts() -> dict[str, dict[str, object]]:
    return {
        shard: {
            "script": True,
            "scenarios": scenarios,
            "apps": "all",
            "timeout": "90",
            "widget_timeout": "3",
            "json": True,
            "quiet_progress": True,
            "no_result_cache": True,
            "output_dir": f"test-results/ui-robot-matrix/{shard}",
            "screenshot_dir": f"screenshots/ui-robot-matrix/{shard}",
            "failure_bundle_dir": f"test-results/ui-robot-matrix/{shard}/failure-bundles",
            "retry_failed_with_artifacts": True,
            "retry_trace_dir": f"test-results/ui-robot-matrix/{shard}/failure-artifacts/traces",
            "retry_har_dir": f"test-results/ui-robot-matrix/{shard}/failure-artifacts/har",
            "retry_video_dir": f"test-results/ui-robot-matrix/{shard}/failure-artifacts/video",
        }
        for shard, scenarios in _ui_robot_matrix_workflow_shards().items()
    }


def _ui_robot_matrix_parity_contracts() -> dict[str, dict[str, object]]:
    contracts: dict[str, dict[str, object]] = {}
    for command in _ui_robot_matrix_parity_commands():
        contract = _ui_robot_matrix_command_contract(list(command.argv))
        shard = Path(str(contract["output_dir"])).name
        contracts[shard] = contract
    return contracts


def test_ci_workflow_includes_minimal_first_proof_contract() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    push_block = text.split("pull_request:", 1)[0]

    assert 'branches: ["main"]' in push_block
    assert 'branches: ["**"]' not in push_block
    assert "Validate first-launch robot" in text
    assert (
        "uv --preview-features extra-build-dependencies run --extra ui python "
        "tools/first_launch_robot.py --json --output first-launch-robot.json"
    ) in text
    assert "Install Playwright browser for frontend smoke" in text
    assert "Validate Streamlit frontend smoke" in text
    assert "python -m playwright install --with-deps chromium" in text
    assert "tools/agilab_web_robot.py" in text
    assert "--frontend-smoke-only" in text
    assert "frontend-smoke-robot.json" in text
    assert "clean-public-install" in text
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in text
    assert "tools/install_release_proof_package.py" in text
    assert "Check release package is installable from PyPI" in text
    assert "python tools/install_release_proof_package.py --check-installable-only" in text
    assert "steps.release-package.outputs.available == 'true'" in text
    assert "GITHUB_EVENT_NAME" in text
    assert "python tools/install_release_proof_package.py --retries 20 --delay-seconds 15" in text
    assert "python -m pip install agilab" not in text
    assert "agilab first-proof --json --no-manifest --max-seconds 60" in text
    assert "uv --preview-features extra-build-dependencies run --extra dev ruff --version" in text
    assert "tools/app_contract_matrix.py --output app-contract-matrix.json --quiet" in text
    assert "app-contract-matrix.json" in text
    assert "tools/ui_robot_matrix_aggregate.py" in text


def test_validation_workflows_cancel_superseded_branch_runs() -> None:
    for path in VALIDATION_WORKFLOW_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "concurrency:" in text, path
        assert VALIDATION_CONCURRENCY_GROUP in text, path
        assert "cancel-in-progress: true" in text, path


def test_maintenance_workflows_do_not_run_twice_for_pr_branch_pushes() -> None:
    assert 'branches: ["main"]' in WORKFLOW_PATH.read_text(encoding="utf-8")
    assert 'branches: ["main"]' in ENSURE_ROADMAP_LABEL_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_docs_workflows_block_stale_release_proof_github_runs() -> None:
    for path in (DOCS_SOURCE_GUARD_WORKFLOW_PATH, DOCS_PUBLISH_WORKFLOW_PATH):
        text = path.read_text(encoding="utf-8")
        assert "GH_TOKEN: ${{ github.token }}" in text
        assert "tools/release_proof_report.py --check --check-github-runs --compact" in text

    guard_text = DOCS_SOURCE_GUARD_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "actions: read" in guard_text
    assert (
        "uv --preview-features extra-build-dependencies run pytest -q "
        "-o addopts='' test/test_sync_docs_source.py test/test_release_proof_report.py"
    ) in guard_text
    assert "run --extra ui pytest -q -o addopts='' test/test_sync_docs_source.py" not in guard_text


def test_ui_robot_matrix_workflow_is_opt_in_or_nightly_only() -> None:
    text = UI_ROBOT_MATRIX_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: ui-robot-matrix" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert "pull_request:" not in text
    assert "\n  push:" not in text
    assert "ui-robot-matrix:" in text
    assert "strategy:" in text
    assert "fail-fast: false" in text
    assert "- shard: core" in text
    assert "- shard: state" in text
    assert "- shard: quality" in text
    assert "- shard: layout" in text
    assert "tools/agilab_widget_robot_matrix.py" in text
    assert "uv --preview-features extra-build-dependencies run --extra ai --with playwright python tools/agilab_widget_robot_matrix.py" in text
    for scenario in {
        scenario
        for scenarios in _ui_robot_matrix_workflow_shards().values()
        for scenario in scenarios
    }:
        assert scenario in text
    assert '"${scenario_args[@]}"' in text
    assert "--apps \"${robot_apps}\"" in text
    assert "--json" in text
    assert "--quiet-progress" in text
    assert "--no-result-cache" in text
    assert 'result_dir="test-results/ui-robot-matrix/${ROBOT_SHARD}"' in text
    assert 'screenshot_dir="screenshots/ui-robot-matrix/${ROBOT_SHARD}"' in text
    assert 'failure_bundle_dir="${result_dir}/failure-bundles"' in text
    assert 'failure_artifact_dir="${result_dir}/failure-artifacts"' in text
    assert '--output-dir "${result_dir}"' in text
    assert '--screenshot-dir "${screenshot_dir}"' in text
    assert '--failure-bundle-dir "${failure_bundle_dir}"' in text
    assert "--retry-failed-with-artifacts" in text
    assert '--retry-trace-dir "${failure_artifact_dir}/traces"' in text
    assert '--retry-har-dir "${failure_artifact_dir}/har"' in text
    assert '--retry-video-dir "${failure_artifact_dir}/video"' in text
    assert "tools/ui_robot_trend_report.py" in text
    assert '--glob "${result_dir}/*.ndjson"' in text
    assert "--max-total-seconds 2700" in text
    assert "--strict" in text
    assert "--strict-budget" in text
    assert '--output "${result_dir}/trend-report.json"' in text
    assert '${result_dir}/trend-report.txt' in text
    assert 'trend_status="${PIPESTATUS[0]}"' in text
    assert 'exit "${trend_status}"' in text
    assert "## UI robot trend (${ROBOT_SHARD})" in text
    assert "--write-shard-manifest" in text
    assert '--result-dir "${RESULT_DIR}"' in text
    assert '--screenshot-dir "${SCREENSHOT_DIR}"' in text
    assert '--shard "${ROBOT_SHARD}"' in text
    assert "failure_samples" in text
    assert "GITHUB_STEP_SUMMARY" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" in text
    assert "ui-robot-matrix-${{ matrix.shard }}-${{ github.run_attempt }}" in text
    assert "test-results/ui-robot-matrix/${{ matrix.shard }}/**" in text
    assert "screenshots/ui-robot-matrix/${{ matrix.shard }}/**" in text
    assert "aggregate-ui-robot-matrix:" in text
    assert "needs: ui-robot-matrix" in text
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1" in text
    assert "pattern: ui-robot-matrix-*-${{ github.run_attempt }}" in text
    assert "uv --preview-features extra-build-dependencies run python tools/ui_robot_matrix_aggregate.py" in text
    assert "--expected-shards core,state,quality,layout" in text
    assert "--output test-results/ui-robot-matrix-aggregate/aggregate.json" in text
    assert "--summary-markdown test-results/ui-robot-matrix-aggregate/summary.md" in text
    assert "ui-robot-matrix-aggregate-${{ github.run_attempt }}" in text
    assert "AGILAB_DISABLE_BACKGROUND_SERVICES: \"1\"" in text


def test_agent_skills_security_is_local_only() -> None:
    assert not Path(".github/workflows/agent-skills-security.yaml").exists()
    workflow_parity = WORKFLOW_PARITY_PATH.read_text(encoding="utf-8")
    dev_shortcuts = Path("tools/agilab_dev.py").read_text(encoding="utf-8")
    agent_workflows = Path("tools/agent_workflows.md").read_text(encoding="utf-8")

    for text in (workflow_parity, dev_shortcuts, agent_workflows):
        assert "tools/skill_security_scan.py" in text
        assert "--fail-on" in text
        assert "critical" in text


def test_ui_robot_matrix_workflow_command_matches_local_workflow_parity() -> None:
    assert _ui_robot_matrix_workflow_contracts() == _ui_robot_matrix_parity_contracts()


def test_root_conftest_keeps_streamlit_testing_import_lazy() -> None:
    tree = ast.parse(ROOT_CONFTEST_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            continue
        if isinstance(node, ast.ImportFrom):
            assert node.module != "streamlit.testing.v1"


def test_dev_extra_installs_ruff_for_local_linting() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]

    assert any(dependency.startswith("ruff>=") for dependency in dev_dependencies)
