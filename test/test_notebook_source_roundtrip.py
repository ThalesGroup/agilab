from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from agilab.notebooks.notebook_pipeline_import import (
    apply_notebook_runtime_roles,
    build_lab_stages_preview,
    build_notebook_import_contract,
    build_notebook_import_preflight,
    build_notebook_pipeline_import,
    build_notebook_source_export,
    build_notebook_setup_conversion,
    notebook_source_cell_edits_from_stages,
    write_notebook_source_export,
)


def _notebook() -> dict:
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": "python3", "language": "python", "display_name": "Python"},
                     "language_info": {"name": "python"}, "author": {"name": "Example"}},
        "cells": [
            {"id": "intro", "cell_type": "markdown", "source": "![plot](attachment:plot.png)",
             "metadata": {"tags": ["intro"]}, "attachments": {"plot.png": {"image/png": "aGVsbG8="}}},
            {"id": "setup", "cell_type": "code", "source": ["values = [2, 3]\n"],
             "metadata": {"agilab": {"runtime_role": "manager"}, "custom": {"keep": True}},
             "execution_count": 8, "outputs": [{"output_type": "stream", "name": "stdout", "text": "old\n"}]},
            {"id": "raw", "cell_type": "raw", "source": "raw content", "metadata": {"format": "text/plain"}},
            {"id": "empty", "cell_type": "code", "source": [], "metadata": {}, "execution_count": None, "outputs": []},
            {"id": "result", "cell_type": "code", "source": "answer = sum(values)\n",
             "metadata": {"agilab": {"runtime_role": "manager"}}, "execution_count": 2, "outputs": []},
            {"id": "end", "cell_type": "markdown", "source": ["Trailing context\n"], "metadata": {}},
        ],
    }


def test_source_roundtrip_recovers_every_cell_and_metadata_without_execution(tmp_path: Path) -> None:
    notebook = _notebook()
    marker = tmp_path / "must-not-exist"
    notebook["cells"][1]["source"] = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    original = copy.deepcopy(notebook)
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="editable.ipynb")
    contract = build_notebook_import_contract(imported)
    persisted = json.loads(json.dumps(contract))
    exported = build_notebook_source_export(persisted)
    assert exported == original
    assert notebook == original
    assert not marker.exists()
    exported["cells"][0]["metadata"]["tags"].append("changed")
    assert build_notebook_source_export(persisted) == original
    output = write_notebook_source_export(tmp_path / "editable-source-roundtrip.ipynb", persisted)
    assert json.loads(output.read_text()) == original
    assert not marker.exists()


def test_original_cell_identity_and_order_survive_pipeline_projection() -> None:
    imported = build_notebook_pipeline_import(notebook=_notebook(), source_notebook="editable.ipynb")
    stages = build_lab_stages_preview(imported, module_name="demo")["demo"]
    assert [(stage["NB_CELL_ID"], stage["NB_CELL_INDEX"]) for stage in stages] == [("setup", 2), ("result", 5)]
    compiled = build_lab_stages_preview(imported, module_name="demo", preserve_notebook_state=True)["demo"]
    assert [(cell["id"], cell["index"]) for cell in compiled[0]["NB_SOURCE_CELLS"]] == [("setup", 2), ("result", 5)]


def test_explicit_code_edit_records_divergence_and_clears_only_changed_outputs() -> None:
    original = _notebook()
    imported = build_notebook_pipeline_import(notebook=original, source_notebook="editable.ipynb")
    exported = build_notebook_source_export(imported, cell_edits={"setup": "values = [4, 5]\n"})
    assert exported["cells"][1]["source"] == ["values = [4, 5]\n"]
    assert exported["cells"][1]["outputs"] == []
    assert exported["cells"][1]["execution_count"] is None
    assert exported["cells"][0] == original["cells"][0]
    assert exported["cells"][2:] == original["cells"][2:]
    provenance = exported["metadata"]["agilab"]["source_roundtrip"]
    assert provenance["divergence"] == "edited"
    assert provenance["original_document_sha256"] == imported["source"]["document_sha256"]
    assert provenance["changed_cells"][0]["cell_id"] == "setup"
    assert build_notebook_source_export(imported) == original


@pytest.mark.parametrize("edits", [{"intro": "bad"}, {"unknown": "bad"}, {"setup": 42}])
def test_edits_reject_unknown_non_code_or_non_text_cells(edits: dict) -> None:
    imported = build_notebook_pipeline_import(notebook=_notebook(), source_notebook="editable.ipynb")
    with pytest.raises(ValueError, match="Cell edit"):
        build_notebook_source_export(imported, cell_edits=edits)


