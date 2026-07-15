from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import tomllib

from agilab.notebooks.notebook_export_support import (
    NotebookExportContext,
    build_notebook_document,
)
from test import import_agilab_module


pipeline_editor = import_agilab_module("agilab.pipeline.pipeline_editor")


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def _uploaded_notebook(code: str = "print('imported')\n") -> SimpleNamespace:
    payload = {
        "cells": [
            {
                "cell_type": "code",
                "metadata": {"agilab": {"runtime_role": "manager"}},
                "source": [code],
            }
        ]
    }
    return SimpleNamespace(
        name="imported.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(payload).encode("utf-8"),
    )


def _quiet_streamlit(session_state=None) -> SimpleNamespace:
    return SimpleNamespace(
        session_state=session_state if session_state is not None else _State(),
        error=lambda *_args, **_kwargs: None,
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        success=lambda *_args, **_kwargs: None,
    )


def _mark_same_origin_supervisor(preview: dict, module: str = "demo_project") -> None:
    preview["target_project_name"] = "demo_project"
    preview["notebook_import"]["source"].update(
        {
            "import_mode": "agilab_supervisor_metadata",
            "project_name": "demo_project",
        }
    )
    for stage in preview["notebook_import"]["pipeline_stages"]:
        stage["source_module"] = module


def test_notebook_import_default_merge_preserves_existing_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    stages_file = module_dir / "lab_stages.toml"
    stages_file.write_text(
        """
[__meta__]
schema = "agilab.lab_stages.v1"
version = 1
other_project__sequence = [0]
demo_project__sequence = [1, 0]

[[other_project]]
id = "other-stage"
Q = "Other module"
C = "print('other')"

[[demo_project]]
id = "existing-stage"
Q = "Existing stage"
C = "print('existing')"

[[demo_project]]
id = "unrelated-stage"
Q = "Unrelated stage"
C = "print('unrelated')"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    before = tomllib.loads(stages_file.read_text(encoding="utf-8"))

    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook(),
        module_dir,
        stages_file=stages_file,
    )
    assert preview is not None
    assert "target_stages_signature" in preview
    preview["toml_content"]["demo_project"][0].pop("id", None)

    count = pipeline_editor.write_notebook_import_preview(preview, module_dir, stages_file)

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert count == 1
    assert stored["__meta__"] == {
        **before["__meta__"],
        "demo_project__sequence": [1, 0, 2],
    }
    assert stored["other_project"] == before["other_project"]
    assert stored["demo_project"][:2] == before["demo_project"]
    assert len(stored["demo_project"]) == 3
    assert stored["demo_project"][2]["C"] == "print('imported')\n"


def test_notebook_import_preview_uses_active_workflow_module_key(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"

    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook(),
        module_dir,
        module_name="stages",
    )

    assert preview is not None
    assert preview["module"] == "stages"
    assert list(preview["toml_content"]) == ["stages"]


def test_notebook_import_merge_upserts_explicit_id_in_same_module(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    stages_file = module_dir / "lab_stages.toml"
    stages_file.write_text(
        """
[[other_project]]
id = "stable-stage"
Q = "Same id in another module"
C = "print('other-old')"

[[demo_project]]
id = "stable-stage"
Q = "Replace me"
C = "print('old')"

[[demo_project]]
id = "keep-stage"
Q = "Keep me"
C = "print('keep')"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook("print('new')\n"),
        module_dir,
        stages_file=stages_file,
    )
    assert preview is not None
    imported_stage = preview["toml_content"]["demo_project"][0]
    imported_stage["id"] = "stable-stage"
    imported_stage["Q"] = "Updated from notebook"
    _mark_same_origin_supervisor(preview)

    pipeline_editor.write_notebook_import_preview(preview, module_dir, stages_file)

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    matching = [stage for stage in stored["demo_project"] if stage.get("id") == "stable-stage"]
    assert len(matching) == 1
    assert matching[0]["Q"] == "Updated from notebook"
    assert matching[0]["C"] == "print('new')\n"
    assert [stage["id"] for stage in stored["demo_project"]] == [
        "stable-stage",
        "keep-stage",
    ]
    assert stored["other_project"][0]["C"] == "print('other-old')"


def test_notebook_import_merge_rejects_cross_project_id_collision(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    stages_file = module_dir / "lab_stages.toml"
    stages_file.write_text(
        '[[demo_project]]\nid = "train"\nC = "print(\'current\')"\n',
        encoding="utf-8",
    )
    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook("print('foreign')\n"),
        module_dir,
        stages_file=stages_file,
    )
    assert preview is not None
    preview["toml_content"]["demo_project"][0]["id"] = "train"

    with pytest.raises(ValueError, match="collides.*same-project supervisor"):
        pipeline_editor.write_notebook_import_preview(preview, module_dir, stages_file)

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert stored["demo_project"] == [{"id": "train", "C": "print('current')"}]


