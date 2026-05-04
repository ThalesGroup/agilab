from pathlib import Path
import tomllib


DOCS_SOURCE = Path("docs/source")


def _release_proof_manifest() -> dict:
    with (DOCS_SOURCE / "data" / "release_proof.toml").open("rb") as stream:
        return tomllib.load(stream)


def test_architecture_five_minutes_page_exposes_layer_map() -> None:
    page = (DOCS_SOURCE / "architecture-five-minutes.rst").read_text(encoding="utf-8")
    index = (DOCS_SOURCE / "index.rst").read_text(encoding="utf-8")

    assert "Architecture in 5 minutes" in page
    assert "reproducible AI/ML experimentation workbench for engineering teams" in page
    assert "Streamlit UI, CLI wrappers, or notebook entry points" in page
    assert "AgiEnv: settings, project selection, app paths, logs, local workspace" in page
    assert "Dask back-plane and optional MLflow tracking" in page
    assert "does not replace MLflow, Kubeflow" in page
    assert "architecture-five-minutes" in index


def test_compatibility_matrix_promotes_clean_package_install_evidence() -> None:
    matrix = (DOCS_SOURCE / "data" / "compatibility_matrix.toml").read_text(
        encoding="utf-8"
    )
    docs = (DOCS_SOURCE / "compatibility-matrix.rst").read_text(encoding="utf-8")

    assert 'id = "published-package-route"' in matrix
    assert 'status = "validated"' in matrix
    assert 'platforms = ["Linux CI", "macOS CI", "Windows CI"]' in matrix
    assert "python -m pip install agilab && agilab first-proof --json" in matrix
    assert "60-second first-proof runtime budget" in matrix
    assert "Platform coverage snapshot" in docs
    assert "macOS local" in docs
    assert "Linux package" in docs
    assert "macOS package" in docs
    assert "Windows / WSL2" in docs
    assert "VM / SSH cluster" in docs
    assert "Hugging Face Space" in docs
    assert "tools/public_proof_scenarios.py --compact" in docs
    assert "tools/first_launch_robot.py --json" in docs
    assert "tools/security_hygiene_report.py --compact" in docs
    assert "--first-proof-json first-proof.json --hf-smoke-json hf-space-smoke.json" in docs


def test_demo_page_keeps_three_generic_demo_routes() -> None:
    demos = (DOCS_SOURCE / "demos.rst").read_text(encoding="utf-8")

    assert "Three short demos" in demos
    assert "Local app proof" in demos
    assert "Distributed worker route" in demos
    assert "MLflow tracking route" in demos
    assert "python -m pip install agilab" in demos
    assert "tools/public_proof_scenarios.py --compact" in demos
    assert "--first-proof-json first-proof.json --hf-smoke-json hf-space-smoke.json" in demos
    assert "agilab first-proof --json --max-seconds 60" in demos
    assert "tools/service_health_check.py --format json" in demos


def test_release_proof_page_collects_public_audit_evidence() -> None:
    page = (DOCS_SOURCE / "release-proof.rst").read_text(encoding="utf-8")
    normalized_page = " ".join(page.split())
    index = (DOCS_SOURCE / "index.rst").read_text(encoding="utf-8")
    demos = (DOCS_SOURCE / "demos.rst").read_text(encoding="utf-8")
    manifest = _release_proof_manifest()
    release = manifest["release"]
    ci_runs = {row["id"]: row for row in manifest["ci_runs"]}

    assert "Release Proof" in page
    assert "generated from docs/source/data/release_proof.toml" in page
    assert f"{release['package_name']}=={release['package_version']}" in page
    assert release["github_release_tag"] in page
    assert f"repo-guardrails run {ci_runs['release-guardrails']['run_id']}" in page
    assert f"repo-guardrails run {ci_runs['ci-maintenance-guardrails']['run_id']}" in page
    assert release["hf_space_commit"] in page
    assert "agilab first-proof --json --max-seconds 60" in page
    assert "does not certify every remote cluster topology" in normalized_page
    assert "release-proof" in index
    assert ":doc:`release-proof`" in demos


def test_readme_uses_recommended_workbench_positioning() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert (
        "AGILAB is a reproducible AI/ML experimentation workbench for "
        "engineering teams, bridging local interactive development, distributed "
        "execution, and result analysis"
    ) in readme
    assert "not as a replacement for mature orchestration or production MLOps platforms" in readme
