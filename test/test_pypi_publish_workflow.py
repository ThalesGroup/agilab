from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/pypi-publish.yaml")


def test_pypi_publish_runs_live_artifact_index_evidence_before_publish() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "release-evidence:" in text
    assert "actions: read" in text
    assert "tools/github_actions_artifact_index.py" in text
    assert "--write-sample-directory" in text
    assert "--live-github" in text
    assert "tools/ci_artifact_harvest_report.py" in text
    assert "tools/compatibility_report.py" in text
    assert "--artifact-index \"$RUNNER_TEMP/artifact_index.json\"" in text
    assert "public-evidence-sample" in text
    assert "publish-library-packages:\n    needs:\n      - test\n      - release-evidence" in text


def test_pypi_publish_release_tests_use_local_parity_profiles() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "tools/workflow_parity.py" in text
    assert 'python-version: ["3.13"]' in text
    assert "uv --preview-features extra-build-dependencies run --no-project python tools/workflow_parity.py" in text
    assert "--profile agi-env" in text
    assert "--profile agi-gui" in text
    assert "--profile agi-core-combined" in text
    assert "uv run --dev --project agi-cluster python -m pytest" not in text
