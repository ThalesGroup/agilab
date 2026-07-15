from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

from agilab.notebooks.notebook_export_support import (
    NOTEBOOK_EXPORT_STAGE_CELL_SCHEMA,
    NotebookExportContext,
    build_notebook_document,
)
from agilab.notebooks.notebook_pipeline_import import (
    build_lab_stages_preview,
    build_notebook_import_preflight,
    build_notebook_pipeline_import,
)


MODULE_NAME = "notebook_roundtrip_project"


def _stage_cell_metadata(cell: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = cell.get("metadata", {})
    agilab_metadata = metadata.get("agilab", {}) if isinstance(metadata, Mapping) else {}
    stage_cell = (
        agilab_metadata.get("stage_cell", {})
        if isinstance(agilab_metadata, Mapping)
        else {}
    )
    return stage_cell if isinstance(stage_cell, Mapping) else {}


def _stage_cells(notebook: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    cells = notebook.get("cells", [])
    return [
        cell
        for cell in cells
        if isinstance(cell, dict)
        and _stage_cell_metadata(cell).get("kind") == kind
    ]


def _replace_exported_stage_source(
    notebook: Mapping[str, Any],
    *,
    stage_id: str,
    source: str,
) -> None:
    source_cell = next(
        cell
        for cell in _stage_cells(notebook, "source")
        if _stage_cell_metadata(cell).get("stage_id") == stage_id
    )
    stage_index = int(_stage_cell_metadata(source_cell)["stage_index"])
    variable_name = f"STAGE_{stage_index:03d}_CODE"
    source_cell["source"] = (
        f"{variable_name} = {source!r}\nprint({variable_name})\n"
    ).splitlines(keepends=True)


def test_supervisor_notebook_reimport_preserves_stage_contract_and_original_provenance(
    tmp_path: Path,
) -> None:
    original_source = (
        "import pandas as pd\n"
        "orders = pd.read_csv('legacy/orders.csv')\n"
        "orders.to_json('legacy/summary.json')\n"
    )
    edited_source = (
        "import json\n"
        "from pathlib import Path\n"
        "payload = json.loads(Path('fresh/orders.json').read_text(encoding='utf-8'))\n"
        "Path('fresh/summary.json').write_text(json.dumps(payload), encoding='utf-8')\n"
    )
    stages_file = tmp_path / "lab_stages.toml"
    stage_contract = {
        "__meta__": {"schema": "agilab.lab_stages.v1", "version": 1},
        MODULE_NAME: [
            {
                "id": "prepare",
                "label": "Prepare source data",
                "kind": "data",
                "produces": ["declared/orders.parquet"],
                "D": "Prepare source data",
                "Q": "Prepare orders for the evidence stage.",
                "M": "",
                "C": "print('prepare')\n",
                "R": "runpy",
            },
            {
                "id": "summarize",
                "label": "Summarize order evidence",
                "kind": "evidence",
                "deps": ["prepare"],
                "produces": ["declared/summary.json"],
                "D": "Summarize order evidence",
                "Q": "Build the review summary.",
                "M": "review-model",
                "C": original_source,
                "R": "agi.run",
                "NB_CELL_ID": "cell-8",
                "NB_CELL_INDEX": 8,
                "NB_CONTEXT_IDS": ["markdown-7"],
                "NB_ENV_HINTS": ["pandas"],
                "NB_ARTIFACT_REFERENCES": [
                    "legacy/orders.csv",
                    "legacy/summary.json",
                ],
                "NB_EXECUTION_MODE": "not_executed_import",
                "NB_EXECUTION_COUNT": 4,
                "NB_SOURCE_NOTEBOOK": "notebooks/source/original.ipynb",
                "NB_RUNTIME_ROLE": "worker",
            },
        ],
    }
    notebook = build_notebook_document(
        stage_contract,
        stages_file,
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )

    exported_stages = notebook["metadata"]["agilab"]["stages"]
    exported_summary = next(
        stage for stage in exported_stages if stage.get("stage_id") == "summarize"
    )
    assert exported_summary["stage_id_explicit"] is True
    assert exported_summary["depends_on"] == ["prepare"]
    assert exported_summary["label"] == "Summarize order evidence"
    assert exported_summary["kind"] == "evidence"
    assert exported_summary["produces"] == ["declared/summary.json"]
    assert exported_summary["notebook_import"] == {
        "cell_id": "cell-8",
        "source_cell_index": 8,
        "context_ids": ["markdown-7"],
        "env_hints": ["pandas"],
        "artifact_references": ["legacy/orders.csv", "legacy/summary.json"],
        "execution_mode": "not_executed_import",
        "source_notebook": "notebooks/source/original.ipynb",
        "runtime_role": "worker",
        "execution_count": 4,
    }

    summary_source_cell = next(
        cell
        for cell in _stage_cells(notebook, "source")
        if _stage_cell_metadata(cell).get("stage_id") == "summarize"
    )
    summary_cell_metadata = _stage_cell_metadata(summary_source_cell)
    assert summary_cell_metadata["schema"] == NOTEBOOK_EXPORT_STAGE_CELL_SCHEMA
    assert summary_cell_metadata["stage_id_explicit"] is True
    _replace_exported_stage_source(
        notebook,
        stage_id="summarize",
        source=edited_source,
    )

    notebook_import = build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook="exported/lab_stages.ipynb",
    )
    reimported = build_lab_stages_preview(
        notebook_import,
        module_name=MODULE_NAME,
    )[MODULE_NAME]
    summary = next(stage for stage in reimported if stage.get("id") == "summarize")

    assert summary["depends_on"] == ["prepare"]
    assert summary["label"] == "Summarize order evidence"
    assert summary["kind"] == "evidence"
    assert summary["produces"] == ["declared/summary.json"]
    assert summary["C"] == edited_source
    assert summary["R"] == "agi.run"
    assert summary["NB_CELL_ID"] == "cell-8"
    assert summary["NB_CELL_INDEX"] == 8
    assert summary["NB_CONTEXT_IDS"] == ["markdown-7"]
    assert summary["NB_EXECUTION_MODE"] == "not_executed_import"
    assert summary["NB_EXECUTION_COUNT"] == 4
    assert summary["NB_SOURCE_NOTEBOOK"] == "notebooks/source/original.ipynb"
    assert summary["NB_RUNTIME_ROLE"] == "worker"
    assert summary["NB_ENV_HINTS"] == ["json", "pathlib"]
    assert set(summary["NB_ARTIFACT_REFERENCES"]) == {
        "fresh/orders.json",
        "fresh/summary.json",
    }
    assert "legacy/orders.csv" not in summary["NB_ARTIFACT_REFERENCES"]
    assert "legacy/summary.json" not in summary["NB_ARTIFACT_REFERENCES"]

    preflight = build_notebook_import_preflight(notebook_import)
    assert preflight["artifact_contract"]["inputs"] == ["fresh/orders.json"]
    assert preflight["artifact_contract"]["outputs"] == ["fresh/summary.json"]


def test_supervisor_notebook_export_uses_effective_saved_stage_sequence(
    tmp_path: Path,
) -> None:
    stages_file = tmp_path / "lab_stages.toml"
    stage_contract = {
        "__meta__": {
            "schema": "agilab.lab_stages.v1",
            "version": 1,
            f"{MODULE_NAME}__sequence": [1, 2, 0],
        },
        MODULE_NAME: [
            {"id": "extract", "C": "print('extract')\n", "R": "runpy"},
            {"id": "train", "C": "print('train')\n", "R": "runpy"},
            {"id": "publish", "C": "print('publish')\n", "R": "runpy"},
        ],
    }

    notebook = build_notebook_document(
        stage_contract,
        stages_file,
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )

    exported_stages = notebook["metadata"]["agilab"]["stages"]
    assert [stage["stage_id"] for stage in exported_stages] == [
        "train",
        "publish",
        "extract",
    ]
    assert [stage["module_index"] for stage in exported_stages] == [1, 2, 0]
    assert [
        _stage_cell_metadata(cell)["stage_id"]
        for cell in _stage_cells(notebook, "source")
    ] == ["train", "publish", "extract"]


def test_supervisor_notebook_export_orders_dependencies_before_consumers(
    tmp_path: Path,
) -> None:
    stages_file = tmp_path / "lab_stages.toml"
    stage_contract = {
        "__meta__": {
            "schema": "agilab.lab_stages.v1",
            "version": 1,
            f"{MODULE_NAME}__sequence": [1, 0],
        },
        MODULE_NAME: [
            {"id": "prepare", "C": "print('prepare')\n", "R": "runpy"},
            {
                "id": "summarize",
                "deps": ["prepare"],
                "C": "print('summarize')\n",
                "R": "runpy",
            },
        ],
    }

    notebook = build_notebook_document(
        stage_contract,
        stages_file,
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )

    exported_stages = notebook["metadata"]["agilab"]["stages"]
    assert [stage["stage_id"] for stage in exported_stages] == ["prepare", "summarize"]
    assert exported_stages[1]["depends_on"] == ["prepare"]


def test_supervisor_notebook_export_orders_selected_profile_dependencies(
    tmp_path: Path,
) -> None:
    notebook = build_notebook_document(
        {
            "__meta__": {
                f"{MODULE_NAME}__sequence": [0, 1],
                f"{MODULE_NAME}__automation": {"profile": "fast"},
            },
            MODULE_NAME: [
                {
                    "id": "consumer",
                    "C": "print('consumer')\n",
                    "profiles": {"fast": {"deps": ["producer"]}},
                },
                {"id": "producer", "C": "print('producer')\n"},
            ],
        },
        tmp_path / "lab_stages.toml",
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )

    exported = notebook["metadata"]["agilab"]["stages"]
    assert [stage["stage_id"] for stage in exported] == ["producer", "consumer"]
    assert exported[1]["depends_on"] == []
    assert exported[1]["effective_depends_on"] == ["producer"]


def test_supervisor_notebook_export_rejects_selected_profile_cycle(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="cycle or self-dependency"):
        build_notebook_document(
            {
                "__meta__": {
                    f"{MODULE_NAME}__automation": {"profile": "fast"}
                },
                MODULE_NAME: [
                    {
                        "id": "left",
                        "C": "print('left')\n",
                        "profiles": {"fast": {"deps": ["right"]}},
                    },
                    {
                        "id": "right",
                        "C": "print('right')\n",
                        "profiles": {"fast": {"deps": ["left"]}},
                    },
                ],
            },
            tmp_path / "lab_stages.toml",
            export_context=NotebookExportContext(
                project_name=MODULE_NAME,
                module_path=MODULE_NAME,
                artifact_dir=str(tmp_path / "artifacts"),
            ),
        )


def test_supervisor_notebook_export_only_includes_active_module(tmp_path: Path) -> None:
    stages_file = tmp_path / "lab_stages.toml"
    notebook = build_notebook_document(
        {
            "__meta__": {
                f"{MODULE_NAME}__automation": {"profile": "fast"},
                "other_project__automation": {"profile": "smoke"},
            },
            MODULE_NAME: [{"id": "active", "C": "print('active')\n"}],
            "other_project": [{"id": "other", "C": "print('other')\n"}],
        },
        stages_file,
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )

    exported = notebook["metadata"]["agilab"]
    assert exported["module_key"] == MODULE_NAME
    assert exported["module_automation"] == {"profile": "fast"}
    assert [stage["stage_id"] for stage in exported["stages"]] == ["active"]
    assert {stage["module"] for stage in exported["stages"]} == {MODULE_NAME}
    notebook_import = build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook="exported/lab_stages.ipynb",
    )
    assert {stage["source_module"] for stage in notebook_import["pipeline_stages"]} == {
        MODULE_NAME
    }
    preview = build_lab_stages_preview(notebook_import, module_name=MODULE_NAME)
    assert preview["__meta__"] == {
        f"{MODULE_NAME}__automation": {"profile": "fast"}
    }