def test_tampered_source_document_is_rejected_before_writing(tmp_path: Path) -> None:
    imported = build_notebook_pipeline_import(notebook=_notebook(), source_notebook="editable.ipynb")
    imported["notebook_document"]["notebook"]["cells"][1]["source"] = "changed = True"
    target = tmp_path / "must-not-be-created" / "editable.ipynb"
    with pytest.raises(ValueError, match="fingerprint"):
        write_notebook_source_export(target, imported)
    assert not target.parent.exists()


@pytest.mark.parametrize("language,source,rule", [
    ("r", "answer <- 5", "unsupported_notebook_kernel"),
    ("python", "%time answer = 5", "notebook_magic_requires_conversion"),
    ("python", "%%bash\nprintf 'hello'", "notebook_magic_requires_conversion"),
    ("python", "await fetch_data()", "invalid_python_cell"),
])
def test_incompatible_runtime_is_blocked_but_original_notebook_remains_recoverable(language: str, source: str, rule: str) -> None:
    notebook = _notebook()
    notebook["metadata"]["language_info"]["name"] = language
    notebook["metadata"]["kernelspec"]["language"] = language
    notebook["cells"][1]["source"] = source
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="mixed.ipynb")
    reviewed = apply_notebook_runtime_roles(imported, {"cell-2": "manager", "cell-5": "manager"})
    preflight = build_notebook_import_preflight(reviewed)
    assert preflight["status"] == "blocked"
    assert preflight["safe_to_import"] is False
    assert rule in {risk["rule"] for risk in preflight["risks"]}
    assert build_notebook_source_export(reviewed) == notebook


def test_foreign_cell_language_is_not_overridden_by_python_kernel_or_role() -> None:
    notebook = _notebook()
    notebook["cells"][1]["metadata"]["vscode"] = {"languageId": "julia"}
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="mixed.ipynb")
    assert any(issue["rule"] == "unsupported_cell_language" for issue in imported["import_diagnostics"])
    assert build_notebook_import_preflight(imported)["safe_to_import"] is False


def test_future_flags_and_magic_looking_strings_do_not_block_python_cells() -> None:
    notebook = _notebook()
    notebook["cells"][1]["source"] = 'from __future__ import annotations\ntext = """\n%time is documentation\n"""\n'
    notebook["cells"][4]["source"] = "def f(value: UnknownType):\n    return value\n"
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="python.ipynb")
    assert imported["import_diagnostics"] == []
    assert build_notebook_import_preflight(imported)["safe_to_import"] is True


def test_reexport_maps_individual_edits_and_refuses_guessing_composite_changes() -> None:
    imported = build_notebook_pipeline_import(notebook=_notebook(), source_notebook="editable.ipynb")
    stages = build_lab_stages_preview(imported, module_name="demo")["demo"]
    stages[1]["C"] = "answer = max(values)\n"
    edits = notebook_source_cell_edits_from_stages(imported, stages)
    assert edits == {"result": "answer = max(values)\n"}
    compiled = build_lab_stages_preview(imported, module_name="demo", preserve_notebook_state=True)["demo"]
    assert notebook_source_cell_edits_from_stages(imported, compiled) == {}
    compiled[0]["C"] += "print('new composite code')\n"
    with pytest.raises(ValueError, match="cannot be assigned"):
        notebook_source_cell_edits_from_stages(imported, compiled)


def test_older_notebook_without_cell_ids_can_recover_and_apply_indexed_edits() -> None:
    notebook = _notebook()
    for cell in notebook["cells"]:
        cell.pop("id")
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="older.ipynb")
    assert build_notebook_source_export(imported) == notebook
    edited = build_notebook_source_export(imported, cell_edits={"cell-2": "values = [1]\n"})
    assert "id" not in edited["cells"][1]
    assert edited["cells"][1]["source"] == ["values = [1]\n"]


def test_setup_conversion_is_explicit_retains_requirements_and_never_installs(tmp_path: Path) -> None:
    notebook = _notebook()
    marker = tmp_path / "never-install"
    notebook["cells"][1]["source"] = (
        "%pip install --quiet 'numpy>=2,<3' pandas\n%matplotlib inline\nvalues = [2, 3]\n"
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('must not execute')\n"
    )
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="setup.ipynb")
    assert build_notebook_import_preflight(imported)["safe_to_import"] is False
    converted = build_notebook_setup_conversion(imported, cell_ids=["setup"])
    assert build_notebook_source_export(imported) == notebook
    declaration = converted["metadata"]["agilab"]["setup_conversion"]
    assert declaration["requirements"] == ["numpy>=2,<3", "pandas"]
    assert declaration["original_setup_cells"] == [notebook["cells"][1]]
    assert declaration["installs_dependencies"] is False
    assert declaration["executes_notebook"] is False
    reimported = build_notebook_pipeline_import(notebook=converted, source_notebook="setup-converted.ipynb")
    assert build_notebook_import_preflight(reimported)["safe_to_import"] is True
    assert build_notebook_import_contract(reimported)["environment"]["requirements"] == ["numpy>=2,<3", "pandas"]
    assert not marker.exists()