def test_notebook_import_merge_matches_existing_stage_id_alias(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    stages_file = module_dir / "lab_stages.toml"
    stages_file.write_text(
        '[[demo_project]]\nstage_id = "train"\nC = "print(\'old\')"\n',
        encoding="utf-8",
    )
    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook("print('new')\n"),
        module_dir,
        stages_file=stages_file,
    )
    assert preview is not None
    preview["toml_content"]["demo_project"][0]["id"] = "train"
    _mark_same_origin_supervisor(preview)

    pipeline_editor.write_notebook_import_preview(preview, module_dir, stages_file)

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert len(stored["demo_project"]) == 1
    assert stored["demo_project"][0]["stage_id"] == "train"
    assert stored["demo_project"][0]["id"] == "train"
    assert stored["demo_project"][0]["C"] == "print('new')\n"


def test_same_origin_roundtrip_positionally_updates_idless_stages(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    stages_file = module_dir / "lab_stages.toml"
    stages_file.write_text(
        """
[[demo_project]]
Q = "First legacy stage"
C = "print('first-old')"

[[demo_project]]
Q = "Second legacy stage"
C = "print('second')"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    notebook = build_notebook_document(
        tomllib.loads(stages_file.read_text(encoding="utf-8")),
        stages_file,
        export_context=NotebookExportContext(
            project_name="demo_project",
            module_path="demo_project",
            artifact_dir=str(module_dir),
        ),
    )
    first_source_cell = next(
        cell
        for cell in notebook["cells"]
        if cell.get("metadata", {})
        .get("agilab", {})
        .get("stage_cell", {})
        .get("kind")
        == "source"
        and cell["metadata"]["agilab"]["stage_cell"]["module_index"] == 0
    )
    first_source_cell["source"] = [
        "STAGE_000_CODE = \"print('first-edited')\\n\"\n",
        "print(STAGE_000_CODE)\n",
    ]
    uploaded = SimpleNamespace(
        name="lab_stages.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(notebook).encode("utf-8"),
    )

    preview = pipeline_editor.build_notebook_import_preview(
        uploaded,
        module_dir,
        stages_file=stages_file,
        module_name="demo_project",
        target_project_name="demo_project",
    )
    assert preview is not None
    assert preview["toml_content"]["demo_project"][0]["NB_SOURCE_MODULE_INDEX"] == 0
    assert preview["toml_content"]["demo_project"][0][
        "NB_SOURCE_STAGE_FINGERPRINT"
    ]

    pipeline_editor.write_notebook_import_preview(preview, module_dir, stages_file)

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert len(stored["demo_project"]) == 2
    assert stored["demo_project"][0]["C"] == "print('first-edited')\n"
    assert stored["demo_project"][1]["C"] == "print('second')"


def test_same_origin_idless_roundtrip_rejects_shifted_stage_identity(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    stages_file = module_dir / "lab_stages.toml"
    original = {
        "demo_project": [
            {"Q": "Stage A", "C": "print('A')"},
            {"Q": "Stage B", "C": "print('B')"},
        ]
    }
    notebook = build_notebook_document(
        original,
        stages_file,
        export_context=NotebookExportContext(
            project_name="demo_project",
            module_path="demo_project",
            artifact_dir=str(module_dir),
        ),
    )
    stages_file.write_text(
        '[[demo_project]]\nQ = "Stage B"\nC = "print(\'B\')"\n',
        encoding="utf-8",
    )
    uploaded = SimpleNamespace(
        name="stale-lab-stages.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(notebook).encode("utf-8"),
    )
    preview = pipeline_editor.build_notebook_import_preview(
        uploaded,
        module_dir,
        stages_file=stages_file,
        module_name="demo_project",
        target_project_name="demo_project",
    )
    assert preview is not None
    before = stages_file.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="no longer matches.*stage identity"):
        pipeline_editor.write_notebook_import_preview(
            preview,
            module_dir,
            stages_file,
        )

    assert stages_file.read_text(encoding="utf-8") == before


def test_notebook_import_replace_mode_replaces_project_scaffold(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    stages_file = module_dir / "lab_stages.toml"
    stages_file.write_text(
        """
[[demo_project]]
id = "scaffold-stage"
Q = "Template scaffold"
C = "print('scaffold')"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook(),
        module_dir,
        stages_file=stages_file,
    )
    assert preview is not None

    pipeline_editor.write_notebook_import_preview(
        preview,
        module_dir,
        stages_file,
        write_mode="replace",
    )

    stored = tomllib.loads(stages_file.read_text(encoding="utf-8"))
    assert len(stored["demo_project"]) == 1
    assert stored["demo_project"][0]["C"] == "print('imported')\n"
    assert all(stage.get("id") != "scaffold-stage" for stage in stored["demo_project"])


def test_notebook_import_rejects_selected_stage_with_missing_dependency(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook("print('summary')\n"),
        module_dir,
    )
    assert preview is not None
    imported_stage = preview["toml_content"]["demo_project"][0]
    imported_stage["id"] = "summarize"
    imported_stage["depends_on"] = ["prepare"]

    with pytest.raises(ValueError, match="depends on missing stage.*prepare"):
        pipeline_editor.write_notebook_import_preview(
            preview,
            module_dir,
            module_dir / "lab_stages.toml",
        )

    assert not (module_dir / "lab_stages.toml").exists()


@pytest.mark.parametrize(
    "stages, message",
    [
        (
            [
                {"id": "duplicate", "C": "print(1)"},
                {"id": "duplicate", "C": "print(2)"},
            ],
            "Duplicate workflow stage ID",
        ),
        (
            [{"id": "self", "depends_on": ["self"], "C": "print(1)"}],
            "cycle or self-dependency",
        ),
        (
            [
                {"id": "left", "depends_on": ["right"], "C": "print(1)"},
                {"id": "right", "depends_on": ["left"], "C": "print(2)"},
            ],
            "cycle or self-dependency",
        ),
    ],
)
def test_notebook_import_replace_rejects_invalid_stage_graph(
    monkeypatch, tmp_path, stages, message
):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook(),
        module_dir,
    )
    assert preview is not None
    preview["toml_content"] = {"demo_project": stages}

    with pytest.raises(ValueError, match=message):
        pipeline_editor.write_notebook_import_preview(
            preview,
            module_dir,
            module_dir / "lab_stages.toml",
            write_mode="replace",
        )

    assert not (module_dir / "lab_stages.toml").exists()


