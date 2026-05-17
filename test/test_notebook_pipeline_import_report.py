from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPORT_PATH = Path("tools/notebook_pipeline_import_report.py").resolve()
CORE_PATH = Path("src/agilab/notebook_pipeline_import.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_notebook_pipeline_import_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_pipeline_import_report_test_module")
    output_path = tmp_path / "notebook_import.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=output_path)

    assert report["report"] == "Notebook pipeline import report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["schema"] == "agilab.notebook_pipeline_import.v1"
    assert report["summary"]["run_status"] == "imported"
    assert report["summary"]["execution_mode"] == "not_executed_import"
    assert report["summary"]["round_trip_ok"] is True
    assert report["summary"]["cell_count"] == 4
    assert report["summary"]["code_cell_count"] == 2
    assert report["summary"]["markdown_cell_count"] == 2
    assert report["summary"]["pipeline_stage_count"] == 2
    assert report["summary"]["context_block_count"] == 2
    assert report["summary"]["env_hint_count"] == 3
    assert report["summary"]["artifact_reference_count"] == 3
    assert report["summary"]["lab_stages_preview_stage_count"] == 2
    assert report["summary"]["stage_ids"] == ["cell-2", "cell-4"]
    assert {check["id"] for check in report["checks"]} == {
        "notebook_pipeline_import_schema",
        "notebook_pipeline_import_cells",
        "notebook_pipeline_import_metadata",
        "notebook_pipeline_import_context_links",
        "notebook_pipeline_import_execution_boundary",
        "notebook_pipeline_import_lab_stages_preview",
        "notebook_pipeline_import_persistence",
        "notebook_pipeline_import_docs_reference",
    }


def test_notebook_pipeline_import_reads_fixture_and_round_trips(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_core_test_module")
    fixture = Path.cwd() / "docs/source/data/notebook_pipeline_import_sample.ipynb"
    output_path = tmp_path / "notebook_import.json"

    proof = core_module.persist_notebook_pipeline_import(
        repo_root=Path.cwd(),
        output_path=output_path,
        notebook_path=fixture,
    )

    assert proof.ok is True
    assert proof.round_trip_ok is True
    assert proof.pipeline_stage_count == 2
    assert proof.env_hint_count == 3
    assert proof.artifact_reference_count == 3
    imported = proof.notebook_import
    assert imported["execution_mode"] == "not_executed_import"
    assert imported["provenance"]["executes_notebook"] is False
    assert imported["env_hints"] == ["json", "pandas", "pathlib"]
    assert [stage["context_ids"] for stage in imported["pipeline_stages"]] == [
        ["markdown-1"],
        ["markdown-3"],
    ]
    assert {
        reference["path"]
        for reference in imported["artifact_references"]
    } == {
        "data/flights.csv",
        "artifacts/summary.json",
        "artifacts/trajectory.png",
    }
    preview = core_module.build_lab_stages_preview(
        imported,
        module_name="flight_telemetry_project",
    )
    assert [stage["NB_CELL_ID"] for stage in preview["flight_telemetry_project"]] == [
        "cell-2",
        "cell-4",
    ]
    assert preview["flight_telemetry_project"][0]["D"] == "Flight import context"
    assert preview["flight_telemetry_project"][0]["NB_ENV_HINTS"] == ["pandas", "pathlib"]
    assert preview["flight_telemetry_project"][1]["NB_ARTIFACT_REFERENCES"] == [
        "artifacts/summary.json",
        "artifacts/trajectory.png",
    ]


def test_notebook_pipeline_import_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_pipeline_import_report_failure_test_module")
    missing = tmp_path / "missing.ipynb"

    report = module.build_report(
        repo_root=Path.cwd(),
        notebook_path=missing,
        output_path=tmp_path / "notebook_import.json",
    )

    assert report["status"] == "fail"
    assert report["checks"] == [
        {
            "details": {
                "error": f"[Errno 2] No such file or directory: '{missing}'",
            },
            "evidence": [str(missing)],
            "id": "notebook_pipeline_import_load",
            "label": "Notebook pipeline import load",
            "status": "fail",
            "summary": "notebook-to-pipeline import could not be persisted",
        }
    ]


def test_notebook_pipeline_import_preflight_flags_risky_cells(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_preflight_test_module")
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 7,
                "metadata": {"tags": ["agilab-runtime-worker"]},
                "source": [
                    "!pip install risky-package\n",
                    "import requests\n",
                    "import ipywidgets as widgets\n",
                    "requests.get('https://example.invalid/data.json')\n",
                    "widgets.IntSlider().observe(lambda change: change)\n",
                    "get_ipython(); globals()\n",
                    "df = pd.read_csv('data/input.csv')\n",
                    "df.to_csv('outputs/out.csv')\n",
                    "Path('/Users/agi/private.csv').read_text()\n",
                ],
            }
        ],
    }

    imported = core_module.build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook=tmp_path / "risky.ipynb",
    )
    preflight = core_module.build_notebook_import_preflight(imported)
    contract = core_module.build_notebook_import_contract(
        imported,
        preflight=preflight,
        module_name="risky_project",
    )
    preview = core_module.build_lab_stages_preview(imported, module_name="risky_project")

    assert imported["pipeline_stages"][0]["runtime_role"] == "worker"
    assert imported["pipeline_stages"][0]["runtime"] == "agi.run"
    assert preview["risky_project"][0]["NB_RUNTIME_ROLE"] == "worker"
    assert preview["risky_project"][0]["NB_EXECUTION_COUNT"] == 7
    assert preflight["status"] == "review"
    assert preflight["safe_to_import"] is True
    assert preflight["cleanup_required"] is True
    assert preflight["artifact_contract"]["inputs"] == [
        "/Users/agi/private.csv",
        "data/input.csv",
    ]
    assert preflight["artifact_contract"]["outputs"] == ["outputs/out.csv"]
    assert {
        risk["rule"]
        for risk in preflight["risks"]
    } >= {
        "dependency_install",
        "shell_execution",
        "network_access",
        "interactive_widget",
        "hidden_notebook_state",
        "absolute_path",
        "absolute_artifact_path",
        "missing_markdown_context",
        "execution_history_present",
    }
    assert contract["module_name"] == "risky_project"
    assert contract["warnings"]
    assert contract["errors"] == []