@pytest.mark.parametrize("setup", [
    "!pip install -r secret.txt", "%pip install --index-url https://example.invalid pkg",
    "!pip install 'pkg @ https://example.invalid/pkg.whl'", "%%bash\necho unsafe",
    "!pip install numpy; touch /tmp/unsafe", "!pip install numpy\n%time values = []",
])
def test_setup_conversion_refuses_unsupported_commands_and_partial_conversion(setup: str) -> None:
    notebook = _notebook()
    notebook["cells"][1]["source"] = setup
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="setup.ipynb")
    with pytest.raises(ValueError, match="manual|supported"):
        build_notebook_setup_conversion(imported, cell_ids=["setup"])
    assert build_notebook_source_export(imported) == notebook


def test_source_export_cli_recovers_and_deliberately_converts_setup(tmp_path: Path) -> None:
    from agilab.notebooks.notebook_pipeline_import import main

    notebook = _notebook()
    notebook["cells"][1]["source"] = "%pip install numpy\nvalues = [2, 3]\n"
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="setup.ipynb")
    contract_path = tmp_path / "notebook-import-contract.json"
    contract_path.write_text(json.dumps(build_notebook_import_contract(imported)))
    output = tmp_path / "setup-source-python.ipynb"
    assert main(["source-export", "--contract", str(contract_path), "--output", str(output),
                 "--convert-setup-cell", "setup"]) == 0
    converted = json.loads(output.read_text())
    assert converted["metadata"]["agilab"]["setup_conversion"]["requirements"] == ["numpy"]
    assert imported["notebook_document"]["notebook"] == notebook


def test_chained_edits_retain_upstream_provenance() -> None:
    imported = build_notebook_pipeline_import(notebook=_notebook(), source_notebook="editable.ipynb")
    first_edit = build_notebook_source_export(imported, cell_edits={"setup": "values = [4, 5]\n"})
    reimported = build_notebook_pipeline_import(notebook=first_edit, source_notebook="editable-edited.ipynb")
    next_edit = build_notebook_source_export(reimported, cell_edits={"result": "answer = max(values)\n"})
    provenance = next_edit["metadata"]["agilab"]["source_roundtrip"]
    assert provenance["upstream_provenance"] == first_edit["metadata"]["agilab"]["source_roundtrip"]
    assert provenance["upstream_provenance"]["original_document_sha256"] == imported["source"]["document_sha256"]


def test_conflicting_repeated_cell_edits_require_review() -> None:
    imported = build_notebook_pipeline_import(notebook=_notebook(), source_notebook="editable.ipynb")
    stages = [{"NB_CELL_ID": "result", "C": "answer = max(values)\n"},
              {"NB_CELL_ID": "result", "C": "answer = sum(values)\n"}]
    with pytest.raises(ValueError, match="Conflicting"):
        notebook_source_cell_edits_from_stages(imported, stages)


def test_successive_setup_conversions_retain_requirements_cells_and_provenance() -> None:
    notebook = _notebook()
    notebook["cells"][1]["source"] = "%pip install numpy\nvalues = [2, 3]\n"
    notebook["cells"][4]["source"] = "%pip install pandas numpy\nanswer = sum(values)\n"
    notebook["cells"].append({"id": "plot", "cell_type": "code", "source": "%matplotlib inline\n",
                              "metadata": {}, "outputs": [], "execution_count": None})
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="setup.ipynb")
    first = build_notebook_setup_conversion(imported, cell_ids=["setup"])
    first_provenance = copy.deepcopy(first["metadata"]["agilab"]["setup_conversion"])
    second_import = build_notebook_pipeline_import(notebook=first, source_notebook="first-conversion.ipynb")
    second = build_notebook_setup_conversion(second_import, cell_ids=["result"])
    declaration = second["metadata"]["agilab"]["setup_conversion"]
    assert declaration["requirements"] == ["numpy", "pandas"]
    assert declaration["original_setup_cells"] == [notebook["cells"][1], notebook["cells"][4]]
    assert declaration["upstream_conversion"] == first_provenance
    third_import = build_notebook_pipeline_import(notebook=second, source_notebook="second-conversion.ipynb")
    third = build_notebook_setup_conversion(third_import, cell_ids=["plot"])
    final_declaration = third["metadata"]["agilab"]["setup_conversion"]
    assert final_declaration["requirements"] == ["numpy", "pandas"]
    assert final_declaration["selected_cell_ids"] == ["plot", "result", "setup"]
    assert final_declaration["original_setup_cells"] == [notebook["cells"][1], notebook["cells"][4], notebook["cells"][-1]]
    assert final_declaration["upstream_conversion"] == declaration
    reimported = build_notebook_pipeline_import(notebook=third, source_notebook="all-converted.ipynb")
    assert build_notebook_import_contract(reimported)["environment"]["requirements"] == ["numpy", "pandas"]
    assert build_notebook_import_preflight(reimported)["safe_to_import"] is True


