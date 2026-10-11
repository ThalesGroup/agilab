"""Recovery and handoff regressions for editable imported source notebooks."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys

import pytest

from agilab.notebooks import notebook_pipeline_import as notebook_import


def _notebook():
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"name": "python3", "language": "python", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "cells": [
            {"id": "context", "cell_type": "markdown", "metadata": {},
             "source": "Authored context", "attachments": {"proof.txt": {"text/plain": "proof"}}},
            {"id": "values", "cell_type": "code", "metadata": {},
             "source": "values = [2, 3]\n", "execution_count": 7,
             "outputs": [{"output_type": "stream", "name": "stdout", "text": "old values\n"}]},
            {"id": "answer", "cell_type": "code", "metadata": {},
             "source": "answer = sum(values)\n", "execution_count": 8,
             "outputs": [{"output_type": "stream", "name": "stdout", "text": "old answer\n"}]},
        ],
    }


def _import(document=None):
    return notebook_import.build_notebook_pipeline_import(
        notebook=_notebook() if document is None else document,
        source_notebook="authored-source.ipynb",
    )


@pytest.mark.parametrize("record", [None, [], {}, {"schema": "obsolete-document"}])
def test_export_rejects_missing_preserved_source_contract(record):
    with pytest.raises(ValueError, match="no preserved source notebook"):
        notebook_import.build_notebook_source_export({"notebook_document": record})


def test_unchanged_review_preserves_outputs_without_creating_divergence():
    document = _notebook()
    imported = _import(document)
    exported = notebook_import.build_notebook_source_export(
        imported, cell_edits={"values": document["cells"][1]["source"]},
    )
    assert exported == document
    assert "agilab" not in exported["metadata"]
    assert notebook_import.build_notebook_source_export(imported) == document


@pytest.mark.parametrize("metadata", ["corrupt metadata", {"agilab": ["invalid table"]}])
def test_edited_export_requires_writable_provenance_metadata(metadata):
    document = _notebook()
    document["metadata"] = metadata
    imported = _import(document)
    with pytest.raises(ValueError, match="metadata.*must be an object"):
        notebook_import.build_notebook_source_export(
            imported, cell_edits={"answer": "answer = max(values)\n"},
        )
    assert notebook_import.build_notebook_source_export(imported) == document


def test_stage_handoff_rejects_removed_source_document_cell():
    imported = _import()
    with pytest.raises(ValueError, match="no longer exists"):
        notebook_import.notebook_source_cell_edits_from_stages(
            imported, [{"NB_SOURCE_DOCUMENT_CELL_ID": "removed", "C": "answer = 99"}],
        )


def test_plain_source_document_handoff_maps_only_reviewed_cell():
    imported = _import()
    edits = notebook_import.notebook_source_cell_edits_from_stages(
        imported, [{"NB_SOURCE_DOCUMENT_CELL_ID": "answer", "C": "answer = max(values)\n"}],
    )
    assert edits == {"answer": "answer = max(values)\n"}
    exported = notebook_import.build_notebook_source_export(imported, cell_edits=edits)
    assert exported["cells"][:2] == _notebook()["cells"][:2]
    assert exported["cells"][2]["outputs"] == []


def test_unassociated_pipeline_stage_does_not_guess_original_cell():
    imported = _import()
    assert notebook_import.notebook_source_cell_edits_from_stages(
        imported, [{"NB_CELL_ID": "new-stage", "C": "answer = 99"}],
    ) == {}
    assert notebook_import.build_notebook_source_export(imported) == _notebook()


def test_compiled_handoff_rejects_non_text_source_cell():
    imported = _import()
    source = "answer = sum(values)\n"
    compiled_digest = hashlib.sha256(source.encode()).hexdigest()
    with pytest.raises(ValueError, match="must contain text"):
        notebook_import.notebook_source_cell_edits_from_stages(
            imported,
            [{"C": source, "NB_COMPILED_SHA256": compiled_digest,
              "NB_SOURCE_CELLS": [{"id": "answer", "source": 42}]}],
        )
    assert notebook_import.build_notebook_source_export(imported) == _notebook()


def test_encoded_stage_handoff_preserves_wrapper_and_unicode_context():
    document = _notebook()
    wrapper = (
        "# Contexte rédigé\n"
        "before = after = 0\n"
        "unrelated = 'retain'\n"
        "STAGE_003_CODE = 'answer = sum(values)\\n'\n"
        "reviewed_stage = STAGE_003_CODE\n"
    )
    document["cells"][2]["source"] = wrapper
    document["cells"][2]["metadata"] = {
        "agilab": {"stage_cell": {
            "schema": notebook_import.NOTEBOOK_EXPORT_STAGE_CELL_SCHEMA,
            "stage_index": 3,
        }},
    }
    imported = _import(document)
    unchanged = notebook_import.notebook_source_cell_edits_from_stages(
        imported, [{"NB_SOURCE_DOCUMENT_CELL_ID": "answer", "C": "answer = sum(values)\n"}],
    )
    assert unchanged == {}
    edits = notebook_import.notebook_source_cell_edits_from_stages(
        imported, [{"NB_SOURCE_DOCUMENT_CELL_ID": "answer", "C": "answer = max(values)\n"}],
    )
    scope = {}
    exec(edits["answer"], scope)
    assert scope["reviewed_stage"] == "answer = max(values)\n"
    assert "# Contexte rédigé\n" in edits["answer"]
    assert "before = after = 0\n" in edits["answer"]
    assert "unrelated = 'retain'\n" in edits["answer"]
    assert notebook_import.build_notebook_source_export(imported) == document


def test_plain_stage_source_is_editable_without_an_encoded_wrapper():
    assert notebook_import._replace_exported_stage_source(
        "answer = sum(values)\n", 3, "answer = max(values)\n",
    ) == "answer = max(values)\n"


@pytest.mark.parametrize(
    "selected,message",
    [([], "Choose at least one"), (["context"], "requires a code cell"),
     (["removed"], "unknown or ambiguous")],
)
def test_setup_conversion_requires_explicit_existing_code_cells(selected, message):
    imported = _import()
    with pytest.raises(ValueError, match=message):
        notebook_import.build_notebook_setup_conversion(imported, cell_ids=selected)
    assert notebook_import.build_notebook_source_export(imported) == _notebook()


@pytest.mark.parametrize(
    "previous,message",
    [
        ("invalid", "metadata must be an object"),
        ({"requirements": "numpy"}, "declarations are invalid"),
        ({"requirements": [42]}, "declarations are invalid"),
        ({"original_setup_cells": "old"}, "declarations are invalid"),
        ({"original_setup_cells": [42]}, "declarations are invalid"),
        ({"selected_cell_ids": "setup"}, "declarations are invalid"),
        ({"selected_cell_ids": [42]}, "declarations are invalid"),
    ],
)
def test_successive_setup_conversion_refuses_corrupt_prior_declarations(previous, message):
    document = _notebook()
    document["metadata"]["agilab"] = {"setup_conversion": previous}
    document["cells"][1]["source"] = "%pip install 'numpy>=2,<3'\nvalues = [2, 3]\n"
    imported = _import(document)
    with pytest.raises(ValueError, match=message):
        notebook_import.build_notebook_setup_conversion(imported, cell_ids=["values"])
    assert notebook_import.build_notebook_source_export(imported) == document


def test_source_export_cli_roundtrip_and_edits_execute_in_fresh_python(tmp_path, capsys):
    original = _notebook()
    imported = _import(original)
    contract = tmp_path / "authored_notebook_import_contract.json"
    contract.write_text(json.dumps(imported), encoding="utf-8")
    original_export = tmp_path / "authored_notebook_source_recovered.ipynb"
    assert notebook_import.main([
        "source-export", "--contract", str(contract), "--output", str(original_export),
    ]) == 0
    assert json.loads(original_export.read_text()) == original

    edits = tmp_path / "authored_notebook_reviewed_cell_edits.json"
    edits.write_text(json.dumps({"answer": "answer = max(values)\nprint(answer)\n"}))
    edited_export = tmp_path / "reviewed" / "authored_notebook_source_edited.ipynb"
    assert notebook_import.main([
        "source-export", "--contract", str(contract), "--output", str(edited_export),
        "--cell-edits", str(edits),
    ]) == 0
    edited = json.loads(edited_export.read_text())
    assert edited["cells"][:2] == original["cells"][:2]
    assert edited["cells"][2]["outputs"] == []
    assert edited["cells"][2]["execution_count"] is None
    code = "\n".join(
        "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        for cell in edited["cells"] if cell["cell_type"] == "code"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True,
        timeout=10, check=True,
    )
    assert completed.stdout.strip() == "3"
    assert json.loads(contract.read_text()) == imported
    assert "notebook execution: none" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["missing-contract", "invalid-edits", "write-denied"])
def test_source_export_cli_reports_failures_without_partial_notebook(
    tmp_path, monkeypatch, capsys, failure,
):
    contract = tmp_path / "authored_notebook_import_contract.json"
    contract.write_text(json.dumps(_import()))
    output = tmp_path / "authored_notebook_source_recovered.ipynb"
    argv = ["source-export", "--contract", str(contract), "--output", str(output)]
    if failure == "missing-contract":
        contract.unlink()
    elif failure == "invalid-edits":
        edits = tmp_path / "authored_notebook_invalid_cell_edits.json"
        edits.write_text(json.dumps({"answer": 42}))
        argv.extend(["--cell-edits", str(edits)])
    else:
        original_write = type(output).write_text

        def denied(path, *args, **kwargs):
            if path == output:
                raise PermissionError("output denied")
            return original_write(path, *args, **kwargs)

        monkeypatch.setattr(type(output), "write_text", denied)
    with pytest.raises(SystemExit) as exc:
        notebook_import.main(argv)
    assert exc.value.code == 2
    assert "Source notebook export failed:" in capsys.readouterr().err
    assert not output.exists()


def test_pipeline_toml_dependency_failure_explains_recovery_without_writing(monkeypatch):
    monkeypatch.setitem(sys.modules, "tomli_w", None)
    target = io.BytesIO()
    with pytest.raises(RuntimeError, match="tomli-w"):
        notebook_import._dump_toml({"stage": []}, target)
    assert target.getvalue() == b""


@pytest.mark.parametrize("kernel", ["julia", "ir", "bash"])
def test_foreign_kernel_name_blocks_python_claim_but_keeps_authored_source(kernel):
    document = _notebook()
    document["metadata"]["kernelspec"]["name"] = kernel
    imported = _import(document)
    diagnostics = imported["import_diagnostics"]
    assert "unsupported_notebook_kernel" in {entry["rule"] for entry in diagnostics}
    assert notebook_import.build_notebook_import_preflight(imported)["safe_to_import"] is False
    assert notebook_import.build_notebook_source_export(imported) == document


def test_cell_language_and_invalid_role_metadata_do_not_invent_worker_execution():
    document = _notebook()
    document["cells"][1]["metadata"] = {"agilab": "invalid role declaration", "language": "python"}
    imported = _import(document)
    assert notebook_import.build_notebook_source_export(imported) == document
    assert imported["import_diagnostics"] == []
    assert all(stage.get("runtime") != "agi.run" for stage in imported["pipeline_stages"])


def test_legacy_supervisor_without_current_cell_identity_requires_reimport():
    imported = _import()
    imported["source"]["import_mode"] = "agilab_supervisor_metadata"
    with pytest.raises(ValueError, match="Import the source notebook again"):
        notebook_import.notebook_source_cell_edits_from_stages(
            imported, [{"NB_CELL_ID": "retired-cell-identity", "C": "answer = 99"}],
        )
    assert notebook_import.build_notebook_source_export(imported) == _notebook()


def test_source_conversion_cli_extends_reviewed_setup_declarations_without_installing(
    tmp_path,
):
    document = _notebook()
    document["metadata"]["agilab"] = {
        "setup_conversion": {
            "requirements": ["pandas"],
            "original_setup_cells": [],
            "selected_cell_ids": ["retained-previous-cell"],
        },
    }
    document["cells"][1]["source"] = "%pip install numpy pandas\nvalues = [2, 3]\n"
    imported = _import(document)
    contract = tmp_path / "authored_setup_import_contract.json"
    contract.write_text(json.dumps(imported))
    output = tmp_path / "authored_setup_converted_source.ipynb"
    assert notebook_import.main([
        "source-export", "--contract", str(contract), "--output", str(output),
        "--convert-setup-cell", "values",
    ]) == 0
    converted = json.loads(output.read_text())
    setup = converted["metadata"]["agilab"]["setup_conversion"]
    assert setup["requirements"] == ["pandas", "numpy"]
    assert setup["selected_cell_ids"] == ["retained-previous-cell", "values"]
    assert setup["installs_dependencies"] is False
    assert setup["executes_notebook"] is False
    assert setup["original_setup_cells"] == [document["cells"][1]]
    assert notebook_import.build_notebook_source_export(imported) == document


def test_pipeline_view_preserves_known_dependencies_without_dangling_handoffs():
    imported = _import()
    first, second = imported["pipeline_stages"]
    second["depends_on"] = [first["id"], "removed-stage"]
    second["context_ids"] = ["removed-context"]
    view = notebook_import.build_notebook_import_pipeline_view(
        imported,
        preflight={"status": "ready", "artifact_contract": {"references": [], "outputs": ["unregistered.csv"]}},
    )
    dependency_edges = [edge for edge in view["edges"] if edge["kind"] == "depends_on"]
    assert len(dependency_edges) == 1
    nodes = {node["id"]: node for node in view["nodes"]}
    assert nodes[dependency_edges[0]["from"]]["source_cell_id"] == first["id"]
    assert nodes[dependency_edges[0]["to"]]["source_cell_id"] == second["id"]
    assert all(edge["from"] in nodes and edge["to"] in nodes for edge in view["edges"])
    assert not any(edge["kind"] == "analysis_consumes" for edge in view["edges"])