def test_notebook_pipeline_import_uses_supervisor_export_metadata(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_supervisor_export_test_module")
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"name": "python3"},
            "agilab": {
                "export_mode": "notebook_export",
                "project_name": "demo_project",
                "stages_file": "lab_stages.toml",
                "import": {
                    "schema": "agilab.notebook_import.defaults.v1",
                    "recommended_template": "flight_telemetry_project",
                    "project_name_hint": "flight_telemetry_from_notebook_project",
                },
                "stages": [
                    {
                        "description": "Prepare data",
                        "question": "Load data",
                        "model": "gpt-5-mini",
                        "runtime": "agi.run",
                        "env": "worker",
                        "code": "print('fallback')",
                    },
                    {
                        "description": "Skipped empty stage",
                        "code": "",
                    },
                ],
            },
        },
        "cells": [
            {
                "cell_type": "code",
                "metadata": {
                    "agilab": {
                        "runtime_role": "manager",
                        "stage_cell": {
                            "schema": "agilab.notebook_export.stage_cell.v1",
                            "kind": "source",
                            "stage_index": 0,
                            "runtime": "runpy",
                        },
                    }
                },
                "source": "STAGE_000_CODE = \"from pathlib import Path\\nPath('outputs/report.json').write_text('{}')\\n\"",
            },
            {
                "cell_type": "code",
                "metadata": {
                    "agilab": {
                        "stage_cell": {
                            "schema": "ignored.schema",
                            "kind": "source",
                            "stage_index": 0,
                        }
                    }
                },
                "source": "print('ignored duplicate')",
            },
        ],
    }

    imported = core_module.build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook=tmp_path / "supervisor.ipynb",
    )
    preview = core_module.build_lab_stages_preview(imported, module_name="demo_project")

    assert imported["source"]["import_mode"] == "agilab_supervisor_metadata"
    assert imported["source"]["import_defaults"]["recommended_template"] == "flight_telemetry_project"
    assert imported["summary"]["supervisor_stage_count"] == 2
    assert imported["summary"]["pipeline_stage_count"] == 1
    assert imported["pipeline_stages"][0]["source_cell_index"] == 1
    assert imported["pipeline_stages"][0]["runtime_role"] == "manager"
    assert "outputs/report.json" in imported["pipeline_stages"][0]["source_lines"][1]
    assert preview["demo_project"][0]["D"] == "Prepare data"
    assert preview["demo_project"][0]["Q"] == "Load data"
    assert preview["demo_project"][0]["R"] == "runpy"
    assert preview["demo_project"][0]["E"] == "worker"


