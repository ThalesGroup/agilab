from __future__ import annotations

from functools import lru_cache
import importlib.util
import re
import sys
from pathlib import Path


README = Path("README.md")
PYPI_README = Path("README.pypi.md")
AGI_CORE_README = Path("src/agilab/core/agi-core/README.md")
COMPONENT_READMES = (
    Path("src/agilab/core/agi-core/README.md"),
    Path("src/agilab/core/agi-env/README.md"),
    Path("src/agilab/core/agi-node/README.md"),
    Path("src/agilab/core/agi-cluster/README.md"),
    Path("src/agilab/lib/agi-gui/README.md"),
)
CHANGELOG = Path("CHANGELOG.md")
PUBLIC_DOC_PAGES = (
    Path("docs/source/agilab-demo.rst"),
    Path("docs/source/demos.rst"),
    Path("docs/source/quick-start.rst"),
)
ADOPTION_DOC_PAGES = (
    Path("docs/source/index.rst"),
    Path("docs/source/newcomer-guide.rst"),
)
POSITIONING_DOC = Path("docs/source/agilab-mlops-positioning.rst")
STRATEGIC_DOC = Path("docs/source/strategic-potential.rst")
FEATURES_DOC = Path("docs/source/features.rst")
COMPATIBILITY_DOC = Path("docs/source/compatibility-matrix.rst")
COMPATIBILITY_MATRIX = Path("docs/source/data/compatibility_matrix.toml")
DOCS_SOURCE = Path("docs/source")
PUBLIC_HF_SPACE_URL = "https://huggingface.co/spaces/jpmorard/agilab"
PUBLIC_HF_SPACE_BADGE = "https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge"
AGI_CORE_NOTEBOOK_URL = "https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb"
AGI_CORE_NOTEBOOK_BADGE = "https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge"
HF_RUNTIME_URL = "https://jpmorard-agilab.hf.space"
QUICK_START_URL = "https://thalesgroup.github.io/agilab/quick-start.html"
RELEASES_URL = "https://github.com/ThalesGroup/agilab/releases"
CURRENT_RELEASE_VERSION = "2026.04.29.post3"
LATEST_RELEASE_URL = f"{RELEASES_URL}/tag/v2026.04.30-4"
KPI_BUNDLE_TOOL = Path("tools/kpi_evidence_bundle.py").resolve()


