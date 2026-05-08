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
    assert (
        "python -m pip install agilab && python -m agilab.lab_run first-proof --json"
        in matrix
    )
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

    assert "Four short demos" in demos
    assert "Local app proof" in demos
    assert "Distributed worker route" in demos
    assert "MLflow tracking route" in demos
    assert "Notebook migration route" in demos
    assert "python -m pip install agilab" in demos
    assert "tools/public_proof_scenarios.py --compact" in demos
    assert "--first-proof-json first-proof.json --hf-smoke-json hf-space-smoke.json" in demos
    assert "python -m agilab.lab_run first-proof --json --max-seconds 60" in demos
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
    assert f"docs-source-guard run {ci_runs['docs-source-guard']['run_id']}" in page
    assert f"coverage run {ci_runs['coverage']['run_id']}" in page
    assert release["hf_space_commit"] in page
    assert "python -m agilab.lab_run first-proof --json --max-seconds 60" in page
    assert "does not certify every remote cluster topology" in normalized_page
    assert "release-proof" in index
    assert ":doc:`release-proof`" in demos


def test_environment_docs_scope_local_secret_persistence() -> None:
    environment = (DOCS_SOURCE / "environment.rst").read_text(encoding="utf-8")

    assert "OS keyrings" in environment
    assert "enterprise vaults" in environment
    assert "short-lived environment variables" in environment
    assert "$HOME/.agilab/.env" in environment
    assert "local plaintext developer convenience" in environment
    assert "not a shared secret manager" in environment


def test_readme_uses_recommended_workbench_positioning() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "AGILAB is a reproducible AI/ML workbench for engineering teams." in readme
    assert "AGILAB complements MLflow." in readme
    assert "It is not a replacement for MLflow or production\nMLOps platforms." in readme


def test_package_publishing_policy_addresses_common_audit_misreads() -> None:
    policy = (DOCS_SOURCE / "package-publishing-policy.rst").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "Real PyPI publication must not silently auto-create\n``.postN`` releases" in policy
    assert "multiple same-day post releases should be treated as release\nprocess debt" in policy
    assert "disallow_untyped_defs = true" in policy
    assert "runs mypy with ``--strict``" in policy
    assert "``setup.py`` is intentionally kept alongside ``pyproject.toml``" in policy
    assert "It is not a\nleftover from an incomplete packaging migration." in policy
    assert "Real PyPI publication must use GitHub OIDC Trusted Publishing" in policy
    assert "Long-lived PyPI\nAPI tokens are not part of the normal release path" in policy
    assert "setup.py is intentionally kept alongside pyproject.toml; it is not a migration\nleftover." in readme


def test_service_mode_documents_non_executable_queue_contract() -> None:
    service_mode = (DOCS_SOURCE / "service-mode.rst").read_text(encoding="utf-8")

    assert "Service queue security contract" in service_mode
    assert "agi.service.task.v1" in service_mode
    assert "*.task.json" in service_mode
    assert "*.task.pkl" in service_mode
    assert "without deserializing" in service_mode