def test_notebook_import_view_plan_matches_manifest_and_warnings(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_view_plan_test_module")
    notebook_import = {
        "source": {"source_notebook": "demo.ipynb"},
        "summary": {"pipeline_stage_count": 1},
        "pipeline_stages": [
            {
                "id": "cell-1",
                "order": 1,
                "source_cell_index": 1,
                "source_lines": ["df = pd.read_csv('data/input.csv')\n", "df.to_csv('outputs/out.csv')\n"],
                "context_ids": ["ctx"],
                "env_hints": ["pandas"],
                "artifact_references": [
                    {"path": "data/input.csv", "suffix": ".csv", "source_cell_index": 1},
                    {"path": "outputs/out.csv", "suffix": ".csv", "source_cell_index": 1},
                ],
            }
        ],
        "context_blocks": [
            {"id": "ctx", "text": "# Load and export data", "source_cell_index": 1}
        ],
        "env_hints": ["pandas"],
        "artifact_references": [
            {"path": "data/input.csv", "suffix": ".csv", "source_cell_index": 1},
            {"path": "outputs/out.csv", "suffix": ".csv", "source_cell_index": 1},
        ],
    }
    preflight = core_module.build_notebook_import_preflight(notebook_import)
    manifest = {
        "notebook_import_views": {
            "app": "demo_project",
            "description": "Demo views",
            "views": [
                {
                    "id": "analysis",
                    "module": "view_analysis",
                    "label": "Analysis",
                    "required_artifacts": ["outputs/*.csv"],
                    "optional_artifacts": ["data/*.csv"],
                    "settings_hints": {"tab": "summary"},
                    "query_params": {"view": "analysis"},
                },
                {
                    "id": "missing",
                    "module": "view_missing",
                    "required_artifacts_any": ["figures/*.png"],
                    "artifacts": ["fallback/*.json"],
                    "priority": "bad",
                },
            ],
        }
    }

    unmatched = core_module.build_notebook_import_view_plan(
        notebook_import,
        preflight=preflight,
        manifest=None,
    )
    empty = core_module.build_notebook_import_view_plan(
        notebook_import,
        preflight=preflight,
        manifest={"views": []},
    )
    matched = core_module.build_notebook_import_view_plan(
        notebook_import,
        preflight=preflight,
        module_name="demo_project",
        manifest=manifest,
        manifest_path="notebook_import_views.toml",
    )
    pipeline_view = core_module.build_notebook_import_pipeline_view(
        notebook_import,
        preflight=preflight,
        module_name="demo_project",
    )

    assert unmatched["status"] == "unmatched"
    assert "no UI view was inferred" in unmatched["warnings"][0]
    assert empty["status"] == "unmatched"
    assert empty["warnings"] == ["Notebook import view manifest declares no views."]
    assert matched["status"] == "matched"
    assert matched["manifest"]["app"] == "demo_project"
    assert matched["summary"]["ready_view_count"] == 1
    assert matched["summary"]["incomplete_view_count"] == 1
    assert matched["matched_views"][0]["settings_hints"] == {"tab": "summary"}
    assert matched["matched_views"][0]["query_params"] == {"view": "analysis"}
    assert matched["views"][1]["missing_required_any"] == ["figures/*.png"]
    assert pipeline_view["summary"]["artifact_node_count"] == 2
    assert any(edge["kind"] == "analysis_consumes" for edge in pipeline_view["edges"])

    export_manifest = tmp_path / "notebook_export.toml"
    export_manifest.write_text(
        """
schema = "agilab.notebook_export.v1"
app = "demo_project"

[notebook_export]
related_pages = [
  {module = "view_analysis", label = "Analysis", artifacts = ["outputs/*.csv"], launch_note = "open analysis"}
]
""".strip(),
        encoding="utf-8",
    )
    loaded = core_module.load_notebook_import_view_manifest(export_manifest)
    assert loaded["source_schema"] == "agilab.notebook_export.v1"
    assert loaded["views"][0]["required_artifacts_any"] == ["outputs/*.csv"]

    nested = tmp_path / "module" / "src"
    nested.mkdir(parents=True)
    nested_manifest = nested / "notebook_import_views.toml"
    nested_manifest.write_text("views = []\n", encoding="utf-8")
    assert core_module.discover_notebook_import_view_manifest(tmp_path / "module") == nested_manifest
    assert core_module.discover_notebook_import_view_manifest(None) is None

    missing_plan = tmp_path / "missing-plan.json"
    core_module.write_notebook_import_view_plan(
        missing_plan,
        notebook_import,
        preflight=preflight,
        manifest_path=tmp_path / "missing.toml",
    )
    assert "not found" in missing_plan.read_text(encoding="utf-8")


def test_notebook_pipeline_import_helper_edges(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_helper_edges_test_module")

    assert core_module._coerce_source_lines(None) == []
    assert core_module._coerce_source_lines("a\nb") == ["a\n", "b"]
    assert core_module._coerce_source_lines(("a\n", 2)) == ["a\n", "2"]
    assert core_module._coerce_source_lines(42) == ["42"]
    assert core_module.extract_env_hints("from package.submodule import thing") == ["package"]
    assert core_module._is_absolute_path_text(r"C:\data\input.csv") is True
    assert core_module._combine_artifact_roles("input", "output") == "input_output"

    invalid_json = tmp_path / "invalid.ipynb"
    invalid_json.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        core_module.load_notebook(invalid_json)
    invalid_cells = tmp_path / "invalid-cells.ipynb"
    invalid_cells.write_text('{"cells": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="cells must be a list"):
        core_module.load_notebook(invalid_cells)

    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": "not-a-mapping",
        "cells": [
            {
                "cell_type": "code",
                "metadata": "not-a-mapping",
                "source": ["print('manager')\n"],
            },
            {
                "cell_type": "raw",
                "source": ["ignored\n"],
            },
        ],
    }
    imported = core_module.build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook=Path("relative.ipynb"),
    )
    assert imported["source"]["kernel_name"] == ""
    assert imported["summary"]["pipeline_stage_count"] == 1

    updated = core_module.apply_notebook_runtime_roles(
        imported,
        {"cell-1": "manager", "missing": "worker"},
    )
    assert updated["pipeline_stages"][0]["runtime_role"] == "manager"
    assert updated["pipeline_stages"][0]["runtime"] == "runpy"
    assert "env" not in updated["pipeline_stages"][0]
    assert core_module.apply_notebook_runtime_roles({"pipeline_stages": "bad"}, {})[
        "pipeline_stages"
    ] == "bad"

    empty_preview = core_module.build_lab_stages_preview(
        {"pipeline_stages": "bad"},
        module_name="edge_project",
    )
    assert empty_preview == {"edge_project": []}
    blocked = core_module.build_notebook_import_preflight({"summary": {}})
    assert blocked["status"] == "blocked"
    assert blocked["safe_to_import"] is False
    assert blocked["risk_counts"]["error"] == 1

    no_artifacts = core_module.build_notebook_import_view_plan(
        imported,
        preflight=core_module.build_notebook_import_preflight(imported),
        manifest={"views": [{"id": "empty", "module": "view_empty"}]},
    )
    assert "does not declare artifacts" in no_artifacts["warnings"][0]

    contract_path = tmp_path / "contract.json"
    view_path = tmp_path / "pipeline-view.json"
    core_module.write_notebook_import_contract(contract_path, imported)
    core_module.write_notebook_import_pipeline_view(view_path, imported)
    assert contract_path.is_file()
    assert view_path.is_file()

    relative_notebook = tmp_path / "relative.ipynb"
    relative_notebook.write_text(
        '{"nbformat": 4, "nbformat_minor": 5, "cells": [{"cell_type": "code", "source": "print(1)"}]}',
        encoding="utf-8",
    )
    proof = core_module.persist_notebook_pipeline_import(
        repo_root=tmp_path,
        notebook_path=Path("relative.ipynb"),
        output_path=tmp_path / "imported.json",
    )
    assert proof.ok is True
