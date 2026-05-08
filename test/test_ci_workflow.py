from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/ci.yml")
DOCS_SOURCE_GUARD_WORKFLOW_PATH = Path(".github/workflows/docs-source-guard.yaml")
DOCS_PUBLISH_WORKFLOW_PATH = Path(".github/workflows/docs-publish.yaml")
UI_ROBOT_MATRIX_WORKFLOW_PATH = Path(".github/workflows/ui-robot-matrix.yml")


def test_ci_workflow_includes_minimal_first_proof_contract() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Compile critical Python entrypoints" in text
    assert "Validate release proof manifest" in text
    assert "python tools/release_proof_report.py --check --compact" in text
    assert "Validate release proof GitHub run evidence" in text
    assert "GH_TOKEN: ${{ github.token }}" in text
    assert "python tools/release_proof_report.py --check --check-github-runs --compact" in text
    assert "tools/ui_robot_evidence.py" in text
    assert "Validate first-proof command contract" in text
    assert "python src/agilab/first_proof_cli.py --print-only --json" in text
    assert "Validate public proof scenarios" in text
    assert "python tools/public_proof_scenarios.py --compact" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert "astral-sh/setup-uv@" in text
    assert "# v7" in text
    assert "Validate first-launch robot" in text
    assert (
        "uv --preview-features extra-build-dependencies run python "
        "tools/first_launch_robot.py --json --output first-launch-robot.json"
    ) in text
    assert "Validate security hygiene report" in text
    assert "python tools/security_hygiene_report.py --output security-hygiene.json --compact" in text
    assert "Upload local proof artifacts" in text
    assert "clean-public-install" in text
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in text
    assert "Install released AGILAB package" in text
    assert "tools/install_release_proof_package.py" in text
    assert "python tools/install_release_proof_package.py --retries 20 --delay-seconds 15" in text
    assert "python -m pip install agilab" not in text
    assert "Validate clean package first proof" in text
    assert "agilab first-proof --json --no-manifest --max-seconds 60" in text
    assert "first-proof exceeded runtime budget" in text
    assert "Upload first-proof artifact" in text
    assert "public-demo-smoke" in text
    assert "python tools/hf_space_smoke.py --json --timeout 30 --target-seconds 30" in text
    assert "--hf-smoke-json hf-space-smoke.json" in text
    assert "Upload hosted proof artifacts" in text
    assert "Repository tests are intentionally local-only" not in text


def test_docs_workflows_block_stale_release_proof_github_runs() -> None:
    for path in (DOCS_SOURCE_GUARD_WORKFLOW_PATH, DOCS_PUBLISH_WORKFLOW_PATH):
        text = path.read_text(encoding="utf-8")
        assert "GH_TOKEN: ${{ github.token }}" in text
        assert "tools/release_proof_report.py --check --check-github-runs --compact" in text

    guard_text = DOCS_SOURCE_GUARD_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "actions: read" in guard_text


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
