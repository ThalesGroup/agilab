import ast
from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/ci.yml")
COVERAGE_WORKFLOW_PATH = Path(".github/workflows/coverage.yml")
DOCS_SOURCE_GUARD_WORKFLOW_PATH = Path(".github/workflows/docs-source-guard.yaml")
DOCS_PUBLISH_WORKFLOW_PATH = Path(".github/workflows/docs-publish.yaml")
ENSURE_ROADMAP_LABEL_WORKFLOW_PATH = Path(".github/workflows/ensure-roadmap-label.yaml")
UI_ROBOT_MATRIX_WORKFLOW_PATH = Path(".github/workflows/ui-robot-matrix.yml")
ROOT_CONFTEST_PATH = Path("test/conftest.py")

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
    assert "clean-public-install" in text
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in text
    assert "tools/install_release_proof_package.py" in text
    assert "Check release package is visible on PyPI" in text
    assert "python tools/install_release_proof_package.py --check-available-only" in text
    assert "steps.release-package.outputs.available == 'true'" in text
    assert "GITHUB_EVENT_NAME" in text
    assert "python tools/install_release_proof_package.py --retries 20 --delay-seconds 15" in text
    assert "python -m pip install agilab" not in text
    assert "agilab first-proof --json --no-manifest --max-seconds 60" in text


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
    assert "all-builtin-isolated-core-pages:" in text
    assert "tools/agilab_widget_robot_matrix.py" in text
    assert "--scenario isolated-core-pages" in text
    assert "--apps \"${robot_apps}\"" in text
    assert "--json" in text
    assert "--quiet-progress" in text
    assert "--output-dir test-results/ui-robot-matrix" in text
    assert "--screenshot-dir screenshots/ui-robot-matrix" in text
    assert "failure_samples" in text
    assert "GITHUB_STEP_SUMMARY" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" in text
    assert "AGILAB_DISABLE_BACKGROUND_SERVICES: \"1\"" in text


def test_root_conftest_keeps_streamlit_testing_import_lazy() -> None:
    tree = ast.parse(ROOT_CONFTEST_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            continue
        if isinstance(node, ast.ImportFrom):
            assert node.module != "streamlit.testing.v1"
