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
    assert 'python -m pip install "agilab[examples]"' in demos
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
    package_spec = release["package_name"]
    if extras := release.get("package_extras", []):
        package_spec = f"{package_spec}[{','.join(extras)}]"
    ci_runs = {row["id"]: row for row in manifest["ci_runs"]}

    assert "Release Proof" in page
    assert "generated from docs/source/data/release_proof.toml" in page
    assert f"{package_spec}=={release['package_version']}" in page
    assert release["github_release_tag"] in page
    assert f"repo-guardrails run {ci_runs['release-guardrails']['run_id']}" in page
    assert f"docs-source-guard run {ci_runs['docs-source-guard']['run_id']}" in page
    assert f"coverage run {ci_runs['coverage']['run_id']}" in page
    assert release["hf_space_commit"] in page
    assert "python -m agilab.lab_run first-proof --json --max-seconds 60" in page
    assert (
        "Live public-demo availability is checked only when a public-demo-smoke run"
        in normalized_page
    )
    assert "opened the public AGILAB demo route during the release guardrail run" not in page
    assert "hosted demo availability at the time of validation" not in page
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


def test_security_policy_addresses_public_audit_adoption_boundaries() -> None:
    security = Path("SECURITY.md").read_text(encoding="utf-8")

    assert "trusted-operator experimentation workbench" in security
    assert "Recommended use without additional platform hardening" in security
    assert "Conditional use only after hardening" in security
    assert "Not recommended as-is" in security
    assert "public exposure without authentication, TLS, and sandboxing" in security
    assert "Multi-tenant service use" in security
    assert "production ML serving" in security
    assert "APPS_REPOSITORY" in security
    assert "explicit allowlist" in security
    assert "commit SHA or immutable tag" in security
    assert "reject floating branches" in security
    assert "CycloneDX SBOM" in security
    assert "pip-audit" in security
    assert "actual install profile" in security
    assert "release-proof" in security
    assert "GitHub tag and PyPI version" in security
    assert "republish the documentation" in security


def test_quick_start_documents_security_adoption_checkpoint() -> None:
    quick_start = (DOCS_SOURCE / "quick-start.rst").read_text(encoding="utf-8")
    beta_readiness = (DOCS_SOURCE / "beta-readiness.rst").read_text(encoding="utf-8")

    assert "Shared or team adoption check" in quick_start
    assert "agilab security-check --json > security-check.json" in quick_start
    assert "workflow_parity.py --profile security-adoption" in quick_start
    assert "AGILAB_SECURITY_CHECK_STRICT=1" in quick_start
    assert "test-results/security-check.json" in beta_readiness
    assert "AGILAB_SECURITY_CHECK_STRICT=1" in beta_readiness


def test_readme_uses_recommended_workbench_positioning() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    local_pypi_proof = readme.split("### Local PyPI UI Proof", 1)[1].split(
        "For a zero-install browser preview", 1
    )[0]

    assert "AGILAB is a reproducible AI/ML workbench for engineering teams." in readme
    assert "AGILAB complements MLflow and production MLOps platforms." in readme
    assert "MLflow tracks experiments; AGILAB transforms notebooks and scripts" in readme
    assert "reproducible execution and analysis layer" in readme
    assert "agilab\n```" in local_pypi_proof
    assert "first-proof" not in local_pypi_proof
    assert "If startup fails, run a progressive fallback" in readme
    assert "| `examples` extra |" in readme
    assert "| `agents` extra |" in readme
    assert "| `dev` extra |" in readme


def test_quick_start_documents_public_install_tiers() -> None:
    quick_start = (DOCS_SOURCE / "quick-start.rst").read_text(encoding="utf-8")
    ui_route = quick_start.split(
        "The base package install is intentionally CLI/core only. Install the UI profile",
        1,
    )[1].split("Optional feature stacks", 1)[0]

    assert "``agilab[agents]`` for the packaged agent workflow client dependencies" in quick_start
    assert "``agilab[examples]`` for notebook/demo helper dependencies" in quick_start
    assert "``agilab[pages]`` for analysis\npage bundles without the full UI profile" in quick_start
    assert "``agilab[dev]`` for contributor-only test/build tooling" in quick_start
    assert 'tool install --upgrade "agilab[ui]"\n    agilab' in ui_route
    assert "agilab first-proof --json --max-seconds 60" not in ui_route
    assert "agilab dry-run" in ui_route
    assert "agilab first-proof --json --with-ui" in ui_route
    assert "base, UI, pages, AI, agents, examples, MLflow, local-LLM, offline, and dev\ninstall profiles" in quick_start


def test_package_publishing_policy_addresses_common_audit_misreads() -> None:
    policy = (DOCS_SOURCE / "package-publishing-policy.rst").read_text(encoding="utf-8")
    normalized_policy = " ".join(policy.split())
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "Release synchronization contract" in policy
    assert "may have several package versions" in normalized_policy
    assert "one committed dependency graph" in normalized_policy
    assert "exact internal dependency pins used by bundle packages" in policy
    assert "must not rewrite versions or dependency metadata during the upload job" in normalized_policy
    assert "dependency-policy hygiene, docs mirror\nintegrity, installer behavior" in policy
    assert "Real PyPI publication must not silently auto-create\n``.postN`` releases" in policy
    assert "multiple same-day post releases should be treated as release\nprocess debt" in policy
    assert "disallow_untyped_defs = true" in policy
    assert "runs mypy with ``--strict``" in policy
    assert "``setup.py`` is intentionally kept alongside ``pyproject.toml``" in policy
    assert "It is not a\nleftover from an incomplete packaging migration." in policy
    assert "Real PyPI publication must use GitHub OIDC Trusted Publishing" in policy
    assert "Long-lived PyPI\nAPI tokens are not part of the normal release path" in policy
    assert "package-publishing-policy.html" in readme


def test_service_mode_documents_non_executable_queue_contract() -> None:
    service_mode = (DOCS_SOURCE / "service-mode.rst").read_text(encoding="utf-8")

    assert "Service queue security contract" in service_mode
    assert "agi.service.task.v1" in service_mode
    assert "*.task.json" in service_mode
    assert "*.task.pkl" in service_mode
    assert "without deserializing" in service_mode
