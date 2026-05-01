from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/ci.yml")


def test_ci_workflow_includes_minimal_first_proof_contract() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Compile critical Python entrypoints" in text
    assert "Validate first-proof command contract" in text
    assert "python src/agilab/first_proof_cli.py --print-only --json" in text
    assert "Validate public proof scenarios" in text
    assert "python tools/public_proof_scenarios.py --compact" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert "astral-sh/setup-uv@v7" in text
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
    assert "python -m pip install agilab" in text
    assert "Validate clean package first proof" in text
    assert "agilab first-proof --json --no-manifest --max-seconds 60" in text
    assert "first-proof exceeded runtime budget" in text
    assert "Upload first-proof artifact" in text
    assert "public-demo-smoke" in text
    assert "python tools/hf_space_smoke.py --json --timeout 30 --target-seconds 30" in text
    assert "--hf-smoke-json hf-space-smoke.json" in text
    assert "Upload hosted proof artifacts" in text
    assert "Repository tests are intentionally local-only" not in text
