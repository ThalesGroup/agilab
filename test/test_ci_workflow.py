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
PYPI_PUBLISH_WORKFLOW_PATH = Path(".github/workflows/pypi-publish.yaml")
ENSURE_ROADMAP_LABEL_WORKFLOW_PATH = Path(".github/workflows/ensure-roadmap-label.yaml")
UI_ROBOT_MATRIX_WORKFLOW_PATH = Path(".github/workflows/ui-robot-matrix.yml")
WINDOWS_CORE_TESTS_WORKFLOW_PATH = Path(".github/workflows/windows-core-tests.yml")
ROOT_TEST_SUITE_WORKFLOW_PATH = Path(".github/workflows/root-test-suite.yml")
ROOT_CONFTEST_PATH = Path("test/conftest.py")
WORKFLOW_PARITY_PATH = Path("tools/workflow_parity.py")
UI_ROBOT_MATRIX_PLAN_PATH = Path("tools/testing/ui_robot_matrix_plan.py")
PYPROJECT_PATH = Path("pyproject.toml")

VALIDATION_WORKFLOW_PATHS = (
    WORKFLOW_PATH,
    COVERAGE_WORKFLOW_PATH,
    DOCS_SOURCE_GUARD_WORKFLOW_PATH,
    ENSURE_ROADMAP_LABEL_WORKFLOW_PATH,
    WINDOWS_CORE_TESTS_WORKFLOW_PATH,
    ROOT_TEST_SUITE_WORKFLOW_PATH,
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


def _ui_robot_matrix_plan_rows() -> dict[str, dict[str, object]]:
    spec = importlib.util.spec_from_file_location(
        "ci_ui_robot_matrix_plan_test_module",
        UI_ROBOT_MATRIX_PLAN_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    plan = module.build_plan()
    return {
        str(row["shard"]): dict(row)
        for row in plan["matrix"]["include"]
    }


def _ui_robot_matrix_workflow_shards() -> dict[str, list[str]]:
    return {
        shard: str(row["scenarios"]).split()
        for shard, row in _ui_robot_matrix_plan_rows().items()
    }


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


def _optional_single_option(argv: list[str], option: str) -> str | None:
    values = _option_values(argv, option)
    assert len(values) <= 1
    return values[0] if values else None


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
        "scenario_timeout": _ui_robot_matrix_option(argv, "--scenario-timeout"),
        "fail_fast": "--fail-fast" in argv,
        "json": "--json" in argv,
        "quiet_progress": "--quiet-progress" in argv,
        "no_result_cache": "--no-result-cache" in argv,
        "output_dir": _single_option(argv, "--output-dir"),
        "screenshot_dir": _single_option(argv, "--screenshot-dir"),
        "failure_bundle_dir": _single_option(argv, "--failure-bundle-dir"),
        "retry_failed_with_artifacts": "--retry-failed-with-artifacts" in argv,
        "retry_trace_dir": _single_option(argv, "--retry-trace-dir"),
        "retry_har_dir": _optional_single_option(argv, "--retry-har-dir"),
        "retry_video_dir": _optional_single_option(argv, "--retry-video-dir"),
        "failure_retry_timeout": _single_option(argv, "--failure-retry-timeout"),
    }


def _ui_robot_matrix_workflow_contracts() -> dict[str, dict[str, object]]:
    plan_rows = _ui_robot_matrix_plan_rows()
    return {
        shard: {
            "script": True,
            "scenarios": scenarios,
            "apps": str(plan_rows[shard]["apps"]),
            "timeout": "90",
            "widget_timeout": "3",
            "scenario_timeout": "900",
            "fail_fast": True,
            "json": True,
            "quiet_progress": False,
            "no_result_cache": True,
            "output_dir": f"test-results/ui-robot-matrix/{shard}",
            "screenshot_dir": f"screenshots/ui-robot-matrix/{shard}",
            "failure_bundle_dir": f"test-results/ui-robot-matrix/{shard}/failure-bundles",
            "retry_failed_with_artifacts": True,
            "retry_trace_dir": f"test-results/ui-robot-matrix/{shard}/failure-artifacts/traces",
            "retry_har_dir": None,
            "retry_video_dir": None,
            "failure_retry_timeout": "300",
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
    assert 'cron: "17 5 * * 1"' in text
    assert 'cron: "17 5 * * *"' not in text
    assert "Validate first-launch robot" in text
    assert (
        "uv --preview-features extra-build-dependencies run --extra ui python "
        "tools/first_launch_robot.py --json --output first-launch-robot.json"
    ) in text
    assert "Resolve Playwright version for browser cache key" in text
    assert "id: playwright-version" in text
    assert "Restore Playwright browser cache" in text
    assert "id: playwright-cache" in text
    assert "actions/cache/restore@27d5ce7f107fe9357f9df03efb73ab90386fccae" in text
    assert "path: ~/.cache/ms-playwright" in text
    assert (
        "key: playwright-${{ runner.os }}-py3.13-${{ steps.playwright-version.outputs.version }}-chromium"
    ) in text
    assert "restore-keys" not in text.split("Restore Playwright browser cache", 1)[1].split(
        "Install Playwright browser for frontend smoke", 1
    )[0]
    assert "Install Playwright browser for frontend smoke" in text
    assert "Validate widget layout visibility collector" in text
    assert 'AGILAB_REQUIRE_PLAYWRIGHT_LAYOUT_REGRESSION: "1"' in text
    assert (
        "test/test_agilab_widget_robot.py::"
        "test_layout_integrity_collector_uses_painted_geometry_for_expander_content"
    ) in text
    assert (
        "test/test_agilab_widget_robot.py::"
        "test_visible_combobox_semantics_collector_filters_hidden_controls"
    ) in text
    assert "Validate Streamlit frontend smoke" in text
    assert (
        'uv --preview-features extra-build-dependencies run --with "playwright==${{ steps.playwright-version.outputs.version }}" '
        "python -m playwright install --with-deps chromium"
    ) in text
    assert "Save Playwright browser cache" in text
    assert "steps.playwright-cache.outputs.cache-hit != 'true'" in text
    assert "actions/cache/save@27d5ce7f107fe9357f9df03efb73ab90386fccae" in text
    assert text.index("Restore Playwright browser cache") < text.index(
        "Install Playwright browser for frontend smoke"
    )
    assert text.index("Install Playwright browser for frontend smoke") < text.index(
        "Save Playwright browser cache"
    )
    assert "tools/agilab_web_robot.py" in text
    assert "--frontend-smoke-only" in text
    assert "frontend-smoke-robot.json" in text
    assert "clean-public-install" in text
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in text
    assert "tools/install_release_proof_package.py" in text
    assert "Check release package is installable from PyPI" in text
    assert "python tools/install_release_proof_package.py --check-source-ahead" in text
    assert "--check-project-newer-than-manifest" not in text
    assert "Release proof explicitly declares source-ahead mode" in text
    assert "python tools/install_release_proof_package.py --check-installable-only" in text
    assert "steps.release-package.outputs.available == 'true'" in text
    assert "GITHUB_EVENT_NAME" in text
    assert "python tools/install_release_proof_package.py --retries 20 --delay-seconds 15" in text
    assert "python -m pip install agilab" not in text
    assert "agilab first-proof --json --no-manifest --max-seconds 60" in text
    assert "uv --preview-features extra-build-dependencies run --extra dev ruff --version" in text
    assert "Validate fast repository contracts" in text
    assert "test/test_package_split_contract.py" in text
    assert "test/test_pypi_publish_workflow.py" in text
    assert "test/test_compat_shim_inventory.py" in text
    assert "tools/app_contract_matrix.py --output app-contract-matrix.json --quiet" in text
    assert "app-contract-matrix.json" in text
    assert "Validate robustness recovery matrix" in text
    assert "tools/robustness_matrix.py" in text
    assert "--profile all" in text
    assert "--output robustness-matrix.json" in text
    assert "robustness-matrix.json" in text
    assert "tools/ui_robot_matrix_aggregate.py" in text
    assert "Guard agi-core owner" in text
    assert "tools/agi_core_change_guard.py" in text
    assert "AGILAB_CORE_CHANGE_ACTOR: ${{ github.actor }}" in text
    assert "--base-ref \"$AGILAB_CORE_CHANGE_BASE\"" in text
    assert "--head-ref \"$AGILAB_CORE_CHANGE_HEAD\"" in text


def test_ci_security_hygiene_uses_required_supply_chain_artifacts() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    scan_step = text.split("- name: Generate base supply-chain evidence", 1)[1].split(
        "- name: Validate security hygiene report", 1
    )[0]
    security_step = text.split("- name: Validate security hygiene report", 1)[1].split(
        "- name: Upload local proof artifacts", 1
    )[0]

    assert "tools/profile_supply_chain_scan.py" in scan_step
    assert "--profile base" in scan_step
    assert "--output-dir test-results/supply-chain" in scan_step
    assert "--run" in scan_step
    assert "uv --preview-features extra-build-dependencies run" in security_step
    assert "--pip-audit-json test-results/supply-chain/base/pip-audit.json" in security_step
    assert "--sbom-json test-results/supply-chain/base/sbom-cyclonedx.json" in security_step
    assert (
        "--scan-requirements test-results/supply-chain/base/requirements.txt"
        in security_step
    )
    assert "--require-scan-artifacts" in security_step
    assert text.index("Generate base supply-chain evidence") < text.index(
        "Validate security hygiene report"
    )

    upload_step = text.split("- name: Upload local proof artifacts", 1)[1].split(
        "- name: Confirm extended test policy", 1
    )[0]
    assert "security-hygiene.json" in upload_step
    assert "test-results/supply-chain/base/**" in upload_step


def test_root_pytest_discovers_all_existing_core_package_tests() -> None:
    config = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    pytest_options = config["tool"]["pytest"]["ini_options"]
    testpaths = set(pytest_options["testpaths"])
    existing_core_test_dirs = {
        path.as_posix()
        for path in Path("src/agilab/core").glob("*/test")
        if path.is_dir()
    }
    expected = {"src/agilab/core/test", *existing_core_test_dirs}

    assert expected <= testpaths


def test_validation_workflows_cancel_superseded_branch_runs() -> None:
    for path in VALIDATION_WORKFLOW_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "concurrency:" in text, path
        assert VALIDATION_CONCURRENCY_GROUP in text, path
        assert "cancel-in-progress: true" in text, path


def test_root_test_suite_runs_canonical_isolated_plan_on_every_change() -> None:
    text = ROOT_TEST_SUITE_WORKFLOW_PATH.read_text(encoding="utf-8")
    checkout = text.split("- name: Checkout", 1)[1].split(
        "- name: Set up Python", 1
    )[0]

    assert 'pull_request:\n    branches: ["**"]\n  push:' in text
    assert 'push:\n    branches: ["main"]\n  workflow_dispatch:' in text
    assert "paths:" not in text
    assert "lfs: true" in checkout
    assert "--extra ui" in text
    assert "--extra notebook" in text
    assert "python -m tools.testing.root_test_runner" in text
    assert "known-failures" not in text
    assert "--deselect" not in text


def test_maintenance_workflows_do_not_run_twice_for_pr_branch_pushes() -> None:
    assert 'branches: ["main"]' in WORKFLOW_PATH.read_text(encoding="utf-8")
    assert 'branches: ["main"]' in ENSURE_ROADMAP_LABEL_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_windows_core_tests_workflow_matches_failure_tracker_command() -> None:
    text = WINDOWS_CORE_TESTS_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: windows-core-tests" in text
    assert "runs-on: windows-latest" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert 'branches: ["main"]' in text
    assert 'branches: ["**"]' in text
    assert "--import-mode=importlib" in text
    assert "--disable-warnings" not in text
    assert "Audit Windows warning output" in text
    assert "tools/validation_warning_report.py" in text
    assert "--strict" in text
    assert "src/agilab/core/test src/agilab/core/agi-env/test src/agilab/core/agi-cluster/test" in text
    assert "test-results/windows-core-tests.txt" in text
    assert "test-results/windows-core-tests.xml" in text
    assert "test-results/windows-core-warning-report.json" in text
    assert (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
        in text
    )
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7" in text
    assert (
        "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0"
        in text
    )
    assert "prune-cache: true" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" in text


def test_clean_public_install_avoids_stale_pip_cache_warnings() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "python -m pip install --upgrade pip --no-cache-dir" in text


def test_base_python_compat_exercises_supported_boundaries_through_the_cli() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    compat_block = text.split("  base-python-compat:", 1)[1].split(
        "  clean-public-install:", 1
    )[0]

    assert 'python-version: ["3.12", "3.14"]' in compat_block
    assert (
        "python -m pytest -q --noconftest -c /dev/null -p no:cacheprovider "
        "test/test_lab_run.py"
    ) in compat_block
    assert "agilab --version" in compat_block
    assert compat_block.count("run --no-project") == 2
    assert compat_block.count("--with-editable .") == 2
    assert compat_block.count("--with pytest==9.1.1") == 1
    assert "Validate base package import" not in compat_block

    primary_python_313_block = text.split("  local-only-policy:", 1)[1].split(
        "  base-python-compat:", 1
    )[0]
    assert 'python-version: "3.13"' in primary_python_313_block


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


def test_docs_workflows_label_target_only_verification_honestly() -> None:
    for path in (DOCS_SOURCE_GUARD_WORKFLOW_PATH, DOCS_PUBLISH_WORKFLOW_PATH):
        text = path.read_text(encoding="utf-8")
        assert "Verify checked-in docs mirror integrity" in text
        assert (
            "tools/sync_docs_source.py --verify-stamp --skip-missing-source --quiet"
            in text
        )

    guard_text = DOCS_SOURCE_GUARD_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "--check --delete --quiet --skip-missing-source" not in guard_text


def test_release_workflow_preserves_valid_mirror_evidence_before_degrading() -> None:
    text = PYPI_PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8")
    stamp_block = text.split("python tools/sync_docs_source.py", 1)[1].split(
        "release_metadata_paths=", 1
    )[0]

    assert "--refresh-target-integrity-stamp" in stamp_block
    assert "--write-target-only-stamp" not in stamp_block
    assert "--source docs/source" not in stamp_block


def test_hf_release_refresh_does_not_claim_or_rewrite_canonical_docs_index() -> None:
    text = PYPI_PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8")
    hf_refresh_block = text.split(
        "- name: Prepare immutable release proof and review branch", 1
    )[1].split("- name: Attest immutable release proof assets", 1)[0]
    metadata_block = hf_refresh_block.split("release_metadata_paths=(", 1)[1].split(
        ")", 1
    )[0]

    assert "update_public_release_references_for_guard" in hf_refresh_block
    assert "update_docs_index_release_link" not in hf_refresh_block
    assert "docs/source/index.rst" not in metadata_block


def test_release_plan_validates_managed_docs_tag_before_publish_jobs() -> None:
    text = PYPI_PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8")
    release_plan_block = text.split("  release-plan:\n", 1)[1].split(
        "  build-library-packages:\n", 1
    )[0]

    assert "Validate managed docs release tag before publication" in release_plan_block
    assert "assert_public_docs_index_release_link" in release_plan_block
    assert "steps.release-plan.outputs.pypi_publish_selected == 'true'" in release_plan_block
    assert text.index("Validate managed docs release tag before publication") < text.index(
        "  publish-library-packages:\n"
    )
    assert text.index("Validate managed docs release tag before publication") < text.index(
        "  publish-agilab:\n"
    )


def test_docs_workflows_fetch_release_tags_for_exact_proof() -> None:
    for workflow_path in (
        DOCS_SOURCE_GUARD_WORKFLOW_PATH,
        DOCS_PUBLISH_WORKFLOW_PATH,
    ):
        workflow_text = workflow_path.read_text(encoding="utf-8")
        checkout_block = workflow_text.split("- name: Checkout", 1)[1].split(
            "- name: Setup Python", 1
        )[0]
        assert "fetch-depth: 0" in checkout_block


def test_ui_robot_matrix_workflow_is_opt_in_or_weekly_only() -> None:
    text = UI_ROBOT_MATRIX_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: ui-robot-matrix" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert 'cron: "43 2 * * 3"' in text
    assert 'cron: "43 2 * * *"' not in text
    assert "pull_request:" not in text
    assert "\n  push:" not in text
    assert "ui-robot-matrix:" in text
    assert "plan_ui_robot_matrix:" in text
    assert "tools/testing/ui_robot_matrix_plan.py" in text
    assert "--github-output" in text
    assert "matrix: ${{ fromJSON(needs.plan_ui_robot_matrix.outputs.matrix) }}" in text
    assert "strategy:" in text
    assert "fail-fast: false" in text
    assert "tools/agilab_widget_robot_matrix.py" in text
    assert "Resolve Playwright version for browser cache key" in text
    assert "id: playwright-version" in text
    assert "Restore Playwright browser cache" in text
    assert "id: playwright-cache" in text
    assert "actions/cache/restore@27d5ce7f107fe9357f9df03efb73ab90386fccae" in text
    assert "path: ~/.cache/ms-playwright" in text
    assert (
        "key: playwright-${{ runner.os }}-py3.13-${{ steps.playwright-version.outputs.version }}-chromium"
    ) in text
    assert "restore-keys" not in text.split("Restore Playwright browser cache", 1)[1].split(
        "Install Playwright browser", 1
    )[0]
    assert (
        'uv --preview-features extra-build-dependencies run --with "playwright==${{ steps.playwright-version.outputs.version }}" '
        "python -m playwright install --with-deps chromium"
    ) in text
    assert "Save Playwright browser cache" in text
    assert "steps.playwright-cache.outputs.cache-hit != 'true' && matrix.shard == 'core-01'" in text
    assert "actions/cache/save@27d5ce7f107fe9357f9df03efb73ab90386fccae" in text
    assert text.index("Restore Playwright browser cache") < text.index(
        "Install Playwright browser"
    )
    assert text.index("Install Playwright browser") < text.index(
        "Save Playwright browser cache"
    )
    assert "uv --preview-features extra-build-dependencies run --extra ai --with playwright python tools/agilab_widget_robot_matrix.py" in text
    planner_text = UI_ROBOT_MATRIX_PLAN_PATH.read_text(encoding="utf-8")
    for scenario in {
        scenario
        for scenarios in _ui_robot_matrix_workflow_shards().values()
        for scenario in scenarios
    }:
        assert scenario in planner_text
    assert '"${scenario_args[@]}"' in text
    assert "--apps \"${robot_apps}\"" in text
    assert "--scenario-timeout 900" in text
    assert "--fail-fast" in text
    assert "--json" in text
    assert "--quiet-progress" not in text
    assert "--no-result-cache" in text
    assert 'result_dir="test-results/ui-robot-matrix/${ROBOT_SHARD}"' in text
    assert 'screenshot_dir="screenshots/ui-robot-matrix/${ROBOT_SHARD}"' in text
    assert 'failure_bundle_dir="${result_dir}/failure-bundles"' in text
    assert 'failure_artifact_dir="${result_dir}/failure-artifacts"' in text
    assert 'robot_apps="${ROBOT_APPS}"' in text
    assert "ROBOT_APPS: ${{ matrix.apps }}" in text
    assert '--output-dir "${result_dir}"' in text
    assert '--screenshot-dir "${screenshot_dir}"' in text
    assert '--failure-bundle-dir "${failure_bundle_dir}"' in text
    assert "--retry-failed-with-artifacts" in text
    assert '--retry-trace-dir "${failure_artifact_dir}/traces"' in text
    assert "--retry-har-dir" not in text
    assert "--retry-video-dir" not in text
    assert "--failure-retry-timeout 300" in text
    assert "retention-days: 3" in text
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
    assert "- plan_ui_robot_matrix" in text
    assert "- ui-robot-matrix" in text
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1" in text
    assert "pattern: ui-robot-matrix-*-${{ github.run_attempt }}" in text
    assert "uv --preview-features extra-build-dependencies run python tools/ui_robot_matrix_aggregate.py" in text
    assert '--expected-shards "${EXPECTED_SHARDS}"' in text
    assert '--expected-apps "${EXPECTED_APPS}"' in text
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

    ruff_dependencies = [
        dependency
        for dependency in dev_dependencies
        if dependency.startswith("ruff>=")
    ]

    assert ruff_dependencies == ["ruff>=0.15.14,<0.16"]