def test_supervisor_notebook_export_rejects_ambiguous_module_alias(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Unable to identify the active workflow module"):
        build_notebook_document(
            {
                "demo": [{"id": "demo", "C": "print('demo')\n"}],
                "other": [{"id": "other", "C": "print('other')\n"}],
            },
            tmp_path / "lab_stages.toml",
            export_context=NotebookExportContext(
                project_name="demo",
                module_path="nested/demo",
                artifact_dir=str(tmp_path / "artifacts"),
            ),
        )


@pytest.mark.parametrize(
    "stages, message",
    [
        (
            [
                {"id": "duplicate", "C": "print(1)\n"},
                {"id": "duplicate", "C": "print(2)\n"},
            ],
            "Duplicate workflow stage ID",
        ),
        (
            [{"id": "self", "depends_on": ["self"], "C": "print(1)\n"}],
            "cycle or self-dependency",
        ),
        (
            [{"id": "consumer", "depends_on": ["missing"], "C": "print(1)\n"}],
            "depends on missing stage",
        ),
    ],
)
def test_supervisor_notebook_export_rejects_invalid_stage_graph(
    tmp_path: Path,
    stages: list[dict[str, Any]],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_notebook_document(
            {MODULE_NAME: stages},
            tmp_path / "lab_stages.toml",
            export_context=NotebookExportContext(
                project_name=MODULE_NAME,
                module_path=MODULE_NAME,
                artifact_dir=str(tmp_path / "artifacts"),
            ),
        )


def test_supervisor_notebook_preserves_and_applies_automation_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stages_file = tmp_path / "lab_stages.toml"
    module_automation = {"profile": "FAST", "max_workers": 4}
    stage_contract = {
        "__meta__": {f"{MODULE_NAME}__automation": module_automation},
        MODULE_NAME: [
            {
                "id": "guarded",
                "C": "raise RuntimeError('must stay skipped')\n",
                "profiles": {"fast": {"automation": {"skip": True}}},
                "automation": {
                    "skip_if_outputs_exist": True,
                    "outputs": ["already-produced.json"],
                },
            }
        ],
    }
    notebook = build_notebook_document(
        stage_contract,
        stages_file,
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )
    exported = notebook["metadata"]["agilab"]
    exported_stage = exported["stages"][0]
    assert exported["module_automation"] == module_automation
    assert exported_stage["profiles"] == stage_contract[MODULE_NAME][0]["profiles"]
    assert exported_stage["automation"] == stage_contract[MODULE_NAME][0]["automation"]

    helper_source = "".join(notebook["cells"][1]["source"])
    namespace: dict[str, Any] = {}
    exec(helper_source, namespace)
    assert namespace["run_agilab_stage"](0) is None
    assert "skipped by the AGILAB stage contract" in capsys.readouterr().out

    notebook_import = build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook="exported/lab_stages.ipynb",
    )
    preview = build_lab_stages_preview(notebook_import, module_name=MODULE_NAME)
    assert preview["__meta__"][f"{MODULE_NAME}__automation"] == module_automation
    assert preview[MODULE_NAME][0]["profiles"] == stage_contract[MODULE_NAME][0]["profiles"]
    assert preview[MODULE_NAME][0]["automation"] == stage_contract[MODULE_NAME][0]["automation"]


def test_supervisor_notebook_profile_code_applies_until_source_is_edited(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    notebook = build_notebook_document(
        {
            "__meta__": {f"{MODULE_NAME}__automation": {"profile": "FAST"}},
            MODULE_NAME: [
                {
                    "id": "profiled",
                    "C": "print('base code')\n",
                    "profiles": {"fast": {"C": "print('profile code')\n"}},
                }
            ],
        },
        tmp_path / "lab_stages.toml",
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )
    helper_source = "".join(notebook["cells"][1]["source"])
    namespace: dict[str, Any] = {}
    exec(helper_source, namespace)

    namespace["run_agilab_stage"](0)
    assert "profile code" in capsys.readouterr().out

    namespace["run_agilab_stage"](0, code_override="print('edited code')\n")
    assert "edited code" in capsys.readouterr().out


@pytest.mark.parametrize(
    "control",
    [
        {"enabled": False},
        {"skip": True},
        {"automation": {"enabled": False}},
        {"automation": {"skip": True}},
    ],
)
def test_supervisor_notebook_enforces_disabled_and_skip_controls(
    tmp_path: Path,
    control: dict[str, Any],
) -> None:
    stage = {"id": "guarded", "C": "raise RuntimeError('must not run')\n", **control}
    notebook = build_notebook_document(
        {MODULE_NAME: [stage]},
        tmp_path / "lab_stages.toml",
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )
    namespace: dict[str, Any] = {}
    exec("".join(notebook["cells"][1]["source"]), namespace)

    assert namespace["run_agilab_stage"](0) is None


def test_supervisor_notebook_enforces_existing_output_skip(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "ready.json").write_text("{}\n", encoding="utf-8")
    notebook = build_notebook_document(
        {
            MODULE_NAME: [
                {
                    "id": "outputs-ready",
                    "C": "raise RuntimeError('must not run')\n",
                    "automation": {
                        "skip_if_outputs_exist": True,
                        "outputs": {"primary": "ready.json"},
                    },
                }
            ],
        },
        tmp_path / "lab_stages.toml",
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(artifact_dir),
        ),
    )
    namespace: dict[str, Any] = {}
    exec("".join(notebook["cells"][1]["source"]), namespace)

    assert namespace["run_agilab_stage"](0) is None


def test_supervisor_notebook_invalid_profile_falls_back_to_balanced(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    notebook = build_notebook_document(
        {
            "__meta__": {f"{MODULE_NAME}__automation": {"profile": "invalid"}},
            MODULE_NAME: [
                {
                    "id": "balanced-guard",
                    "C": "raise RuntimeError('must not run')\n",
                    "profiles": {"balanced": {"automation": {"skip": True}}},
                }
            ],
        },
        tmp_path / "lab_stages.toml",
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )
    namespace: dict[str, Any] = {}
    exec("".join(notebook["cells"][1]["source"]), namespace)

    assert namespace["run_agilab_stage"](0) is None
    assert (
        "Unknown automation profile 'invalid'; defaulting to 'balanced'"
        in caplog.text
    )


def test_supervisor_notebook_deep_merges_nested_profile_overrides(
    tmp_path: Path,
) -> None:
    notebook = build_notebook_document(
        {
            "__meta__": {f"{MODULE_NAME}__automation": {"profile": "fast"}},
            MODULE_NAME: [
                {
                    "id": "nested-profile",
                    "C": "print('base code')\n",
                    "automation": {
                        "runner": {
                            "retry": {
                                "policy": {
                                    "attempts": 2,
                                    "backoff": {"seconds": 1, "jitter": True},
                                }
                            }
                        }
                    },
                    "automation_profiles": {
                        "fast": {
                            "automation": {
                                "runner": {
                                    "retry": {
                                        "policy": {
                                            "backoff": {"seconds": 5},
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            ],
        },
        tmp_path / "lab_stages.toml",
        export_context=NotebookExportContext(
            project_name=MODULE_NAME,
            module_path=MODULE_NAME,
            artifact_dir=str(tmp_path / "artifacts"),
        ),
    )
    namespace: dict[str, Any] = {}
    exec("".join(notebook["cells"][1]["source"]), namespace)

    effective = namespace["_stage_with_selected_profile"](
        namespace["AGILAB_NOTEBOOK_EXPORT"]["stages"][0]
    )
    retry_policy = effective["automation"]["runner"]["retry"]["policy"]
    assert retry_policy == {
        "attempts": 2,
        "backoff": {"seconds": 5, "jitter": True},
    }
