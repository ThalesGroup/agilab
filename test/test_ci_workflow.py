from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/ci.yml")


def test_ci_workflow_includes_minimal_first_proof_contract() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Compile critical Python entrypoints" in text
    assert "Validate first-proof command contract" in text
    assert "python src/agilab/first_proof_cli.py --print-only --json" in text
    assert "clean-public-install" in text
    assert "Install released AGILAB package" in text
    assert "python -m pip install agilab" in text
    assert "Validate clean package first proof" in text
    assert "agilab first-proof --json" in text
    assert "Repository tests are intentionally local-only" not in text