def test_notebook_import_write_rejects_stale_target_signature(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_editor, "st", _quiet_streamlit())
    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    stages_file = module_dir / "lab_stages.toml"
    stages_file.write_text(
        '[[demo_project]]\nQ = "Previewed"\nC = "print(1)"\n',
        encoding="utf-8",
    )
    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook(),
        module_dir,
        stages_file=stages_file,
    )
    assert preview is not None

    externally_edited = '[[demo_project]]\nQ = "External edit"\nC = "print(2)"\n'
    stages_file.write_text(externally_edited, encoding="utf-8")

    with pytest.raises(ValueError, match="changed (?:after|since).*preview|stale"):
        pipeline_editor.write_notebook_import_preview(preview, module_dir, stages_file)

    assert stages_file.read_text(encoding="utf-8") == externally_edited
    assert not (module_dir / "notebook_import_contract.json").exists()
    assert not (module_dir / "notebook_import_pipeline_view.json").exists()
    assert not (module_dir / "notebook_import_view_plan.json").exists()


def test_notebook_import_confirmation_rejects_stale_target_without_dirtying_page(
    monkeypatch, tmp_path
):
    messages: list[tuple[str, str]] = []
    state = _State({"idx": [0, "", "", "", "", "", 1]})
    fake_st = _quiet_streamlit(state)
    fake_st.error = lambda message, *_args, **_kwargs: messages.append(("error", message))
    monkeypatch.setattr(pipeline_editor, "st", fake_st)
    monkeypatch.setattr(
        pipeline_editor,
        "_bump_history_revision",
        lambda: pytest.fail("stale import must not update history"),
    )
    module_dir = tmp_path / "demo_project"
    module_dir.mkdir()
    stages_file = module_dir / "lab_stages.toml"
    stages_file.write_text(
        '[[demo_project]]\nQ = "Previewed"\nC = "print(1)"\n',
        encoding="utf-8",
    )
    preview = pipeline_editor.build_notebook_import_preview(
        _uploaded_notebook(),
        module_dir,
        stages_file=stages_file,
    )
    assert preview is not None
    state["idx__notebook_import_preview"] = preview

    externally_edited = '[[demo_project]]\nQ = "External edit"\nC = "print(2)"\n'
    stages_file.write_text(externally_edited, encoding="utf-8")

    count = pipeline_editor.confirm_notebook_import_preview(module_dir, stages_file, "idx")

    assert count == 0
    assert stages_file.read_text(encoding="utf-8") == externally_edited
    assert "idx__notebook_import_preview" in state
    assert "page_broken" not in state
    assert state["idx"][-1] == 1
    assert any(
        "changed after" in message or "changed since" in message or "stale" in message
        for _level, message in messages
    )