def test_supervisor_stage_edit_reexports_actual_encoded_source_cell_without_losing_provenance(tmp_path: Path) -> None:
    from agilab.notebooks.notebook_export_support import NotebookExportContext, build_notebook_document

    notebook = build_notebook_document(
        {"demo": [{"C": "answer = 1\n", "R": "runpy", "NB_CELL_ID": "original-code-cell"}]},
        tmp_path / "lab_stages.toml", export_context=NotebookExportContext(
            project_name="demo", module_path="demo", artifact_dir=str(tmp_path / "artifacts"),
        ),
    )
    source_cell = next(cell for cell in notebook["cells"] if cell.get("id") == "stage-000-source")
    source_cell["source"] = "note = 'élève'; " + "".join(source_cell["source"])
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="supervisor.ipynb")
    stages = build_lab_stages_preview(imported, module_name="demo")["demo"]
    assert stages[0]["NB_CELL_ID"] == "original-code-cell"
    assert stages[0]["NB_SOURCE_DOCUMENT_CELL_ID"] == "stage-000-source"
    assert notebook_source_cell_edits_from_stages(imported, stages) == {}
    stages[0]["C"] = "answer = 2\nlabel = 'café'\n"
    edits = notebook_source_cell_edits_from_stages(imported, stages)
    assert set(edits) == {"stage-000-source"}
    assert edits["stage-000-source"].startswith("note = 'élève'; ")
    assert "print(STAGE_000_CODE)" in edits["stage-000-source"]
    edited = build_notebook_source_export(imported, cell_edits=edits)
    reimported = build_notebook_pipeline_import(notebook=edited, source_notebook="supervisor-edited.ipynb")
    restored = build_lab_stages_preview(reimported, module_name="demo")["demo"]
    assert restored[0]["C"] == stages[0]["C"]
    assert restored[0]["NB_CELL_ID"] == "original-code-cell"
    assert build_notebook_source_export(imported) == notebook
    assert edited["metadata"]["agilab"]["source_roundtrip"]["changed_cells"][0]["cell_id"] == "stage-000-source"


def test_older_supervisor_mapping_is_diagnosed_instead_of_silently_ignoring_stage_edits(tmp_path: Path) -> None:
    from agilab.notebooks.notebook_export_support import NotebookExportContext, build_notebook_document

    notebook = build_notebook_document(
        {"demo": [{"C": "answer = 1\n", "R": "runpy"}]}, tmp_path / "lab_stages.toml",
        export_context=NotebookExportContext(project_name="demo", module_path="demo", artifact_dir="artifacts"),
    )
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook="supervisor.ipynb")
    stages = build_lab_stages_preview(imported, module_name="demo")["demo"]
    stages[0].pop("NB_SOURCE_DOCUMENT_CELL_ID")
    stages[0]["C"] = "answer = 2\n"
    with pytest.raises(ValueError, match="current source-cell identity"):
        notebook_source_cell_edits_from_stages(imported, stages)


@pytest.mark.parametrize("sample", sorted(Path("src/agilab/resources/notebook_import_samples").glob("*.ipynb")))
def test_packaged_import_samples_reexport_without_document_loss(sample: Path) -> None:
    notebook = json.loads(sample.read_text(encoding="utf-8"))
    imported = build_notebook_pipeline_import(notebook=notebook, source_notebook=sample.name)
    assert build_notebook_source_export(imported) == notebook
    assert build_notebook_import_preflight(imported)["safe_to_import"] is True
    assert imported["source"]["document_sha256"] == hashlib.sha256(
        json.dumps(notebook, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
