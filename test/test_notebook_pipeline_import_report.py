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


def test_notebook_pipeline_import_edge_serialization_and_malformed_inputs(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_more_edges_test_module")

    issue = core_module._issue("schema", "bad schema")
    proof = core_module.NotebookPipelineImportProof(
        ok=False,
        issues=(issue,),
        path="import.json",
        notebook_path="source.ipynb",
        notebook_import={
            "summary": {
                "pipeline_stage_count": "2",
                "env_hint_count": None,
                "artifact_reference_count": 3,
            }
        },
        reloaded_import={},
    )
    proof_state = proof.as_dict()
    assert proof_state["issues"] == [
        {"level": "error", "location": "schema", "message": "bad schema"}
    ]
    assert proof_state["round_trip_ok"] is False
    assert proof_state["pipeline_stage_count"] == 2
    assert proof_state["env_hint_count"] == 0
    assert proof_state["artifact_reference_count"] == 3

    assert core_module.extract_notebook_import_defaults(
        {"metadata": {"agilab": {"import": [], "notebook_import": []}}}
    ) == {}
    assert core_module.apply_notebook_runtime_roles(
        {"pipeline_stages": ["bad", {"id": "run", "runtime_role": "local", "env": "worker"}]},
        {},
    )["pipeline_stages"][1] == {
        "id": "run",
        "runtime_role": "manager",
        "runtime": "runpy",
    }
    assert core_module._pipeline_stage_sources({"pipeline_stages": "bad"}) == []
    assert core_module._pipeline_stage_sources({"pipeline_stages": ["bad"]}) == []
    assert core_module._safe_node_id("x", "").startswith("x_node_")
    assert core_module._notebook_cells({"cells": [{"a": 1}, "bad"]}) == [{"a": 1}]
    with pytest.raises(ValueError, match="cells must be a list"):
        core_module._notebook_cells({"cells": "bad"})
    assert core_module._kernel_name({"metadata": {"kernelspec": "bad"}}) == ""
    assert core_module._agilab_supervisor_stages({"metadata": {"agilab": {"stages": "bad"}}}) == []
    assert core_module._cell_agilab_metadata({"metadata": []}) == {}
    assert core_module._export_stage_cell_metadata({"metadata": {"agilab": {"stage_cell": []}}}) == {}
    assert core_module._coerce_nonnegative_int("bad") is None
    assert core_module._coerce_nonnegative_int(-1) is None
    assert core_module._extract_exported_stage_source("STAGE_000_CODE = [", 0) == "STAGE_000_CODE = ["
    assert core_module._extract_exported_stage_source("STAGE_000_CODE = 42", 0) == "STAGE_000_CODE = 42"

    malformed = {
        "cells": [
            {
                "cell_type": "code",
                "metadata": {"agilab": {"stage_cell": {"kind": "source", "stage_index": "bad"}}},
                "source": ["print('ignored bad index')\n"],
            },
            {
                "cell_type": "code",
                "metadata": {
                    "agilab": {
                        "stage_cell": {
                            "schema": "agilab.notebook_export.stage_cell.v1",
                            "kind": "source",
                            "stage_index": 0,
                            "runtime_role": "driver",
                        }
                    }
                },
                "source": ["STAGE_000_CODE = \"print('first')\\n\"\n"],
            },
            {
                "cell_type": "code",
                "metadata": {
                    "agilab": {
                        "stage_cell": {
                            "schema": "agilab.notebook_export.stage_cell.v1",
                            "kind": "source",
                            "stage_index": 0,
                        }
                    }
                },
                "source": ["STAGE_000_CODE = \"print('duplicate')\\n\"\n"],
            },
        ],
        "metadata": {
            "agilab": {
                "stages": [
                    {
                        "description": "Stage",
                        "question": "Run",
                        "runtime": "",
                        "code": "print('fallback')\n",
                    }
                ]
            }
        },
    }
    imported = core_module.build_notebook_pipeline_import(
        notebook=malformed,
        source_notebook="malformed.ipynb",
    )
    assert imported["pipeline_stages"][0]["source_lines"] == ["print('first')\n"]
    assert imported["pipeline_stages"][0]["runtime_role"] == "manager"

    contexts = core_module._context_lookup({"context_blocks": ["bad", {"id": "", "text": "x"}]})
    assert contexts == {}
    assert core_module._context_lookup({"context_blocks": "bad"}) == {}
    assert core_module._context_summary(["ctx"], {"ctx": "\n# Useful title\nbody"}) == "Useful title"
    assert core_module._context_summary(["missing"], {}) == ""
    assert core_module._artifact_paths({"artifact_references": "bad"}) == []
    assert core_module._artifact_paths({"artifact_references": ["bad", {"path": ""}, {"path": "out.csv"}]}) == [
        "out.csv"
    ]
    assert core_module._stage_env_hints({"env_hints": "bad"}) == []

    preview = core_module.build_lab_stages_preview(
        {
            "source": "bad",
            "execution_mode": "manual",
            "context_blocks": [{"id": "ctx", "text": "# Context title"}],
            "pipeline_stages": [
                "bad",
                {"id": "empty", "source_lines": ["\n"]},
                {
                    "id": "",
                    "source_cell_index": 3,
                    "source_lines": ["print(3)\n"],
                    "context_ids": ["ctx", ""],
                    "artifact_references": "bad",
                    "env_hints": "bad",
                },
            ],
        },
        module_name="",
    )
    assert preview["lab_stages"][0]["Q"] == "Imported notebook cell"
    assert preview["lab_stages"][0]["D"] == "Context title"
    assert preview["lab_stages"][0]["NB_EXECUTION_MODE"] == "manual"
    assert preview["lab_stages"][0]["NB_SOURCE_NOTEBOOK"] == ""

    contract = core_module.build_notebook_artifact_contract(
        {
            "pipeline_stages": [
                {
                    "id": "stage",
                    "source_cell_index": 1,
                    "source_lines": [
                        "df = pd.read_csv('shared/data.csv')\n",
                        "df.to_csv('shared/data.csv')\n",
                        "Path('notes.txt').read_text()\n",
                    ],
                }
            ],
            "artifact_references": [
                "bad",
                {"path": "", "source_cell_index": 1},
                {"path": "shared/data.csv", "source_cell_index": 1},
                {"path": "notes.txt", "source_cell_index": 1},
                {"path": "notes.txt", "source_cell_index": 1},
            ],
        }
    )
    assert contract["inputs"] == ["notes.txt", "shared/data.csv"]
    assert contract["outputs"] == ["shared/data.csv"]
    notes = next(item for item in contract["references"] if item["path"] == "notes.txt")
    assert notes["source_cell_indices"] == [1]

    view = core_module.build_notebook_import_pipeline_view(
        {
            "source": "bad",
            "context_blocks": "bad",
            "pipeline_stages": [
                "bad",
                {"id": "", "source_lines": ["print('ignored')\n"]},
                {
                    "id": "cell-x",
                    "source_cell_index": 2,
                    "source_lines": ["Path('late.txt').write_text('x')\n"],
                    "artifact_references": [{"path": "late.txt"}],
                },
            ],
        },
        preflight={"artifact_contract": {"references": ["bad", {"path": ""}]}},
        module_name="",
    )
    assert view["module_name"] == "notebook_import_project"
    assert any(node["path"] == "late.txt" for node in view["nodes"] if node["kind"] == "artifact")
    assert any(edge["kind"] == "artifact_output" for edge in view["edges"])

    no_edge_view = core_module.build_notebook_import_pipeline_view(
        {
            "pipeline_stages": [
                {
                    "id": "cell-y",
                    "source_cell_index": 1,
                    "source_lines": ["print('no artifacts')\n"],
                }
            ],
        },
        preflight={"artifact_contract": {"references": []}},
    )
    assert any(edge["kind"] == "analysis_candidate" for edge in no_edge_view["edges"])

    raw_manifest = {
        "notebook_import_views": "bad",
        "views": [
            "bad",
            {
                "page": "view_page",
                "required": "outputs/*.csv",
                "optional": {"ignored": "mapping"},
                "settings_hints": {None: "ignored", "mode": "summary"},
                "query_params": "bad",
            },
        ],
    }
    normalized = core_module._normalize_import_view_manifest(raw_manifest)
    assert normalized["views"][0]["id"] == "view_page"
    assert normalized["views"][0]["required_artifacts"] == ["outputs/*.csv"]
    assert normalized["views"][0]["optional_artifacts"] == []
    assert normalized["views"][0]["settings_hints"] == {"mode": "summary"}

    bad_path = tmp_path / "bad-view.toml"
    bad_path.write_text("not toml = [", encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    core_module.write_notebook_import_view_plan(
        plan_path,
        {"summary": {}, "pipeline_stages": []},
        manifest_path=bad_path,
    )
    assert "Unable to load notebook import view manifest" in plan_path.read_text(encoding="utf-8")


def test_notebook_pipeline_import_more_branch_edges(tmp_path: Path, monkeypatch) -> None:
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_branch_edges_test_module")

    assert core_module._cell_runtime_role_from_metadata(
        {"metadata": {"agilab": {"execution_location": "driver"}}}
    ) == "manager"
    assert core_module._cell_runtime_role_from_metadata({"metadata": {"runtime_role": "app"}}) == "worker"
    assert core_module.extract_notebook_import_defaults({"metadata": {"agilab": {}}}) == {}
    assert core_module.extract_env_hints("def broken(:\nfrom package.sub import thing\n") == ["package"]
    assert core_module._line_role_for_path(
        "df = pd.read_csv('shared.csv'); df.to_csv('shared.csv')",
        "shared.csv",
    ) == "input_output"
    assert core_module._combine_artifact_roles("input", "warning") == "input"
    assert core_module._extract_exported_stage_source("other = 'x'\nSTAGE_000_CODE = 'ok'\n", 0) == "ok"
    assert core_module._extract_exported_stage_source("STAGE_000_CODE = object()\n", 0).startswith(
        "STAGE_000_CODE"
    )

    class BrokenPath:
        def __init__(self, _value):
            pass

        def is_absolute(self):
            raise OSError("bad path")

    monkeypatch.setattr(core_module, "Path", BrokenPath)
    assert core_module._is_absolute_path_text("/absolute/data.csv") is True
    monkeypatch.setattr(core_module, "Path", Path)

    supervisor_notebook = {
        "nbformat": 4,
        "metadata": {
            "agilab": {
                "stages": [
                    {
                        "description": "Stage",
                        "question": "Run",
                        "runtime": "worker",
                        "code": "print('fallback')\n",
                    }
                ]
            }
        },
        "cells": [
            {
                "cell_type": "code",
                "metadata": {
                    "agilab": {
                        "stage_cell": {
                            "schema": core_module.NOTEBOOK_EXPORT_STAGE_CELL_SCHEMA,
                            "kind": "source",
                            "stage_index": 0,
                            "runtime_role": "unknown",
                            "env": "custom-env",
                        }
                    }
                },
                "source": ["STAGE_000_CODE = \"print('override')\\n\"\n"],
            }
        ],
    }
    imported = core_module.build_notebook_pipeline_import(
        notebook=supervisor_notebook,
        source_notebook="supervisor.ipynb",
    )
    assert imported["pipeline_stages"][0]["runtime_role"] == "worker"
    assert imported["pipeline_stages"][0]["runtime"] == "worker"
    assert imported["pipeline_stages"][0]["env"] == "custom-env"

    preflight = core_module.build_notebook_import_preflight(
        {
            "summary": {"pipeline_stage_count": 1, "markdown_cell_count": 1},
            "pipeline_stages": [],
            "artifact_references": ["bad", {"path": "/tmp/out.csv", "source_cell_index": 1}],
        }
    )
    assert any(risk["rule"] == "absolute_artifact_path" for risk in preflight["risks"])

    contract = core_module.build_notebook_import_contract(
        {
            "source": "bad",
            "summary": "bad",
            "env_hints": ["pandas"],
            "pipeline_stages": ["bad"],
        },
        preflight={"risks": "bad", "artifact_contract": {}},
    )
    assert contract["source"] == {}
    assert contract["summary"] == {}
    assert contract["stages"] == []

    view = core_module.build_notebook_import_pipeline_view(
        {
            "context_blocks": [
                "bad",
                {"id": ""},
                {"id": "ctx", "text": "# Title"},
                {"id": "ctx", "text": "# Duplicate"},
            ],
            "pipeline_stages": [
                {
                    "id": "cell",
                    "source_cell_index": 1,
                    "source_lines": ["print('x')\n"],
                    "context_ids": ["ctx", "ctx"],
                    "artifact_references": [{"path": "artifact.csv"}, {"path": "artifact.csv"}],
                }
            ],
        },
        preflight={
            "artifact_contract": {
                "references": [
                    {"path": "artifact.csv", "role": "unknown", "source_cell_indices": [1]},
                ],
                "outputs": ["artifact.csv"],
                "unknown": ["artifact.csv"],
            }
        },
    )
    assert len({(edge["from"], edge["to"], edge["kind"], edge.get("artifact", "")) for edge in view["edges"]}) == len(
        view["edges"]
    )

    assert core_module._string_list(42) == ["42"]
    assert core_module._string_list(["a", "a", "", "b"]) == ["a", "b"]
    assert core_module._safe_mapping({None: "bad", "ok": 1}) == {"ok": 1}
    normalized_export = core_module._normalize_import_view_manifest(
        {
            "app": "demo",
            "notebook_export": {
                "related_pages": [
                    "bad",
                    {"module": "view_demo", "label": "View", "artifacts": ["out.csv"]},
                ]
            },
        }
    )
    assert normalized_export["source_schema"] == "agilab.notebook_export.v1"
    assert normalized_export["views"][0]["module"] == "view_demo"

    class BadModuleDir:
        def __fspath__(self):
            raise TypeError("bad path")

    assert core_module.discover_notebook_import_view_manifest(BadModuleDir()) is None
    assert core_module._artifact_entries_for_view_plan(
        {
            "references": ["bad", {"path": ""}, {"path": "out.csv", "role": "output"}],
            "inputs": ["in.csv", "in.csv"],
            "unknown": "maybe.txt",
        }
    ) == (["in.csv", "maybe.txt", "out.csv"], {"out.csv": "output", "in.csv": "input", "maybe.txt": "unknown"})


def test_notebook_pipeline_import_persist_reports_invalid_generated_import(
    tmp_path: Path,
    monkeypatch,
) -> None:
    core_module = _load_module(CORE_PATH, "notebook_pipeline_import_persist_edges_test_module")
    source = tmp_path / "source.ipynb"
    source.write_text('{"nbformat": 4, "cells": []}', encoding="utf-8")

    monkeypatch.setattr(core_module, "load_notebook", lambda _path: {"cells": []})
    monkeypatch.setattr(
        core_module,
        "build_notebook_pipeline_import",
        lambda **_kwargs: {
            "schema": "wrong",
            "execution_mode": "executed",
            "pipeline_stages": [],
        },
    )
    monkeypatch.setattr(core_module, "write_notebook_pipeline_import", lambda output_path, _payload: output_path)
    monkeypatch.setattr(core_module, "load_notebook_pipeline_import", lambda _path: {"schema": "different"})

    proof = core_module.persist_notebook_pipeline_import(
        repo_root=tmp_path,
        notebook_path=source,
        output_path=tmp_path / "import.json",
    )

    assert proof.ok is False
    assert {issue.location for issue in proof.issues} == {
        "persistence.round_trip",
        "schema",
        "execution_mode",
        "pipeline_stages",
    }