@lru_cache(maxsize=1)
def _load_kpi_module():
    spec = importlib.util.spec_from_file_location(
        "kpi_evidence_bundle_for_public_demo_links_test",
        KPI_BUNDLE_TOOL,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _kpi_snapshot() -> dict:
    return _load_kpi_module().build_score_snapshot()


def _kpi_score(name: str) -> str:
    return _kpi_snapshot()["summary"]["score_components"][name]


def _overall_score() -> str:
    return _kpi_snapshot()["supported_score"]


def _baseline_score() -> str:
    return _load_kpi_module().BASELINE_REVIEW_SCORE


def _strategic_score() -> str:
    return _kpi_snapshot()["summary"]["strategic_potential_score"]


def test_readme_advertises_public_huggingface_space_page() -> None:
    readme = README.read_text(encoding="utf-8")

    assert PUBLIC_HF_SPACE_URL in readme
    assert "AGILAB Space" in readme


def test_pypi_readme_uses_same_public_demo_entry_points() -> None:
    readme = PYPI_README.read_text(encoding="utf-8")

    assert PUBLIC_HF_SPACE_URL in readme
    assert PUBLIC_HF_SPACE_BADGE in readme
    assert AGI_CORE_NOTEBOOK_URL in readme
    assert AGI_CORE_NOTEBOOK_BADGE in readme
    assert "flight_project" in readme
    assert "uav_relay_queue_project" in readme
    assert "demo request" not in readme.lower()
    assert "issues/new" not in readme


def test_readme_uses_hf_space_badge_for_primary_link_without_robot_command() -> None:
    readme = README.read_text(encoding="utf-8")

    assert (
        f'<a href="{PUBLIC_HF_SPACE_URL}"><img src="{PUBLIC_HF_SPACE_BADGE}" '
        'alt="AGILAB Space" /></a>'
    ) in readme
    assert HF_RUNTIME_URL not in readme


def test_readme_uses_agi_core_notebook_badge_for_api_route() -> None:
    readme = README.read_text(encoding="utf-8")

    assert (
        f'<a href="{AGI_CORE_NOTEBOOK_URL}"><img src="{AGI_CORE_NOTEBOOK_BADGE}" '
        'alt="agi-core notebook" /></a>'
    ) in readme


def test_component_readmes_do_not_embed_umbrella_demo_links() -> None:
    forbidden = (
        PUBLIC_HF_SPACE_URL,
        PUBLIC_HF_SPACE_BADGE,
        HF_RUNTIME_URL,
        "AGILAB Space",
        "public AGILAB Space",
        "docs-agilab",
        "open-in-kaggle.svg",
        "colab-badge.svg",
    )

    for path in COMPONENT_READMES:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{path} should stay component-scoped; found {marker!r}"


def test_agi_core_component_readme_stays_package_scoped() -> None:
    component_readme = AGI_CORE_README.read_text(encoding="utf-8")

    assert "https://thalesgroup.github.io/agilab/agi-core-architecture.html" in component_readme
    assert "https://thalesgroup.github.io/agilab/notebook-quickstart.html" not in component_readme
    assert AGI_CORE_NOTEBOOK_URL not in component_readme
    assert AGI_CORE_NOTEBOOK_BADGE not in component_readme


def test_public_docs_link_to_hf_space_page_not_runtime_host() -> None:
    for path in PUBLIC_DOC_PAGES:
        text = path.read_text(encoding="utf-8")
        assert PUBLIC_HF_SPACE_URL in text
        assert HF_RUNTIME_URL not in text


def test_docs_sidebar_exposes_both_public_demo_lanes() -> None:
    index = Path("docs/source/index.rst").read_text(encoding="utf-8")
    demos = Path("docs/source/demos.rst").read_text(encoding="utf-8")
    agilab_demo = Path("docs/source/agilab-demo.rst").read_text(encoding="utf-8")
    use_sidebar_block = index.split(":caption: Use", 1)[1].split(":caption: Build", 1)[0]

    assert "AGILAB Demo <agilab-demo>" in index
    assert "notebook-quickstart" in index
    assert "AGILAB Demo <agilab-demo>" in use_sidebar_block
    assert "notebook-quickstart" in use_sidebar_block
    assert use_sidebar_block.index("AGILAB Demo <agilab-demo>") < use_sidebar_block.index("notebook-quickstart")
    assert ":doc:`agilab-demo`" in demos
    assert ":doc:`notebook-quickstart`" in demos
    assert "sidebar-visible counterpart" in agilab_demo


def test_public_demo_docs_define_single_flight_view_maps_route() -> None:
    demos = Path("docs/source/demos.rst").read_text(encoding="utf-8")
    agilab_demo = Path("docs/source/agilab-demo.rst").read_text(encoding="utf-8")
    normalized_agilab_demo = " ".join(agilab_demo.split())

    assert "``flight_project``" in demos
    assert "``view_maps`` analysis" in demos
    assert "``uav_relay_queue_project`` is the UAV Relay Queue RL demo" in demos

    for phrase in (
        "confirm ``flight_project`` is selected in ``PROJECT``",
        "inspect the generated execution snippet in ``ORCHESTRATE``",
        "open ``ANALYSIS`` and finish on the ``view_maps`` operator view",
        "``ANALYSIS`` opens the ``view_maps`` route without a startup error",
    ):
        assert phrase in normalized_agilab_demo


def test_readme_uses_quick_start_link_with_badges_not_a_route_table() -> None:
    readme = README.read_text(encoding="utf-8")

    assert f"## [Quick Start]({QUICK_START_URL})" in readme
    assert readme.count(QUICK_START_URL) == 1
    assert "## Start Here" not in readme
    assert "## Maintainer Checks" not in readme
    assert "Notebook quickstart" not in readme
    assert "notebook-quickstart.html" not in readme
    for maintainer_command in (
        "tools/compatibility_report.py",
        "tools/hf_space_smoke.py --json",
        "tools/agilab_web_robot.py",
        "tools/production_readiness_report.py",
        "tools/kpi_evidence_bundle.py",
    ):
        assert maintainer_command not in readme
    assert "| Need | Start here | Outcome |" not in readme
    assert "Browser preview" not in readme
    assert "Full UI path" not in readme
    assert "API/notebook" not in readme
    assert 'alt="AGILAB Space"' in readme
    assert 'alt="agi-core notebook"' in readme
    assert "## First Run" in readme
    assert "Then in the UI:" not in readme
    assert "PROJECT` -> select" not in readme
    assert "tools/newcomer_first_proof.py --json" in readme
    assert "ease of adoption" in readme
    assert _kpi_score("Ease of adoption") in readme


def test_readme_captures_research_experimentation_evidence() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "research experimentation" in readme
    assert _kpi_score("Research experimentation") in readme


def test_readme_captures_engineering_prototyping_evidence() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "engineering prototyping" in readme
    assert _kpi_score("Engineering prototyping") in readme


def test_readme_captures_production_readiness_evidence() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "production readiness" in readme
    assert _kpi_score("Production readiness") in readme


def test_readme_captures_overall_public_evaluation_evidence() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "## Evaluation Snapshot" in readme
    assert "## CODEX 5.5 Evaluation Snapshot" not in readme
    assert "CODEX 5.5 working summary" in readme
    assert "AI/ML experimentation workbench" in readme
    assert "not as a replacement for mature orchestration or production MLOps platforms" in readme
    assert "project setup, environment management, execution, and result analysis" in readme
    assert "Overall public evaluation" in readme
    assert f"{_baseline_score()}` ->" not in readme
    assert _overall_score() in readme
    assert "rounded category average" in readme
    assert _kpi_score("Ease of adoption") in readme
    assert "public KPI bundle" in readme


def test_readme_links_to_mlops_positioning_page() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "MLOps positioning" in readme
    assert "https://thalesgroup.github.io/agilab/agilab-mlops-positioning.html" in readme


def test_readme_links_to_strategic_scorecard_page() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "strategic score movement rule" in readme
    assert "Strategic scorecard" in readme
    assert "https://thalesgroup.github.io/agilab/strategic-potential.html" in readme


def test_docs_link_positioning_to_strategic_scorecard() -> None:
    index = Path("docs/source/index.rst").read_text(encoding="utf-8")
    positioning = POSITIONING_DOC.read_text(encoding="utf-8")
    strategic = STRATEGIC_DOC.read_text(encoding="utf-8")

    assert "strategic-potential" in index
    assert ":doc:`strategic-potential`" in positioning
    assert "Score movement rule" in strategic
    assert "4.3 / 5" in strategic


def test_public_docs_do_not_teach_stale_agi_run_snippets() -> None:
    stale_fragments = (
        "AGI_command_flight.py",
        "asyncio.get_event_loop()",
        "AGI._",
        "mode=13",
        "mode=15",
        "modes_enabled=13",
        "modes_enabled=15",
    )
    legacy_run_call = re.compile(
        r"AGI\.run\(\s*\n\s*app_env,\s*\n(?:(?!request=).)*?\bmode\s*=",
        re.DOTALL,
    )
    paths = sorted(
        path
        for pattern in ("*.rst", "*.py")
        for path in DOCS_SOURCE.rglob(pattern)
    )
    offenders: list[str] = []

    for path in paths:
        text = path.read_text(encoding="utf-8")
        offenders.extend(
            f"{path}: contains {fragment!r}"
            for fragment in stale_fragments
            if fragment in text
        )
        if legacy_run_call.search(text):
            offenders.append(f"{path}: contains legacy AGI.run(app_env, mode=...) shape")

    assert offenders == []


def test_readme_links_to_public_changelog() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "[Changelog](CHANGELOG.md)" in readme


def test_readme_links_to_public_releases_page() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "[Releases]" in readme
    assert RELEASES_URL in readme


def test_changelog_documents_current_public_release() -> None:
    changelog = CHANGELOG.read_text(encoding="utf-8")

    assert f"## [{CURRENT_RELEASE_VERSION}] - 2026-04-29" in changelog
    assert LATEST_RELEASE_URL in changelog
    assert f"Published AGILAB `{CURRENT_RELEASE_VERSION}` to PyPI" in changelog
    assert "create or update the" in changelog


def test_docs_index_links_to_latest_public_release() -> None:
    text = Path("docs/source/index.rst").read_text(encoding="utf-8")

    assert "latest public GitHub release" in text
    assert LATEST_RELEASE_URL in text


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
    assert _kpi_score("Ease of adoption") in text
    assert "5.86s" in text
    assert "600s" in text


def test_positioning_docs_capture_executive_review_summary() -> None:
    text = POSITIONING_DOC.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Executive review summary" in text
    assert "AI/ML experimentation workbench" in text
    assert "not as a production MLOps replacement" in normalized
    assert "project setup, environment management, execution, and result analysis" in normalized
    assert "Industrial AI prototypes" in text
    assert "Notebook-to-application workflow consolidation" in text
    assert "Production model serving" in text
    assert "Enterprise governance and audit" in text


def test_positioning_docs_capture_research_experimentation_evidence() -> None:
    text = POSITIONING_DOC.read_text(encoding="utf-8")

    assert "Research experimentation evidence" in text
    assert "Research experimentation" in text
    assert _kpi_score("Research experimentation") in text
    assert "lab_steps.toml" in text
    assert "supervisor notebook export" in text
    assert "MLflow tracking" in text
    assert "notebook-migration example" in text
    assert "first-class reduce contract" in text


def test_positioning_docs_capture_engineering_prototyping_evidence() -> None:
    text = POSITIONING_DOC.read_text(encoding="utf-8")

    assert "Engineering prototyping evidence" in text
    assert "Engineering prototyping" in text
    assert _kpi_score("Engineering prototyping") in text
    assert "app-shaped prototype" in text
    assert "pipeline_view" in text
    assert "analysis-page templates" in text
    assert "first-proof wizard" in text


def test_positioning_docs_capture_production_readiness_evidence() -> None:
    text = POSITIONING_DOC.read_text(encoding="utf-8")

    assert "Production readiness evidence" in text
    assert "Production readiness" in text
    assert _kpi_score("Production readiness") in text
    assert "workflow-parity profiles" in text
    assert "compatibility matrix" in text
    assert "service health gates" in text
    assert "promotion_decision.json" in text
    assert "online monitoring" in text


def test_positioning_docs_capture_strategic_potential_evidence() -> None:
    text = POSITIONING_DOC.read_text(encoding="utf-8")

    assert "Strategic potential evidence" in text
    assert "Strategic potential" in text
    assert _strategic_score() in text
    assert "TRL" in text
    assert "public demo path" in text
    assert "handoff model" in text


def test_features_docs_capture_engineering_prototyping_evidence() -> None:
    text = FEATURES_DOC.read_text(encoding="utf-8")

    assert "Engineering prototyping evidence" in text
    assert "Engineering prototyping" in text
    assert _kpi_score("Engineering prototyping") in text
    assert "app_args_form.py" in text
    assert "app_settings.toml" in text
    assert "pipeline_view.dot" in text


def test_features_docs_capture_production_readiness_controls() -> None:
    text = FEATURES_DOC.read_text(encoding="utf-8")

    assert "Production-readiness controls" in text
    assert "Production readiness" in text
    assert _kpi_score("Production readiness") in text
    assert "tools/pypi_publish.py" in text
    assert "tools/service_health_check.py" in text
    assert "promotion_decision.json" in text
    assert "SECURITY.md" in text


def test_compatibility_matrix_marks_public_hf_demo_validated() -> None:
    matrix = COMPATIBILITY_MATRIX.read_text(encoding="utf-8")
    doc = COMPATIBILITY_DOC.read_text(encoding="utf-8")
    normalized_doc = " ".join(doc.split())

    assert 'id = "agilab-hf-demo"' in matrix
    assert 'status = "validated"' in matrix
    assert "tools/hf_space_smoke.py --json" in matrix
    assert "AGILAB Hugging Face demo" in doc
    assert "workflow-backed compatibility report" in normalized_doc
    assert "tools/compatibility_report.py --compact" in normalized_doc
    assert "required public statuses" in normalized_doc
    assert "tools/hf_space_smoke.py --json" in doc
    assert "tools/kpi_evidence_bundle.py" in doc
