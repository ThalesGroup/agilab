from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/ci.yml")


def test_ci_workflow_includes_minimal_first_proof_contract() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Compile critical Python entrypoints" in text
    assert "Validate first-proof command contract" in text
    assert "python src/agilab/first_proof_cli.py --print-only --json" in text
    assert "Repository tests are intentionally local-only" not in text
