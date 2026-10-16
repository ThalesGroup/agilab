"""Reviewed notebook updates preserve authored workflow edits and recovery bytes."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest
import tomli_w

from test.test_pipeline_editor import _stateful_notebook_review, pipeline_editor


def _document():
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"}},
        "cells": [
            {
                "id": "intro",
                "cell_type": "markdown",
                "source": "# A reusable experiment",
                "metadata": {},
            },
            {
                "id": "seed",
                "cell_type": "code",
                "source": "values = [2, 3]\nalias = values\n",
                "metadata": {},
            },
            {
                "id": "mutate",
                "cell_type": "code",
                "source": "alias.append(5)\n",
                "metadata": {},
            },
            {
                "id": "result",
                "cell_type": "code",
                "source": "total = sum(values)\n",
                "metadata": {},
            },
        ],
    }


def _edited_document():
    document = _document()
    document["cells"][2]["source"] = "alias.append(8)\n"
    return document


def _uploaded(document, *, name="reviewed_experiment.ipynb"):
    payload = json.dumps(document).encode("utf-8")
    return SimpleNamespace(
        name=name,
        type="application/x-ipynb+json",
        read=lambda: payload,
    )


def _tree(project):
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }


def _build(case, document=None, *, name="reviewed_experiment.ipynb"):
    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded(document or _edited_document(), name=name),
        case.project,
        stages_file=case.stages_file,
        module_name="demo",
    )
    assert preview is not None
    case.ui.session_state["idx__notebook_import_preview"] = preview
    return preview


def _roles(preview, role="manager"):
    return {
        str(stage["id"]): role
        for stage in preview["notebook_import"]["pipeline_stages"]
    }


def _review(case, preview=None, *, role="manager"):
    preview = preview or _build(case)
    prepared = pipeline_editor.prepare_notebook_import_preview(
        preview,
        runtime_roles=_roles(preview, role),
        preserve_notebook_state=True,
    )
    return pipeline_editor.prepare_notebook_import_update_preview(
        prepared, case.stages_file
    )


def _confirm(case, preview, reviewed, **overrides):
    options = {
        "runtime_roles": _roles(preview),
        "preserve_notebook_state": True,
        "write_mode": "update",
        "update_review_signature": reviewed["update_review_signature"],
    }
    options.update(overrides)
    return pipeline_editor.confirm_notebook_import_preview(
        case.project, case.stages_file, "idx", **options
    )


def _rewrite_stages(case, edit):
    content = tomllib.loads(case.stages_file.read_text(encoding="utf-8"))
    edit(content)
    case.stages_file.write_text(tomli_w.dumps(content), encoding="utf-8")
    return content


@pytest.fixture
def imported_project(monkeypatch, tmp_path):
    project = tmp_path / "reviewed_update_project"
    _, ui, messages = _stateful_notebook_review(monkeypatch, project)
    case = SimpleNamespace(
        project=project,
        stages_file=project / "lab_stages.toml",
        ui=ui,
        messages=messages,
    )
    preview = _build(case, _document())
    assert (
        pipeline_editor.confirm_notebook_import_preview(
            project,
            case.stages_file,
            "idx",
            runtime_roles=_roles(preview),
            preserve_notebook_state=True,
        )
        == 3
    )
    assert not any(kind == "error" for kind, _ in messages), messages
    ui.session_state.pop("page_broken", None)
    messages.clear()
    return case


def test_review_reports_changed_cells_without_executing_or_writing(imported_project):
    case = imported_project
    marker = case.project / "must-not-execute-on-review.txt"
    document = _edited_document()
    document["cells"][2]["source"] += (
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('unexpected')\n"
    )
    preview = _build(case, document)
    original = copy.deepcopy(preview)
    before = _tree(case.project)

    reviewed = _review(case, preview)

    assert preview == original
    assert _tree(case.project) == before
    assert not marker.exists()
    assert reviewed["write_mode"] == "update"
    assert reviewed["update_plan"]["source_name"] == "reviewed_experiment.ipynb"
    assert reviewed["update_plan"]["stage_index"] == 0
    changes = reviewed["update_plan"]["cell_changes"]
    assert changes["changed"] == ["mutate"]
    assert changes["unchanged"] == ["seed", "result"]
    assert changes["added"] == changes["removed"] == changes["moved"] == []
    assert len(reviewed["update_review_signature"]) == 64


def test_update_preserves_authored_fields_and_unrelated_stages(imported_project):
    case = imported_project
    authored = {
        "D": "My reviewed experiment description",
        "Q": "Investigate the effect of mutation",
        "M": "a hand-selected model",
        "id": "experiment-stage",
        "depends_on": ["prepare-data"],
        "custom_notes": {"owner": "scientist", "version": 3},
    }
    unrelated = {
        "id": "prepare-data",
        "D": "Handwritten prerequisite",
        "Q": "Keep this stage exactly",
        "C": "ready = True\n",
        "R": "runpy",
        "custom_notes": {"do_not_replace": True},
    }

    def edit(content):
        content["demo"][0].update(authored)
        content["demo"].insert(0, unrelated)
        content["analysis"] = [{"C": "print('independent module')", "R": "runpy"}]

    existing = _rewrite_stages(case, edit)
    preview = _build(case)
    reviewed = _review(case, preview)

    assert _confirm(case, preview, reviewed) == 3

    stored = tomllib.loads(case.stages_file.read_text(encoding="utf-8"))
    assert stored["demo"][0] == unrelated
    assert stored["analysis"] == existing["analysis"]
    assert len(stored["demo"]) == 2
    stage = stored["demo"][1]
    for key, value in authored.items():
        assert stage[key] == value
    assert "alias.append(8)" in stage["C"]
    assert "alias.append(5)" not in stage["C"]
    assert stage["NB_EXECUTION_STRATEGY"] == "shared_namespace"
    assert [cell["id"] for cell in stage["NB_SOURCE_CELLS"]] == [
        "seed",
        "mutate",
        "result",
    ]
    assert not any(kind == "error" for kind, _ in case.messages), case.messages


def test_review_tracks_added_and_removed_cells(imported_project):
    case = imported_project
    document = _document()
    intro, seed, _mutate, result = document["cells"]
    extra = {
        "id": "double",
        "cell_type": "code",
        "source": "values *= 2\n",
        "metadata": {},
    }
    document["cells"] = [intro, seed, result, extra]
    preview = _build(case, document)
    reviewed = _review(case, preview)

    changes = reviewed["update_plan"]["cell_changes"]
    assert changes["added"] == ["double"]
    assert changes["removed"] == ["mutate"]
    assert changes["moved"] == []
    assert not changes["changed"]
    assert _confirm(case, preview, reviewed) == 3
    stage = tomllib.loads(case.stages_file.read_text())["demo"][0]
    assert [cell["id"] for cell in stage["NB_SOURCE_CELLS"]] == [
        "seed",
        "result",
        "double",
    ]
    assert "alias.append(5)" not in stage["C"]


def test_review_tracks_reordered_stable_ids_and_compiles_the_new_order(
    imported_project,
):
    case = imported_project
    document = _document()
    intro, seed, mutate, result = document["cells"]
    document["cells"] = [intro, seed, result, mutate]
    preview = _build(case, document)
    reviewed = _review(case, preview)

    changes = reviewed["update_plan"]["cell_changes"]
    assert set(changes["moved"]) == {"mutate", "result"}
    assert changes["added"] == changes["removed"] == changes["changed"] == []
    assert _confirm(case, preview, reviewed) == 3
    stage = tomllib.loads(case.stages_file.read_text())["demo"][0]
    assert [cell["id"] for cell in stage["NB_SOURCE_CELLS"]] == [
        "seed",
        "result",
        "mutate",
    ]
    namespace = {"__name__": "__main__"}
    exec(stage["C"], namespace)
    assert namespace["total"] == 5
    assert namespace["values"] == [2, 3, 5]


def test_import_edit_reimport_twice_keeps_one_execution_and_recovery_bytes(
    imported_project,
):
    case = imported_project
    before = _tree(case.project)
    preview = _build(case)
    reviewed = _review(case, preview)
    assert _confirm(case, preview, reviewed) == 3

    backups = list(case.project.glob("notebook_import_before_update_*.json"))
    assert len(backups) == 1
    backup_bytes = backups[0].read_bytes()
    bundle = json.loads(backup_bytes)
    assert bundle["schema"] == "agilab.notebook_import_update_backup.v1"
    assert set(bundle["targets"]) == set(before)
    for name, original in before.items():
        record = bundle["targets"][name]
        assert record["sha256"] == hashlib.sha256(original).hexdigest()
        assert record["base64"] == base64.b64encode(original).decode("ascii")
        assert record["size_bytes"] == len(original)
    from agilab.notebooks.notebook_import_update import verify_update_backup

    assert verify_update_backup(backups[0]) == before
    first = _tree(case.project)
    preview = _build(case)
    reviewed = _review(case, preview)
    assert reviewed["update_plan"]["cell_changes"]["changed"] == []
    assert _confirm(case, preview, reviewed) == 3

    stages = tomllib.loads(case.stages_file.read_text())["demo"]
    assert len(stages) == 1
    assert _tree(case.project) == first
    assert backups[0].read_bytes() == backup_bytes
    namespace = {"__name__": "__main__"}
    exec(stages[0]["C"], namespace)
    assert namespace["values"] == [2, 3, 8]
    assert namespace["total"] == 13


@pytest.mark.parametrize("corruption", ["bytes", "hash", "inventory"])
def test_previous_import_recovery_rejects_corrupt_downloads(
    imported_project, corruption
):
    from agilab.notebooks.notebook_import_update import verify_update_backup

    case = imported_project
    preview = _build(case)
    reviewed = _review(case, preview)
    assert _confirm(case, preview, reviewed) == 3
    backup_path = next(case.project.glob("notebook_import_before_update_*.json"))
    bundle = json.loads(backup_path.read_bytes())
    if corruption == "bytes":
        bundle["targets"]["lab_stages.toml"]["base64"] = base64.b64encode(
            b"different"
        ).decode()
    elif corruption == "hash":
        bundle["targets"]["lab_stages.toml"]["sha256"] = "0" * 64
    else:
        bundle["targets"].pop("lab_stages.toml")
    downloaded = case.project / "corrupt_downloaded_notebook_import_backup.json"
    downloaded.write_text(json.dumps(bundle))
    before = _tree(case.project)

    with pytest.raises(ValueError):
        verify_update_backup(downloaded)

    assert _tree(case.project) == before


@pytest.mark.parametrize("signature", [None, "", "0" * 64])
def test_update_requires_the_exact_explicit_review_signature(
    imported_project, signature
):
    case = imported_project
    preview = _build(case)
    reviewed = _review(case, preview)
    before = _tree(case.project)

    assert _confirm(case, preview, reviewed, update_review_signature=signature) == 0

    assert _tree(case.project) == before
    assert not case.ui.session_state.get("page_broken", False)
    assert any(kind == "error" for kind, _ in case.messages), case.messages
    assert not any(kind == "success" for kind, _ in case.messages)


def test_a_review_signature_does_not_enable_an_implicit_update(imported_project):
    case = imported_project
    preview = _build(case)
    reviewed = _review(case, preview)
    before = _tree(case.project)

    assert _confirm(case, preview, reviewed, write_mode=None) == 0

    assert _tree(case.project) == before
    assert any(kind == "error" for kind, _ in case.messages)


@pytest.mark.parametrize("side", ["incoming", "previous"])
@pytest.mark.parametrize("identity", ["missing", "duplicate"])
def test_review_rejects_unstable_document_cell_ids(imported_project, side, identity):
    case = imported_project
    document = _edited_document()
    if side == "previous":
        contract_path = case.project / "notebook_import_contract.json"
        contract = json.loads(contract_path.read_text())
        target = contract["notebook_document"]["notebook"]
    else:
        target = document
    if identity == "missing":
        target["cells"][2].pop("id")
    else:
        target["cells"][2]["id"] = target["cells"][1]["id"]
    if side == "previous":
        # Recompute the document envelope, leaving independently bound stage
        # provenance intact: neither a hash envelope nor guessed positions is ID proof.
        contract["notebook_document"]["sha256"] = hashlib.sha256(
            json.dumps(
                target, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        contract_path.write_text(json.dumps(contract))
    preview = _build(case, document)
    before = _tree(case.project)

    with pytest.raises(ValueError):
        _review(case, preview)

    assert _tree(case.project) == before


@pytest.mark.parametrize(
    "drift",
    [
        "compiled_source",
        "compiled_hash",
        "source_cell",
        "source_hash",
        "duplicate_stage",
    ],
)
def test_review_rejects_manually_drifted_execution_provenance(imported_project, drift):
    case = imported_project

    def edit(content):
        stage = content["demo"][0]
        if drift == "compiled_source":
            stage["C"] += "\nprint('manual execution edit')\n"
        elif drift == "compiled_hash":
            stage["NB_COMPILED_SHA256"] = "0" * 64
        elif drift == "source_cell":
            stage["NB_SOURCE_CELLS"][1]["source"] = "alias.append(999)\n"
        elif drift == "source_hash":
            stage["NB_SOURCE_SHA256"] = "0" * 64
        else:
            content["demo"].append(copy.deepcopy(stage))

    _rewrite_stages(case, edit)
    preview = _build(case)
    before = _tree(case.project)

    with pytest.raises(ValueError):
        _review(case, preview)

    assert _tree(case.project) == before


@pytest.mark.parametrize("mismatch", ["runtime", "environment", "filename", "legacy"])
def test_update_review_rejects_incompatible_execution_contracts(
    imported_project, mismatch
):
    case = imported_project
    name = (
        "different_notebook.ipynb"
        if mismatch == "filename"
        else "reviewed_experiment.ipynb"
    )
    preview = _build(case, name=name)
    prepared = pipeline_editor.prepare_notebook_import_preview(
        preview,
        runtime_roles=_roles(preview, "worker" if mismatch == "runtime" else "manager"),
        preserve_notebook_state=mismatch != "legacy",
    )
    if mismatch == "environment":
        prepared["toml_content"]["demo"][0]["E"] = "different-environment"
    before = _tree(case.project)

    with pytest.raises(ValueError):
        pipeline_editor.prepare_notebook_import_update_preview(
            prepared, case.stages_file
        )

    assert _tree(case.project) == before


@pytest.mark.parametrize(
    "failure", ["missing", "broken_json", "document_hash", "module"]
)
def test_update_review_rejects_unverified_previous_contract(imported_project, failure):
    case = imported_project
    contract_path = case.project / "notebook_import_contract.json"
    if failure == "missing":
        contract_path.unlink()
    elif failure == "broken_json":
        contract_path.write_text("{not json")
    else:
        contract = json.loads(contract_path.read_text())
        if failure == "document_hash":
            contract["notebook_document"]["sha256"] = "0" * 64
        else:
            contract["module_name"] = "another_module"
        contract_path.write_text(json.dumps(contract))
    preview = _build(case)
    before = _tree(case.project)

    with pytest.raises(ValueError):
        _review(case, preview)

    assert _tree(case.project) == before


@pytest.mark.parametrize(
    "filename",
    [
        "lab_stages.toml",
        "notebook_import_contract.json",
        "notebook_import_pipeline_view.json",
        "notebook_import_view_plan.json",
    ],
)
def test_confirm_rejects_any_target_changed_after_review(imported_project, filename):
    case = imported_project
    preview = _build(case)
    reviewed = _review(case, preview)
    path = case.project / filename
    path.write_bytes(path.read_bytes() + b"\n")
    before = _tree(case.project)

    assert _confirm(case, preview, reviewed) == 0

    assert _tree(case.project) == before
    assert any(kind == "error" for kind, _ in case.messages)


def test_confirm_rejects_source_changed_after_review(imported_project):
    case = imported_project
    preview = _build(case)
    reviewed = _review(case, preview)
    _build(case, _document())
    before = _tree(case.project)

    assert _confirm(case, preview, reviewed) == 0

    assert _tree(case.project) == before
    assert any(kind == "error" for kind, _ in case.messages)


@pytest.mark.parametrize("tamper", ["merged_source", "plan_index", "review_signature"])
def test_direct_writer_rechecks_reviewed_update_instead_of_trusting_payload(
    imported_project, tamper
):
    case = imported_project
    reviewed = _review(case)
    if tamper == "merged_source":
        reviewed["update_plan"]["merged_content"]["demo"][0]["C"] = "print('tampered')"
    elif tamper == "plan_index":
        reviewed["update_plan"]["stage_index"] = 99
    else:
        reviewed["update_review_signature"] = "0" * 64
    before = _tree(case.project)

    with pytest.raises(ValueError):
        pipeline_editor.write_notebook_import_preview(
            reviewed, case.project, case.stages_file, write_mode="update"
        )

    assert _tree(case.project) == before


def test_cancelling_update_discards_review_without_modifying_project(imported_project):
    case = imported_project
    _review(case)
    before = _tree(case.project)

    pipeline_editor.cancel_notebook_import_preview("idx")

    assert _tree(case.project) == before
    assert "idx__notebook_import_preview" not in case.ui.session_state
    assert not case.ui.session_state.get("page_broken", False)


@pytest.mark.parametrize("boundary", ["sidecar", "replacement"])
def test_failed_update_rolls_back_every_previous_target(
    imported_project, monkeypatch, boundary
):
    case = imported_project
    preview = _build(case)
    reviewed = _review(case, preview)
    before = _tree(case.project)
    if boundary == "sidecar":

        def fail_sidecar(*args, **kwargs):
            raise OSError("injected update sidecar failure")

        monkeypatch.setattr(
            pipeline_editor, "write_notebook_import_contract", fail_sidecar
        )
    else:
        original_replace = Path.replace

        def fail_stages_replace(self, target):
            if Path(target) == case.stages_file and self.name.endswith(".tmp"):
                raise OSError("injected final stages replacement failure")
            return original_replace(self, target)

        monkeypatch.setattr(Path, "replace", fail_stages_replace)

    assert _confirm(case, preview, reviewed) == 0

    current = _tree(case.project)
    for name, previous_bytes in before.items():
        assert current[name] == previous_bytes
    assert not list(case.project.glob(".*.tmp"))
    assert not case.ui.session_state.get("page_broken", False)
    assert any(kind == "error" for kind, _ in case.messages)
    assert not any(kind == "success" for kind, _ in case.messages)


@pytest.mark.parametrize("change", ["metadata", "outputs"])
def test_direct_writer_binds_preserved_document_content_beyond_executable_source(
    imported_project, change
):
    from agilab.notebooks.notebook_import_update import canonical_json, sha256

    case = imported_project
    reviewed = _review(case)
    record = reviewed["notebook_import"]["notebook_document"]
    document = record["notebook"]
    if change == "metadata":
        document["metadata"]["custom"] = {"review_status": "changed after review"}
    else:
        document["cells"][2]["outputs"] = [
            {"output_type": "stream", "name": "stdout", "text": "unreviewed output\n"}
        ]
        document["cells"][2]["execution_count"] = 999
    # The document envelope remains internally valid, and executable source is
    # identical. The review must still bind the full notebook being persisted.
    record["sha256"] = sha256(canonical_json(document))
    before = _tree(case.project)

    with pytest.raises(ValueError, match="[Rr]eview|changed"):
        pipeline_editor.write_notebook_import_preview(
            reviewed, case.project, case.stages_file, write_mode="update"
        )

    assert _tree(case.project) == before


def test_changes_during_recovery_backup_are_preserved_without_applying_update(
    imported_project, monkeypatch
):
    case = imported_project
    reviewed = _review(case)
    before = _tree(case.project)
    update_module = pipeline_editor._notebook_import_update_module
    original_backup = update_module.write_update_backup
    changed_path = case.project / "notebook_import_pipeline_view.json"
    concurrent_bytes = changed_path.read_bytes() + b"\n"
    invoked = []

    def change_after_backup(*args, **kwargs):
        path = original_backup(*args, **kwargs)
        changed_path.write_bytes(concurrent_bytes)
        invoked.append(path)
        return path

    monkeypatch.setattr(update_module, "write_update_backup", change_after_backup)

    with pytest.raises(ValueError, match="changed|review"):
        pipeline_editor.write_notebook_import_preview(
            reviewed, case.project, case.stages_file, write_mode="update"
        )

    assert len(invoked) == 1
    for name, original in before.items():
        expected = concurrent_bytes if name == changed_path.name else original
        assert (case.project / name).read_bytes() == expected
    assert not list(case.project.glob(".*.tmp"))
    assert "update_backup_path" not in reviewed


def test_update_rejects_a_notebook_with_no_matching_source_cell_ids(imported_project):
    case = imported_project
    document = _edited_document()
    for cell in document["cells"]:
        cell["id"] = f"another-{cell['id']}"
    preview = _build(case, document)
    before = _tree(case.project)

    with pytest.raises(ValueError, match="[Nn]o stable|lineage"):
        _review(case, preview)

    assert _tree(case.project) == before


@pytest.mark.parametrize(
    "invalid",
    [
        "missing_document",
        "document_schema",
        "document_type",
        "missing_cells",
        "invalid_cell",
        "missing_id",
        "blank_id",
        "non_string_id",
        "missing_source_lineage",
    ],
)
def test_update_planner_rejects_invalid_preserved_source_identity(
    imported_project, invalid
):
    from agilab.notebooks.notebook_import_update import (
        canonical_json,
        plan_notebook_import_update,
        sha256,
    )

    case = imported_project
    preview = _build(case)
    prepared = pipeline_editor.prepare_notebook_import_preview(
        preview, runtime_roles=_roles(preview), preserve_notebook_state=True
    )
    current = tomllib.loads(case.stages_file.read_text())
    previous = json.loads((case.project / "notebook_import_contract.json").read_text())
    record = previous["notebook_document"]
    document = record["notebook"]
    if invalid == "missing_document":
        previous.pop("notebook_document")
    elif invalid == "document_schema":
        record["schema"] = "another.notebook.document"
    elif invalid == "document_type":
        record["notebook"] = []
    elif invalid == "missing_cells":
        document.pop("cells")
    elif invalid == "invalid_cell":
        document["cells"].append("invalid cell metadata")
    elif invalid == "missing_id":
        document["cells"][1].pop("id")
    elif invalid == "blank_id":
        document["cells"][1]["id"] = "   "
    elif invalid == "non_string_id":
        document["cells"][1]["id"] = 12
    else:
        previous["source"] = []
    if isinstance(record.get("notebook"), dict):
        record["sha256"] = sha256(canonical_json(record["notebook"]))
    before = _tree(case.project)

    with pytest.raises(ValueError):
        plan_notebook_import_update(
            current,
            prepared["toml_content"],
            notebook_import=prepared["notebook_import"],
            previous_contract=previous,
            module_name="demo",
        )

    assert _tree(case.project) == before


def test_renderer_selects_reviewed_update_and_retains_recovery_after_cancel(
    imported_project, monkeypatch
):
    case = imported_project
    preview = _build(case)
    reviewed = _review(case, preview)
    calls = []
    downloads = []
    forwarded = []
    click = {"label": "Update notebook stage"}

    def selectbox(label, options, **kwargs):
        calls.append(("selectbox", label, list(options)))
        if label == "Notebook import action":
            return "Update existing notebook stage"
        if label == "Notebook import scope":
            return "All runnable cells"
        assert label.startswith("Cell ") and label.endswith(" runtime")
        return "Manager (local runpy)"

    def button(label, **kwargs):
        calls.append(("button", label, kwargs))
        return label == click["label"]

    original_confirm = pipeline_editor.confirm_notebook_import_preview

    def confirm(*args, **kwargs):
        forwarded.append((args, kwargs))
        return original_confirm(*args, **kwargs)

    target = SimpleNamespace(
        selectbox=selectbox,
        checkbox=lambda *args, **kwargs: True,
        button=button,
        caption=lambda text, **kwargs: calls.append(("caption", text)),
        code=lambda text, **kwargs: calls.append(("code", text)),
        warning=lambda text, **kwargs: calls.append(("warning", text)),
        error=lambda text, **kwargs: calls.append(("error", text)),
        download_button=lambda label, **kwargs: downloads.append((label, kwargs)),
    )
    monkeypatch.setattr(pipeline_editor, "confirm_notebook_import_preview", confirm)

    pipeline_editor.render_notebook_import_preview(
        case.project, case.stages_file, "idx", container=target
    )

    assert len(forwarded) == 1
    assert forwarded[0][1]["write_mode"] == "update"
    assert (
        forwarded[0][1]["update_review_signature"]
        == reviewed["update_review_signature"]
    )
    assert forwarded[0][1]["preserve_notebook_state"] is True
    assert forwarded[0][1]["runtime_roles"] == _roles(preview)
    update_button = next(
        call for call in calls if call[:2] == ("button", "Update notebook stage")
    )
    assert update_button[2]["disabled"] is False
    assert not any(
        call[:2] == ("button", "Import all runnable cells") for call in calls
    )
    assert not any(call[0] == "error" for call in calls), calls
    assert len(downloads) == 1
    label, recovery = downloads[0]
    assert label == "Download previous notebook import"
    assert recovery["file_name"].startswith("notebook_import_before_update_")
    assert recovery["mime"] == "application/json"
    assert recovery["data"] == (case.project / recovery["file_name"]).read_bytes()
    assert "idx__notebook_import_preview" not in case.ui.session_state

    _build(case, _document())
    before_cancel = _tree(case.project)
    click["label"] = "Cancel import"
    pipeline_editor.render_notebook_import_preview(
        case.project, case.stages_file, "idx", container=target
    )
    assert len(forwarded) == 1
    assert _tree(case.project) == before_cancel
    assert "idx__notebook_import_preview" not in case.ui.session_state
    assert downloads[-1] == (label, recovery)
    pipeline_editor.render_notebook_import_preview(
        case.project, case.stages_file, "idx", container=target
    )
    assert downloads[-1] == (label, recovery)
    assert len(downloads) == 3


def test_update_ignores_empty_code_cells_without_inventing_source_identity(
    imported_project,
):
    case = imported_project
    document = _document()
    document["cells"].insert(
        2, {"cell_type": "code", "source": ["  ", "\n"], "metadata": {}}
    )
    preview = _build(case, document)
    before = _tree(case.project)

    reviewed = _review(case, preview)

    assert reviewed["update_plan"]["cell_changes"] == {
        "added": [],
        "changed": [],
        "removed": [],
        "moved": [],
        "unchanged": ["seed", "mutate", "result"],
    }
    assert _tree(case.project) == before


@pytest.mark.parametrize(
    ("invalid", "message"),
    [
        ("previous_supervisor", "supervisor round-trip"),
        ("incoming_supervisor", "supervisor round-trip"),
        ("multiple_incoming", "all runnable cells"),
        ("invalid_incoming", "all runnable cells"),
        ("missing_current", "no existing notebook stage"),
        ("previous_strategy", "shared-state notebook stage"),
        ("incoming_strategy", "shared-state notebook stage"),
        ("incoming_source", "incoming stage names a different"),
        ("no_runnable_cells", "runnable code cells"),
    ],
)
def test_update_planner_refuses_unsafe_stage_replacements(
    imported_project, invalid, message
):
    from agilab.notebooks.notebook_import_update import (
        canonical_json,
        plan_notebook_import_update,
        sha256,
    )

    case = imported_project
    preview = _build(case)
    prepared = pipeline_editor.prepare_notebook_import_preview(
        preview, runtime_roles=_roles(preview), preserve_notebook_state=True
    )
    current = tomllib.loads(case.stages_file.read_text())
    incoming = prepared["toml_content"]
    previous = json.loads((case.project / "notebook_import_contract.json").read_text())
    notebook_import = prepared["notebook_import"]
    if invalid == "previous_supervisor":
        previous["source"]["import_mode"] = "agilab_supervisor_metadata"
    elif invalid == "incoming_supervisor":
        notebook_import["source"]["import_mode"] = "agilab_supervisor_metadata"
    elif invalid == "multiple_incoming":
        incoming["demo"].append(copy.deepcopy(incoming["demo"][0]))
    elif invalid == "invalid_incoming":
        incoming["demo"] = ["unverified stage"]
    elif invalid == "missing_current":
        current["demo"] = None
    elif invalid == "previous_strategy":
        current["demo"][0]["NB_EXECUTION_STRATEGY"] = "isolated"
    elif invalid == "incoming_strategy":
        incoming["demo"][0]["NB_EXECUTION_STRATEGY"] = "isolated"
    elif invalid == "incoming_source":
        incoming["demo"][0]["NB_SOURCE_NOTEBOOK"] = "another-source.ipynb"
    else:
        record = previous["notebook_document"]
        record["notebook"]["cells"] = [
            cell
            for cell in record["notebook"]["cells"]
            if cell["cell_type"] == "markdown"
        ]
        record["sha256"] = sha256(canonical_json(record["notebook"]))
    before = _tree(case.project)

    with pytest.raises(ValueError, match=message):
        plan_notebook_import_update(
            current,
            incoming,
            notebook_import=notebook_import,
            previous_contract=previous,
            module_name="demo",
        )

    assert _tree(case.project) == before


@pytest.mark.parametrize(
    "linked",
    [
        "import_directory",
        "lab_stages.toml",
        "notebook_import_contract.json",
        "notebook_import_pipeline_view.json",
        "notebook_import_view_plan.json",
    ],
)
def test_update_target_snapshot_refuses_symbolic_links(tmp_path, linked):
    from agilab.notebooks.notebook_import_update import read_import_targets

    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "authored-project-data"
    external.mkdir()
    protected = external / "lab_stages.toml"
    protected.write_bytes(b"preserve this authored workflow")
    if linked == "import_directory":
        linked_directory = tmp_path / "linked-project"
        linked_directory.symlink_to(external, target_is_directory=True)
        stages_file = linked_directory / "lab_stages.toml"
    else:
        (project / linked).symlink_to(protected)
        stages_file = project / "lab_stages.toml"
    before = _tree(tmp_path)

    with pytest.raises(ValueError, match="regular lab_stages|symbolic link"):
        read_import_targets(stages_file)

    assert protected.read_bytes() == b"preserve this authored workflow"
    assert _tree(tmp_path) == before


def test_update_target_snapshot_requires_the_established_stages_filename(tmp_path):
    from agilab.notebooks.notebook_import_update import read_import_targets

    alternate = tmp_path / "different-workflow.toml"
    alternate.write_bytes(b"not an import target")
    before = _tree(tmp_path)

    with pytest.raises(ValueError, match="regular lab_stages.toml"):
        read_import_targets(alternate)

    assert _tree(tmp_path) == before


def test_recovery_round_trip_preserves_missing_targets_and_reuses_identical_bundle(
    tmp_path,
):
    from agilab.notebooks.notebook_import_update import (
        read_import_targets,
        verify_update_backup,
        write_update_backup,
    )

    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_bytes(b'[demo]\nname = "authored workflow"\n')
    targets = read_import_targets(stages_file)
    assert targets["notebook_import_contract.json"] is None
    backup = write_update_backup(
        stages_file, targets, review_signature="reviewed-source"
    )
    before = _tree(tmp_path)

    assert verify_update_backup(backup) == targets
    assert (
        write_update_backup(stages_file, targets, review_signature="reviewed-source")
        == backup
    )
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("collision", ["different_content", "symbolic_link"])
def test_recovery_writer_never_overwrites_a_conflicting_existing_bundle(
    tmp_path, collision
):
    from agilab.notebooks.notebook_import_update import (
        read_import_targets,
        write_update_backup,
    )

    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_bytes(b"authored workflow bytes")
    targets = read_import_targets(stages_file)
    backup = write_update_backup(
        stages_file, targets, review_signature="reviewed-source"
    )
    external = tmp_path / "unrelated-author-data"
    external.write_bytes(b"retain exact unrelated bytes")
    if collision == "different_content":
        backup.write_bytes(b"retain unexpected existing recovery content")
    else:
        backup.unlink()
        backup.symlink_to(external)
    before = _tree(tmp_path)

    with pytest.raises(ValueError, match="different content|symbolic link"):
        write_update_backup(stages_file, targets, review_signature="reviewed-source")

    assert _tree(tmp_path) == before
    assert external.read_bytes() == b"retain exact unrelated bytes"


@pytest.mark.parametrize(
    ("invalid", "message"),
    [
        ("bundle_type", "bundle schema"),
        ("schema", "bundle schema"),
        ("record_type", "target status"),
        ("status", "target status"),
        ("missing_base64", "recovery bytes"),
        ("invalid_base64", "recovery bytes"),
        ("non_string_base64", "recovery bytes"),
        ("absent_with_bytes", "absent recovery target"),
    ],
)
def test_recovery_verifier_refuses_malformed_downloads_without_writing(
    tmp_path, invalid, message
):
    from agilab.notebooks.notebook_import_update import (
        read_import_targets,
        verify_update_backup,
        write_update_backup,
    )

    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_bytes(b"authored workflow bytes")
    backup = write_update_backup(
        stages_file,
        read_import_targets(stages_file),
        review_signature="reviewed-source",
    )
    bundle = json.loads(backup.read_bytes())
    if invalid == "bundle_type":
        bundle = []
    elif invalid == "schema":
        bundle["schema"] = "another.recovery.schema"
    elif invalid == "record_type":
        bundle["targets"]["lab_stages.toml"] = []
    elif invalid == "status":
        bundle["targets"]["lab_stages.toml"]["status"] = "unknown"
    elif invalid == "missing_base64":
        bundle["targets"]["lab_stages.toml"].pop("base64")
    elif invalid == "invalid_base64":
        bundle["targets"]["lab_stages.toml"]["base64"] = "not-base64!"
    elif invalid == "non_string_base64":
        bundle["targets"]["lab_stages.toml"]["base64"] = 123
    else:
        bundle["targets"]["notebook_import_contract.json"]["base64"] = ""
    downloaded = tmp_path / "malformed-notebook-import-recovery.json"
    downloaded.write_text(json.dumps(bundle))
    before = _tree(tmp_path)

    with pytest.raises(ValueError, match=message):
        verify_update_backup(downloaded)

    assert _tree(tmp_path) == before


def test_recovery_verifier_refuses_a_symbolic_link_download(tmp_path):
    from agilab.notebooks.notebook_import_update import verify_update_backup

    authored = tmp_path / "authored-data.json"
    authored.write_bytes(b"unrelated authored bytes")
    downloaded = tmp_path / "linked-notebook-import-recovery.json"
    downloaded.symlink_to(authored)
    before = _tree(tmp_path)

    with pytest.raises(ValueError, match="symbolic link"):
        verify_update_backup(downloaded)

    assert _tree(tmp_path) == before
