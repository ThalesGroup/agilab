from __future__ import annotations

from functools import lru_cache
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
import tomllib

from packaging.version import Version

README = Path("README.md")
PYPI_README = Path("README.pypi.md")
AGI_CORE_README = Path("src/agilab/core/agi-core/README.md")
COMPONENT_READMES = (
    Path("src/agilab/core/agi-core/README.md"),
    Path("src/agilab/core/agi-env/README.md"),
    Path("src/agilab/core/agi-node/README.md"),
    Path("src/agilab/core/agi-cluster/README.md"),
    Path("src/agilab/lib/agi-gui/README.md"),
    Path("src/agilab/lib/agi-apps/README.md"),
    Path("src/agilab/lib/agi-pages/README.md"),
)
CHANGELOG = Path("CHANGELOG.md")
PUBLIC_DOC_PAGES = (
    Path("docs/source/agilab-demo.rst"),
    Path("docs/source/demos.rst"),
    Path("docs/source/quick-start.rst"),
    Path("docs/source/release-proof.rst"),
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
RELEASE_PROOF_MANIFEST = Path("docs/source/data/release_proof.toml")
DOCS_SOURCE = Path("docs/source")
NOTEBOOK_EXAMPLES = Path("src/agilab/examples")
METEO_NOTEBOOK_MIGRATION = NOTEBOOK_EXAMPLES / "notebook_migrations/skforecast_meteo_fr"
PUBLIC_HF_SPACE_URL = "https://huggingface.co/spaces/jpmorard/agilab"
PUBLIC_HF_SPACE_BADGE = "https://img.shields.io/badge/AGILAB-Space-0F766E?style=for-the-badge"
AGI_CORE_NOTEBOOK_URL = "https://kaggle.com/kernels/welcome?src=https://github.com/ThalesGroup/agilab/blob/main/src/agilab/examples/notebook_quickstart/agi_core_kaggle_first_run.ipynb"
AGI_CORE_NOTEBOOK_BADGE = "https://img.shields.io/badge/agi--core-notebook-1D4ED8?style=for-the-badge"
HF_RUNTIME_URL = "https://jpmorard-agilab.hf.space"
QUICK_START_URL = "https://thalesgroup.github.io/agilab/quick-start.html"
RELEASES_URL = "https://github.com/ThalesGroup/agilab/releases"
CURRENT_RELEASE_VERSION = "2026.05.01.post4"
KPI_BUNDLE_TOOL = Path("tools/kpi_evidence_bundle.py").resolve()
NOTEBOOK_PIPELINE_IMPORT = Path("src/agilab/notebook_pipeline_import.py").resolve()
AGI_APPS_PYPROJECT = Path("src/agilab/lib/agi-apps/pyproject.toml")


@lru_cache(maxsize=1)
def _release_proof_manifest() -> dict:
    with RELEASE_PROOF_MANIFEST.open("rb") as stream:
        return tomllib.load(stream)


LATEST_RELEASE_URL = _release_proof_manifest()["release"]["github_release_url"]


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
def _load_notebook_pipeline_import_module():
    spec = importlib.util.spec_from_file_location(
        "notebook_pipeline_import_for_public_demo_links_test",
        NOTEBOOK_PIPELINE_IMPORT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_examples_do_not_use_root_examples_tree() -> None:
    tracked_root_examples = subprocess.check_output(
        ["git", "ls-files", "examples"],
        text=True,
    ).splitlines()

    assert tracked_root_examples == []


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
    assert "flight_telemetry_project" in readme
    assert "uav_relay_queue_project" in readme
    assert "Advanced Proof Pack" in readme
    assert "advanced-proof-pack.html" in readme
    assert "demo request" not in readme.lower()
    assert "issues/new" not in readme


def test_pypi_readme_tracks_public_readme_contract() -> None:
    readme = README.read_text(encoding="utf-8")
    pypi_readme = PYPI_README.read_text(encoding="utf-8")
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["readme"] == "README.pypi.md"

    synced_fragments = (
        "AGILAB is a reproducible AI/ML workbench for engineering teams.",
        "It turns notebooks and scripts into controlled, executable apps with:",
        "AGILAB complements MLflow and production MLOps platforms.",
        "## Core Flow",
        "### Local PyPI UI Proof",
        'uv --preview-features extra-build-dependencies tool install --upgrade "agilab[ui]"',
        "## Production Boundary",
        "## Dependency And Supply-Chain Boundaries",
        "## Evidence Taxonomy",
        "## Source Version vs Package Version",
        "| `main` branch and root `pyproject.toml` |",
        "| Release tag |",
        "| PyPI package |",
        "| Release proof |",
        "## Source Checkout",
        "## Published Package",
        "| Distributed (Dask) | Stable |",
        "| UI Streamlit | Beta |",
        "| RL examples | Example available |",
        "Current public evaluation summary, refreshed from the public KPI bundle:",
        "Overall public evaluation, rounded category average: `3.8 / 5`.",
        "Package publishing policy",
    )
    for fragment in synced_fragments:
        assert fragment in readme
        assert fragment in pypi_readme

    stale_fragments = (
        "Try this first",
        "## First Run",
        "## Install The Published Package",
        "The PyPI package is the thinnest public entry point",
        'pip install "agilab[ui]"',
        "pip install agilab",
        "| Distributed (Dask) | Beta |",
        "| UI Streamlit | Stable |",
        "| Agents RL | Roadmap |",
        "CODEX 5.5",
        "One forward-looking improvement area is elasticity",
    )
    for fragment in stale_fragments:
        assert fragment not in pypi_readme

    assert pypi_readme.count("agilab[ui]") == 1


def test_source_package_version_contract_is_explicit_and_current() -> None:
    readme = README.read_text(encoding="utf-8")
    pypi_readme = PYPI_README.read_text(encoding="utf-8")
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    release = _release_proof_manifest()["release"]

    source_version = pyproject["project"]["version"]
    package_version = release["package_version"]
    core_dependency = next(
        dependency for dependency in pyproject["project"]["dependencies"] if dependency.startswith("agi-core==")
    )
    core_version = core_dependency.removeprefix("agi-core==").split(";", 1)[0]
    agi_apps_pyproject = tomllib.loads(
        Path("src/agilab/lib/agi-apps/pyproject.toml").read_text(encoding="utf-8")
    )
    agi_apps_version = agi_apps_pyproject["project"]["version"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert Version(source_version) >= Version(package_version)
    assert Version(source_version) >= Version(core_version) >= Version(package_version)
    assert f"agi-apps=={agi_apps_version}" in optional_dependencies["ui"]
    assert f"agi-apps=={agi_apps_version}" in optional_dependencies["examples"]
    assert "version%20alignment-release%20proof" in readme
    assert "version%20alignment-release%20proof" in pypi_readme
    assert "main` branch and root `pyproject.toml" in readme
    assert "main` branch and root `pyproject.toml" in pypi_readme
    assert "release tag, PyPI package version, docs, CI, coverage, and demo proof" in readme
    assert "release tag, PyPI package version, docs, CI, coverage, and demo proof" in pypi_readme


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


def test_readme_agent_skill_badges_use_raw_urls_for_public_renderers() -> None:
    readme = README.read_text(encoding="utf-8")

    assert (
        '<a href=".codex/skills/README.md"><img '
        'src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/skills-codex.svg" '
        'alt="Codex skills" /></a>'
    ) in readme
    assert (
        '<a href=".claude/skills/README.md"><img '
        'src="https://raw.githubusercontent.com/ThalesGroup/agilab/main/badges/skills-claude.svg" '
        'alt="Claude skills" /></a>'
    ) in readme
    assert 'src="badges/skills-codex.svg"' not in readme
    assert 'src="badges/skills-claude.svg"' not in readme


def test_readme_uses_explicit_wheel_yes_badge() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "https://img.shields.io/badge/wheel-yes-0F766E" in readme
    assert 'alt="Wheel: yes"' in readme
    assert "https://img.shields.io/pypi/format/agilab" not in readme
    assert 'alt="PyPI format"' not in readme


def test_readme_first_proof_snippet_uses_console_script_without_manual_venv() -> None:
    readme = README.read_text(encoding="utf-8")
    local_proof = readme.split("### Local PyPI UI Proof", 1)[1].split(
        "For a zero-install browser preview",
        1,
    )[0]

    assert (
        'uv --preview-features extra-build-dependencies tool install --upgrade "agilab[ui]"'
        in local_proof
    )
    assert "agilab first-proof" not in local_proof
    assert "agilab first-proof --json --with-ui" in readme
    assert "If startup fails, run a progressive fallback" in readme
    assert "agilab\n" in local_proof
    assert "python3 -m venv" not in local_proof
    assert "source ~/.agilab-first-proof/bin/activate" not in local_proof
    assert "python -m pip install --upgrade pip" not in local_proof
    assert "python -m agilab.lab_run" not in readme
    assert (
        readme.count(
            'uv --preview-features extra-build-dependencies tool install --upgrade "agilab[ui]"'
        )
        == 1
    )
    assert "The PyPI package is the thinnest public entry point" not in readme


def test_quick_start_package_route_uses_tool_console_script_without_activation() -> None:
    quick_start = Path("docs/source/quick-start.rst").read_text(encoding="utf-8")
    ui_route = quick_start.split(
        "The base package install is intentionally CLI/core only. Install the UI profile",
        1,
    )[1].split("Optional feature stacks", 1)[0]

    assert (
        "uv --preview-features extra-build-dependencies tool install --upgrade agilab"
        in quick_start
    )
    assert (
        'uv --preview-features extra-build-dependencies tool install --upgrade "agilab[ui]"'
        in quick_start
    )
    assert "agilab first-proof --json --max-seconds 60" in quick_start
    assert "agilab first-proof --json --max-seconds 60" not in ui_route
    assert "agilab first-proof --json --with-ui" in quick_start
    assert "source .venv/bin/activate" not in quick_start
    assert "python -m agilab.lab_run" not in quick_start


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
    assert "Advanced Proof Pack <advanced-proof-pack>" in index
    assert "notebook-quickstart" in index
    assert "AGILAB Demo <agilab-demo>" in use_sidebar_block
    assert "Advanced Proof Pack <advanced-proof-pack>" in use_sidebar_block
    assert "notebook-quickstart" in use_sidebar_block
    assert use_sidebar_block.index("AGILAB Demo <agilab-demo>") < use_sidebar_block.index("notebook-quickstart")
    assert ":doc:`agilab-demo`" in demos
    assert ":doc:`advanced-proof-pack`" in demos
    assert ":doc:`notebook-quickstart`" in demos
    assert "sidebar-visible counterpart" in agilab_demo
    assert ":doc:`advanced-proof-pack`" in agilab_demo


def test_public_demo_docs_define_flight_and_meteo_routes() -> None:
    demos = Path("docs/source/demos.rst").read_text(encoding="utf-8")
    agilab_demo = Path("docs/source/agilab-demo.rst").read_text(encoding="utf-8")
    normalized_agilab_demo = " ".join(agilab_demo.split())

    assert "``flight_telemetry_project``" in demos
    assert "``weather_forecast_project``" in demos
    assert "``view_maps``" in demos
    assert "``view_forecast_analysis``" in demos
    assert "``view_release_decision``" in demos
    assert "notebook-migration-skforecast-meteo" in demos
    assert "Notebook migration route" in demos
    assert "Four short demos" in demos
    assert "``uav_relay_queue_project`` is the UAV Relay Queue RL demo" in demos

    for phrase in (
        "confirm ``flight_telemetry_project`` is selected in ``PROJECT``",
        "inspect the generated execution snippet in ``ORCHESTRATE``",
        "open ``ANALYSIS`` and finish on the ``view_maps`` operator view",
        "switch to ``weather_forecast_project``",
        "open ``view_forecast_analysis`` or ``view_release_decision``",
        "use :doc:`notebook-migration-skforecast-meteo` as the companion walkthrough",
        "``ANALYSIS`` opens the ``view_maps`` and ``view_forecast_analysis`` routes without a startup error",
    ):
        assert phrase in normalized_agilab_demo


def test_advanced_proof_pack_surfaces_deeper_public_routes() -> None:
    advanced = Path("docs/source/advanced-proof-pack.rst").read_text(encoding="utf-8")
    demos = Path("docs/source/demos.rst").read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    pypi_readme = PYPI_README.read_text(encoding="utf-8")
    advanced_url = "https://thalesgroup.github.io/agilab/advanced-proof-pack.html"

    for text in (advanced, demos):
        for marker in (
            "``mission_decision_project``",
            "``execution_pandas_project``",
            "``execution_polars_project``",
            "``uav_relay_queue_project``",
            "``inter_project_dag``",
            "``service_mode``",
            ":doc:`data-connectors`",
            ":doc:`release-proof`",
        ):
            assert marker in text

    assert "Advanced Proof Pack" in demos
    assert "advanced--proof-pack" in demos
    assert "kernel-only benchmark" in advanced
    assert "default hosted demo" in advanced
    assert "Polars already manages native internal parallelism" in advanced
    assert "[Advanced Proof Pack]" in readme
    assert advanced_url in readme
    assert "Advanced Proof Pack" in pypi_readme
    assert advanced_url in pypi_readme


def test_readme_surfaces_notebook_migration_as_demo_route() -> None:
    readme = README.read_text(encoding="utf-8")
    pypi_readme = PYPI_README.read_text(encoding="utf-8")
    demo_url = "https://thalesgroup.github.io/agilab/notebook-migration-skforecast-meteo.html"

    assert demo_url in readme
    assert "Notebook Migration Demo" in readme
    assert "`weather_forecast_project` notebook-migration demo" in readme
    assert "Understand notebook-to-app migration" in readme
    assert "Notebook Migration Demo" in pypi_readme
    assert "`weather_forecast_project` notebook-migration demo" in pypi_readme


def test_meteo_notebook_migration_assets_are_complete_and_packaged() -> None:
    required_files = (
        "README.md",
        "notebooks/01_prepare_meteo_series.ipynb",
        "notebooks/02_backtest_temperature_forecast.ipynb",
        "notebooks/03_compare_predictions.ipynb",
        "data/meteo_fr_daily_sample.csv",
        "migrated_project/lab_stages.toml",
        "migrated_project/pipeline_view.dot",
        "analysis_artifacts/forecast_metrics.json",
        "analysis_artifacts/forecast_predictions.csv",
    )

    for relative_path in required_files:
        source = METEO_NOTEBOOK_MIGRATION / relative_path
        assert source.is_file(), f"Missing repository meteo migration asset: {source}"

    package_data = tomllib.loads(AGI_APPS_PYPROJECT.read_text(encoding="utf-8"))["tool"]["setuptools"][
        "package-data"
    ]["agilab.examples"]
    for pattern in (
        "notebook_migrations/*/notebooks/*.ipynb",
        "notebook_migrations/*/analysis_artifacts/*.json",
        "notebook_migrations/*/analysis_artifacts/*.csv",
        "notebook_migrations/*/migrated_project/*.toml",
        "notebook_migrations/*/migrated_project/*.dot",
    ):
        assert pattern in package_data


def test_notebook_quickstart_assets_are_packaged_from_agilab_package_tree() -> None:
    notebook_dir = NOTEBOOK_EXAMPLES / "notebook_quickstart"
    required_notebooks = (
        "agi_core_colab_benchmark.ipynb",
        "agi_core_colab_benchmark_source.ipynb",
        "agi_core_colab_data_dag.ipynb",
        "agi_core_colab_data_dag_pypi.ipynb",
        "agi_core_colab_first_run.ipynb",
        "agi_core_colab_first_run_source.ipynb",
        "agi_core_colab_worker_paths.ipynb",
        "agi_core_colab_worker_paths_pypi.ipynb",
        "agi_core_first_run.ipynb",
        "agi_core_kaggle_first_run.ipynb",
        "agi_core_kaggle_first_run_source.ipynb",
    )

    for notebook in required_notebooks:
        assert (notebook_dir / notebook).is_file(), notebook

    package_data = tomllib.loads(AGI_APPS_PYPROJECT.read_text(encoding="utf-8"))["tool"]["setuptools"][
        "package-data"
    ]["agilab.examples"]
    assert "notebook_quickstart/*.ipynb" in package_data


def test_weather_forecast_project_declares_notebook_import_views() -> None:
    manifest_path = Path("src/agilab/apps/builtin/weather_forecast_project/notebook_import_views.toml")
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    view_modules = {view["module"] for view in manifest["views"]}
    notebook_pipeline_import = _load_notebook_pipeline_import_module()

    assert manifest["schema"] == "agilab.notebook_import_views.v1"
    assert manifest["app"] == "weather_forecast_project"
    assert {"view_forecast_analysis", "view_release_decision"} <= view_modules
    for module in view_modules:
        assert Path(f"src/agilab/apps-pages/{module}").is_dir(), module

    view_plan = notebook_pipeline_import.build_notebook_import_view_plan(
        {
            "source": {
                "source_notebook": (
                    "src/agilab/examples/notebook_migrations/skforecast_meteo_fr/notebooks/"
                    "03_compare_predictions.ipynb"
                )
            }
        },
        preflight={
            "artifact_contract": {
                "outputs": [
                    "analysis_artifacts/forecast_metrics.json",
                    "analysis_artifacts/forecast_predictions.csv",
                ],
            },
        },
        module_name="weather_forecast_project",
        manifest=notebook_pipeline_import.load_notebook_import_view_manifest(manifest_path),
        manifest_path=manifest_path,
    )
    ready_modules = {view["module"] for view in view_plan["matched_views"]}

    assert view_plan["status"] == "matched"
    assert "view_forecast_analysis" in ready_modules


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
    assert "## Source Checkout" in readme
    assert "## First Run" not in readme
    assert "Then in the UI:" not in readme
    assert "PROJECT` -> select" not in readme
    assert "tools/newcomer_first_proof.py --json" not in readme
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
    assert "CODEX 5.5" not in readme
    assert "reproducible AI/ML workbench" in readme
    assert "complements MLflow and production MLOps platforms" in readme
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


def test_readme_links_to_release_proof_page() -> None:
    readme = README.read_text(encoding="utf-8")

    release_proof_url = "https://thalesgroup.github.io/agilab/release-proof.html"

    assert f"[Release Proof]({release_proof_url})" in readme
    assert f"[Release proof]({release_proof_url})" in readme


def test_changelog_documents_current_public_release() -> None:
    changelog = CHANGELOG.read_text(encoding="utf-8")

    assert f"## [{CURRENT_RELEASE_VERSION}] - 2026-05-01" in changelog
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


def test_newcomer_docs_choose_first_example_without_deprecation_confusion() -> None:
    text = Path("docs/source/newcomer-guide.rst").read_text(encoding="utf-8")
    decision_section = text.split("Which example should I start with?", 1)[1].split(
        "Adoption evidence",
        1,
    )[0]

    for phrase in (
        "``flight_telemetry_project``",
        "``mycode_project``",
        "``weather_forecast_project`` or ``mission_decision_project``",
        "Read-only preview examples",
        "``notebook_migrations/skforecast_meteo_fr``",
    ):
        assert phrase in decision_section
    assert "deprecated" not in decision_section.lower()
    assert "deprecation" not in decision_section.lower()


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
    assert "lab_stages.toml" in text
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
