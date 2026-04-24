from __future__ import annotations

from pathlib import Path


README = Path("README.md")
PUBLIC_DOC_PAGES = (
    Path("docs/source/demos.rst"),
    Path("docs/source/quick-start.rst"),
)
ADOPTION_DOC_PAGES = (
    Path("docs/source/index.rst"),
    Path("docs/source/newcomer-guide.rst"),
)
POSITIONING_DOC = Path("docs/source/agilab-mlops-positioning.rst")
FEATURES_DOC = Path("docs/source/features.rst")
COMPATIBILITY_DOC = Path("docs/source/compatibility-matrix.rst")
COMPATIBILITY_MATRIX = Path("docs/source/data/compatibility_matrix.toml")
PUBLIC_HF_SPACE_URL = "https://huggingface.co/spaces/jpmorard/agilab"
HF_RUNTIME_URL = "https://jpmorard-agilab.hf.space"


def test_readme_advertises_public_huggingface_space_page() -> None:
    readme = README.read_text(encoding="utf-8")

    assert PUBLIC_HF_SPACE_URL in readme
    assert "AGILAB-demo" in readme
    assert "self-serve public Hugging Face Spaces demo" in readme


def test_readme_links_to_hf_space_page_not_runtime_host() -> None:
    readme = README.read_text(encoding="utf-8")

    assert HF_RUNTIME_URL not in readme


def test_public_docs_link_to_hf_space_page_not_runtime_host() -> None:
    for path in PUBLIC_DOC_PAGES:
        text = path.read_text(encoding="utf-8")
        assert PUBLIC_HF_SPACE_URL in text
        assert HF_RUNTIME_URL not in text


def test_readme_exposes_three_clear_adoption_routes() -> None:
    readme = README.read_text(encoding="utf-8")

    for phrase in ("See the UI now", "Prove it locally", "Use the API/notebook"):
        assert phrase in readme
    assert "Target: pass the first proof in 10 minutes" in readme
    assert "tools/newcomer_first_proof.py --json" in readme
    assert "Ease of adoption" in readme
    assert "3.5 / 5" in readme
    assert "5.86s" in readme


def test_readme_captures_research_experimentation_evidence() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "Research experimentation" in readme
    assert "4.0 / 5" in readme
    assert "lab_steps.toml" in readme
    assert "MLflow-tracked runs" in readme


def test_readme_captures_engineering_prototyping_evidence() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "Engineering prototyping" in readme
    assert "4.0 / 5" in readme
    assert "app_args_form.py" in readme
    assert "pipeline_view" in readme
    assert "analysis-page" in readme
    assert "templates" in readme


def test_readme_captures_production_readiness_evidence() -> None:
    readme = README.read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "Production readiness" in readme
    assert "3.0 / 5" in readme
    assert "service health gates" in readme
    assert "release-decision page" in readme
    assert "security hardening checklist" in normalized
    assert "production model serving" in readme
    assert "tools/production_readiness_report.py" in readme


def test_readme_captures_overall_public_evaluation_evidence() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "overall public-evaluation evidence" in readme
    assert "3.2 / 5" in readme
    assert "3.5 / 5" in readme
    assert "cross-KPI evidence bundle" in readme
    assert "tools/kpi_evidence_bundle.py" in readme


def test_readme_links_to_mlops_positioning_page() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "MLOps positioning" in readme
    assert "https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html" in readme


def test_public_docs_expose_three_clear_adoption_routes() -> None:
    for path in ADOPTION_DOC_PAGES:
        text = path.read_text(encoding="utf-8")
        for phrase in ("See the UI now", "Prove it locally", "Use the API/notebook"):
            assert phrase in text
        assert "10 minutes" in text


def test_newcomer_docs_capture_adoption_evidence() -> None:
    text = Path("docs/source/newcomer-guide.rst").read_text(encoding="utf-8")

    assert "Adoption evidence" in text
    assert "Ease of adoption" in text
    assert "3.5 / 5" in text
    assert "5.86s" in text
    assert "600s" in text


def test_positioning_docs_capture_research_experimentation_evidence() -> None:
    text = POSITIONING_DOC.read_text(encoding="utf-8")

    assert "Research experimentation evidence" in text
    assert "Research experimentation" in text
    assert "4.0 / 5" in text
    assert "lab_steps.toml" in text
    assert "supervisor notebook export" in text
    assert "MLflow tracking" in text
    assert "notebook-migration example" in text
    assert "first-class reduce contract" in text


def test_positioning_docs_capture_engineering_prototyping_evidence() -> None:
    text = POSITIONING_DOC.read_text(encoding="utf-8")

    assert "Engineering prototyping evidence" in text
    assert "Engineering prototyping" in text
    assert "4.0 / 5" in text
    assert "app-shaped prototype" in text
    assert "pipeline_view" in text
    assert "analysis-page templates" in text
    assert "first-proof wizard" in text


def test_positioning_docs_capture_production_readiness_evidence() -> None:
    text = POSITIONING_DOC.read_text(encoding="utf-8")

    assert "Production readiness evidence" in text
    assert "Production readiness" in text
    assert "3.0 / 5" in text
    assert "workflow-parity profiles" in text
    assert "compatibility matrix" in text
    assert "service health gates" in text
    assert "promotion_decision.json" in text
    assert "online monitoring" in text


def test_positioning_docs_capture_strategic_potential_evidence() -> None:
    text = POSITIONING_DOC.read_text(encoding="utf-8")

    assert "Strategic potential evidence" in text
    assert "Strategic potential" in text
    assert "4.2 / 5" in text
    assert "TRL" in text
    assert "public demo path" in text
    assert "handoff model" in text


def test_features_docs_capture_engineering_prototyping_evidence() -> None:
    text = FEATURES_DOC.read_text(encoding="utf-8")

    assert "Engineering prototyping evidence" in text
    assert "Engineering prototyping" in text
    assert "4.0 / 5" in text
    assert "app_args_form.py" in text
    assert "app_settings.toml" in text
    assert "pipeline_view.dot" in text


def test_features_docs_capture_production_readiness_controls() -> None:
    text = FEATURES_DOC.read_text(encoding="utf-8")

    assert "Production-readiness controls" in text
    assert "Production readiness" in text
    assert "3.0 / 5" in text
    assert "tools/pypi_publish.py" in text
    assert "tools/service_health_check.py" in text
    assert "promotion_decision.json" in text
    assert "SECURITY.md" in text


def test_compatibility_matrix_marks_public_hf_demo_validated() -> None:
    matrix = COMPATIBILITY_MATRIX.read_text(encoding="utf-8")
    doc = COMPATIBILITY_DOC.read_text(encoding="utf-8")

    assert 'id = "agilab-hf-demo"' in matrix
    assert 'status = "validated"' in matrix
    assert "tools/hf_space_smoke.py --json" in matrix
    assert "AGILAB Hugging Face demo" in doc
    assert "tools/hf_space_smoke.py --json" in doc
    assert "tools/kpi_evidence_bundle.py" in doc
