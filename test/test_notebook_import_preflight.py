from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPORT_PATH = Path("tools/notebook_import_preflight.py").resolve()
CORE_PATH = Path("src/agilab/notebook_pipeline_import.py").resolve()
SAMPLE_HELPER_PATH = Path("src/agilab/notebook_import_sample.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _risky_notebook() -> dict[str, object]:
    return {
        "cells": [
            {
                "cell_type": "markdown",
                "source": ["# Risky import\n", "Notebook migration preflight should flag generic cleanup work."],
            },
            {
                "cell_type": "code",
                "source": [
                    "!pip install requests\n",
                    "from pathlib import Path\n",
                    "import pandas as pd\n",
                    "import requests\n",
                    "raw = pd.read_csv('data/orders.csv')\n",
                    "requests.get('https://example.invalid/data')\n",
                    "Path('/tmp/local-only.csv').write_text('debug')\n",
                    "raw.to_parquet('artifacts/orders.parquet')\n",
                ],
            },
        ],
        "metadata": {"kernelspec": {"name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def test_notebook_import_preflight_flags_generic_risks_and_contract(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_import_preflight_core_test_module")
    imported = core_module.build_notebook_pipeline_import(
        notebook=_risky_notebook(),
        source_notebook="risky.ipynb",
    )

    preflight = core_module.build_notebook_import_preflight(imported)
    contract_path = core_module.write_notebook_import_contract(
        tmp_path / "notebook_import_contract.json",
        imported,
        preflight=preflight,
        module_name="demo_project",
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    view_path = core_module.write_notebook_import_pipeline_view(
        tmp_path / "notebook_import_pipeline_view.json",
        imported,
        preflight=preflight,
        module_name="demo_project",
    )
    view = json.loads(view_path.read_text(encoding="utf-8"))
    view_plan_path = core_module.write_notebook_import_view_plan(
        tmp_path / "notebook_import_view_plan.json",
        imported,
        preflight=preflight,
        module_name="demo_project",
        manifest={
            "app": "demo_project",
            "views": [
                {
                    "id": "orders_dataframe",
                    "module": "view_dataframe",
                    "label": "Orders dataframe",
                    "required_artifacts_any": ["artifacts/*.parquet"],
                    "optional_artifacts": ["data/*.csv"],
                }
            ],
        },
    )
    view_plan = json.loads(view_plan_path.read_text(encoding="utf-8"))

    assert preflight["schema"] == "agilab.notebook_import_preflight.v1"
    assert preflight["status"] == "review"
    assert preflight["safe_to_import"] is True
    assert preflight["cleanup_required"] is True
    assert preflight["summary"]["pipeline_stage_count"] == 1
    assert preflight["artifact_contract"]["inputs"] == ["data/orders.csv"]
    assert "/tmp/local-only.csv" in preflight["artifact_contract"]["outputs"]
    assert "artifacts/orders.parquet" in preflight["artifact_contract"]["outputs"]
    assert {
        risk["rule"]
        for risk in preflight["risks"]
        if risk["level"] == "warning"
    } >= {
        "dependency_install",
        "shell_execution",
        "network_access",
        "absolute_path",
        "absolute_artifact_path",
    }
    assert contract["schema"] == "agilab.notebook_import_contract.v1"
    assert contract["module_name"] == "demo_project"
    assert contract["preflight"]["status"] == "review"
    assert contract["artifact_contract"] == preflight["artifact_contract"]
    assert contract["warnings"]
    assert contract["stages"][0]["id"] == "cell-2"
    assert view["schema"] == "agilab.notebook_import_pipeline_view.v1"
    assert view["module_name"] == "demo_project"
    assert {node["kind"] for node in view["nodes"]} >= {
        "markdown_context",
        "notebook_code_cell",
        "artifact",
        "analysis_consumer",
    }
    assert any(edge["kind"] == "artifact_input" for edge in view["edges"])
    assert any(edge["kind"] == "artifact_output" for edge in view["edges"])
    assert any(edge["kind"] == "analysis_consumes" for edge in view["edges"])
    assert view_plan["schema"] == "agilab.notebook_import_view_plan.v1"
    assert view_plan["matching_policy"] == "app_manifest_only"
    assert view_plan["status"] == "matched"
    assert view_plan["matched_views"][0]["module"] == "view_dataframe"
    assert "artifacts/orders.parquet" in view_plan["matched_views"][0]["matched_artifacts"]


def test_supervisor_notebook_import_preserves_artifact_role_inference() -> None:
    core_module = _load_module(CORE_PATH, "notebook_import_preflight_supervisor_roles_module")
    source = "\n".join(
        [
            "import pandas as pd",
            "df = pd.read_csv('shared/orders.csv')",
            "df.to_parquet('shared/summary.parquet')",
        ]
    )
    imported = core_module.build_notebook_pipeline_import(
        notebook={
            "cells": [],
            "metadata": {
                "agilab": {
                    "stages": [
                        {
                            "description": "Build shared summary",
                            "question": "Summarize orders.",
                            "code": source,
                        }
                    ]
                }
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        },
        source_notebook="supervisor.ipynb",
    )

    preflight = core_module.build_notebook_import_preflight(imported)

    assert imported["source"]["import_mode"] == "agilab_supervisor_metadata"
    assert imported["pipeline_stages"][0]["source_cell_index"] == 1
    assert preflight["artifact_contract"]["inputs"] == ["shared/orders.csv"]
    assert preflight["artifact_contract"]["outputs"] == ["shared/summary.parquet"]
    assert preflight["artifact_contract"]["unknown"] == []


def test_notebook_import_metadata_prefills_project_defaults_and_runtime_tags() -> None:
    core_module = _load_module(CORE_PATH, "notebook_import_metadata_defaults_module")
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "metadata": {"tags": ["agilab.manager"]},
                "source": ["print('manager')\n"],
            },
            {
                "cell_type": "code",
                "metadata": {"agilab": {"runtime_role": "worker"}},
                "source": ["print('worker')\n"],
            },
        ],
        "metadata": {
            "agilab": {
                "import": {
                    "schema": "agilab.notebook_import.v1",
                    "recommended_template": "flight_telemetry_project",
                    "project_name_hint": "flight-telemetry-from-notebook-project",
                }
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    imported = core_module.build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook="sample.ipynb",
    )
    preview = core_module.build_lab_stages_preview(imported, module_name="demo_project")

    assert core_module.extract_notebook_import_defaults(notebook) == {
        "schema": "agilab.notebook_import.v1",
        "recommended_template": "flight_telemetry_project",
        "project_name_hint": "flight-telemetry-from-notebook-project",
    }
    assert imported["source"]["import_defaults"]["project_name_hint"] == (
        "flight-telemetry-from-notebook-project"
    )
    assert [stage["NB_RUNTIME_ROLE"] for stage in preview["demo_project"]] == [
        "manager",
        "worker",
    ]
    assert [stage["R"] for stage in preview["demo_project"]] == ["runpy", "agi.run"]


def test_notebook_runtime_role_aliases_and_invalid_metadata_are_handled() -> None:
    core_module = _load_module(CORE_PATH, "notebook_import_runtime_role_aliases_module")
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "metadata": {"tags": ["ignored", "agilab.runtime.worker"]},
                "source": ["print('tagged worker')\n"],
            },
            {
                "cell_type": "code",
                "metadata": {
                    "tags": "agilab.worker",
                    "agilab": {"execution_location": "driver"},
                },
                "source": ["print('metadata manager')\n"],
            },
            {
                "cell_type": "code",
                "metadata": {"agilab_runtime": "app-runtime"},
                "source": ["print('top-level worker')\n"],
            },
            {
                "cell_type": "code",
                "metadata": [],
                "source": ["print('no metadata')\n"],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    imported = core_module.build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook="roles.ipynb",
    )
    preview = core_module.build_lab_stages_preview(imported, module_name="demo_project")
    stages = imported["pipeline_stages"]

    assert core_module.normalize_notebook_runtime_role(" MAIN ") == "manager"
    assert core_module.normalize_notebook_runtime_role("agi.run") == "worker"
    assert core_module.normalize_notebook_runtime_role("not-a-runtime") == ""
    assert [stage.get("runtime_role", "") for stage in stages] == [
        "worker",
        "manager",
        "worker",
        "",
    ]
    assert [stage.get("runtime", "") for stage in stages] == [
        "agi.run",
        "runpy",
        "agi.run",
        "",
    ]
    assert [
        entry.get("NB_RUNTIME_ROLE", "")
        for entry in preview["demo_project"]
    ] == ["worker", "manager", "worker", ""]


def test_notebook_import_defaults_falls_back_to_legacy_metadata_key() -> None:
    core_module = _load_module(CORE_PATH, "notebook_import_legacy_defaults_module")
    notebook = {
        "metadata": {
            "agilab": {
                "import": [],
                "notebook_import": {
                    "schema": " agilab.notebook_import.v1 ",
                    "recommended_template": " flight_telemetry_project ",
                    "project_name_hint": " flight-telemetry-from-notebook-project ",
                }
            }
        }
    }

    assert core_module.extract_notebook_import_defaults(notebook) == {
        "schema": "agilab.notebook_import.v1",
        "recommended_template": "flight_telemetry_project",
        "project_name_hint": "flight-telemetry-from-notebook-project",
    }
    assert core_module.extract_notebook_import_defaults({"metadata": []}) == {}
    assert core_module.extract_notebook_import_defaults({"metadata": {"agilab": []}}) == {}


def test_apply_notebook_runtime_roles_sets_engines_without_mutating_source() -> None:
    core_module = _load_module(CORE_PATH, "notebook_import_runtime_role_apply_module")
    notebook_import = {
        "pipeline_stages": [
            {"id": "load", "runtime_role": "manager", "runtime": "agi.run", "env": ["pandas"]},
            {"id": "score", "runtime": "runpy", "env": ["numpy"]},
            {"id": "notes", "runtime": "runpy"},
        ]
    }

    updated = core_module.apply_notebook_runtime_roles(
        notebook_import,
        {"score": "worker", "notes": "unknown"},
    )

    assert notebook_import["pipeline_stages"][0]["env"] == ["pandas"]
    assert updated["pipeline_stages"][0]["runtime_role"] == "manager"
    assert updated["pipeline_stages"][0]["runtime"] == "runpy"
    assert "env" not in updated["pipeline_stages"][0]
    assert updated["pipeline_stages"][1]["runtime_role"] == "worker"
    assert updated["pipeline_stages"][1]["runtime"] == "agi.run"
    assert updated["pipeline_stages"][1]["env"] == ["numpy"]
    assert updated["pipeline_stages"][2]["runtime"] == "runpy"


def test_packaged_notebook_import_sample_declares_first_proof_defaults() -> None:
    core_module = _load_module(CORE_PATH, "notebook_import_packaged_sample_defaults_module")
    sample_module = _load_module(SAMPLE_HELPER_PATH, "notebook_import_packaged_sample_module")
    sample_path = sample_module.sample_notebook_path()
    notebook = json.loads(sample_module.read_sample_notebook_bytes().decode("utf-8"))

    defaults = core_module.extract_notebook_import_defaults(notebook)
    imported = core_module.build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook=sample_module.SAMPLE_NOTEBOOK_DOWNLOAD_NAME,
    )
    preview = core_module.build_lab_stages_preview(
        imported,
        module_name="flight_telemetry_from_notebook_project",
    )

    assert sample_module.SAMPLE_NOTEBOOK_MIME == "application/x-ipynb+json"
    assert sample_path.name == sample_module.SAMPLE_NOTEBOOK_RESOURCE_NAME
    assert sample_path.is_file()
    assert defaults["recommended_template"] == "flight_telemetry_project"
    assert defaults["project_name_hint"] == "flight-telemetry-from-notebook-project"
    assert [stage["R"] for stage in preview["flight_telemetry_from_notebook_project"]] == [
        "runpy",
        "runpy",
    ]
    assert "pd.read_csv(\"data/flights.csv\")" in preview[
        "flight_telemetry_from_notebook_project"
    ][1]["C"]


def test_notebook_import_preflight_report_writes_contract(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_import_preflight_report_test_module")
    notebook_path = tmp_path / "risky.ipynb"
    output_path = tmp_path / "contract.json"
    pipeline_view_path = tmp_path / "notebook_import_pipeline_view.json"
    view_plan_path = tmp_path / "notebook_import_view_plan.json"
    view_manifest_path = tmp_path / "notebook_import_views.toml"
    notebook_path.write_text(json.dumps(_risky_notebook()), encoding="utf-8")
    view_manifest_path.write_text(
        """
schema = "agilab.notebook_import_views.v1"
app = "demo_project"

[[views]]
id = "orders_dataframe"
module = "view_dataframe"
required_artifacts_any = ["artifacts/*.parquet"]
optional_artifacts = ["data/*.csv"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = module.build_report(
        repo_root=Path.cwd(),
        notebook_path=notebook_path,
        output_path=output_path,
        view_manifest_path=view_manifest_path,
        module_name="demo_project",
    )

    assert report["report"] == "Notebook import preflight report"
    assert report["status"] == "pass"
    assert report["summary"]["risk_status"] == "review"
    assert report["summary"]["safe_to_import"] is True
    assert report["summary"]["contract_path"] == str(output_path)
    assert report["summary"]["pipeline_view_path"] == str(pipeline_view_path)
    assert report["summary"]["view_plan_path"] == str(view_plan_path)
    assert report["summary"]["view_plan_status"] == "matched"
    assert output_path.is_file()
    assert pipeline_view_path.is_file()
    assert view_plan_path.is_file()
    assert {check["id"] for check in report["checks"]} == {
        "notebook_import_preflight_importable",
        "notebook_import_preflight_risks",
        "notebook_import_preflight_artifacts",
        "notebook_import_preflight_lab_stages_preview",
        "notebook_import_preflight_pipeline_view",
        "notebook_import_preflight_view_plan",
        "notebook_import_preflight_contract_write",
        "notebook_import_preflight_pipeline_view_write",
        "notebook_import_preflight_view_plan_write",
    }


def test_notebook_import_preflight_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_import_preflight_report_failure_test_module")
    missing = tmp_path / "missing.ipynb"

    report = module.build_report(repo_root=Path.cwd(), notebook_path=missing)

    assert report["status"] == "fail"
    assert report["summary"]["risk_status"] == "blocked"
    assert report["checks"][0]["id"] == "notebook_import_preflight_load"
