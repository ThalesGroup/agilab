from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agilab.notebooks.notebook_export_support import NotebookExportContext
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


def _streamlit_messages() -> tuple[SimpleNamespace, list[tuple[str, str]]]:
    messages: list[tuple[str, str]] = []
    streamlit = SimpleNamespace(
        session_state=_State(),
        error=lambda message, *_args, **_kwargs: messages.append(("error", message)),
        warning=lambda message, *_args, **_kwargs: messages.append(("warning", message)),
    )
    return streamlit, messages


def _edit_exported_source(path: Path) -> str:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    source_cell = next(
        cell
        for cell in notebook["cells"]
        if cell.get("metadata", {}).get("agilab", {}).get("stage_cell", {}).get("kind")
        == "source"
    )
    edited_source = "STAGE_000_CODE = \"print('edited notebook')\\n\"\nprint(STAGE_000_CODE)\n"
    source_cell["source"] = edited_source.splitlines(keepends=True)
    path.write_text(json.dumps(notebook, indent=2) + "\n", encoding="utf-8")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("edited_export", ["primary", "pycharm_mirror"])
def test_notebook_export_refresh_preserves_edited_notebook(
    monkeypatch,
    tmp_path: Path,
    edited_export: str,
) -> None:
    streamlit, messages = _streamlit_messages()
    monkeypatch.setattr(pipeline_editor, "st", streamlit)
    stages_file = tmp_path / "lab_stages.toml"
    mirror_path = tmp_path / "mirror" / "lab_stages.ipynb"
    monkeypatch.setattr(
        pipeline_editor,
        "resolve_pycharm_notebook_path",
        lambda *_args, **_kwargs: mirror_path,
    )
    context = NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(tmp_path / "artifacts"),
    )
    original = {"demo_project": [{"C": "print('original')\n", "R": "runpy"}]}
    refreshed = {"demo_project": [{"C": "print('from stages')\n", "R": "runpy"}]}

    notebook_path = pipeline_editor.toml_to_notebook(
        original,
        stages_file,
        export_context=context,
    )
    assert notebook_path == stages_file.with_suffix(".ipynb")
    edit_target = notebook_path if edited_export == "primary" else mirror_path
    edited_text = _edit_exported_source(edit_target)
    primary_before_refresh = notebook_path.read_text(encoding="utf-8")

    result = pipeline_editor.toml_to_notebook(
        refreshed,
        stages_file,
        export_context=context,
    )

    assert result == notebook_path
    assert edit_target.read_text(encoding="utf-8") == edited_text
    assert notebook_path.read_text(encoding="utf-8") == primary_before_refresh
    assert any(
        level == "warning" and "Preserved edited notebook export" in message
        for level, message in messages
    )


def test_refresh_notebook_export_returns_none_when_write_fails(monkeypatch, tmp_path: Path) -> None:
    streamlit, messages = _streamlit_messages()
    monkeypatch.setattr(pipeline_editor, "st", streamlit)
    monkeypatch.setattr(
        pipeline_editor,
        "resolve_pycharm_notebook_path",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline_editor,
        "_write_notebook_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        '[[demo_project]]\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    result = pipeline_editor.refresh_notebook_export(stages_file)

    assert result is None
    assert not stages_file.with_suffix(".ipynb").exists()
    assert messages == [("error", "Failed to save notebook: disk full")]


def test_notebook_export_refresh_preserves_malformed_notebook_as_unverified(
    monkeypatch,
    tmp_path: Path,
) -> None:
    streamlit, messages = _streamlit_messages()
    monkeypatch.setattr(pipeline_editor, "st", streamlit)
    monkeypatch.setattr(
        pipeline_editor,
        "resolve_pycharm_notebook_path",
        lambda *_args, **_kwargs: None,
    )
    stages_file = tmp_path / "lab_stages.toml"
    context = NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(tmp_path / "artifacts"),
    )
    notebook_path = pipeline_editor.toml_to_notebook(
        {"demo_project": [{"C": "print('original')\n"}]},
        stages_file,
        export_context=context,
    )
    assert notebook_path is not None
    malformed = "{ edited notebook JSON is incomplete"
    notebook_path.write_text(malformed, encoding="utf-8")

    result = pipeline_editor.toml_to_notebook(
        {"demo_project": [{"C": "print('from stages')\n"}]},
        stages_file,
        export_context=context,
    )

    assert result == notebook_path
    assert notebook_path.read_text(encoding="utf-8") == malformed
    assert any(
        level == "warning"
        and "Preserved edited notebook export" in message
        and "unverified" in message
        for level, message in messages
    )


def test_explicit_regeneration_can_replace_edited_export(
    monkeypatch,
    tmp_path: Path,
) -> None:
    streamlit, _messages = _streamlit_messages()
    monkeypatch.setattr(pipeline_editor, "st", streamlit)
    monkeypatch.setattr(
        pipeline_editor,
        "resolve_pycharm_notebook_path",
        lambda *_args, **_kwargs: None,
    )
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text(
        '[[demo_project]]\nC = "print(\'original\')\\n"\nR = "runpy"\n',
        encoding="utf-8",
    )
    context = NotebookExportContext(
        project_name="demo_project",
        module_path="demo_project",
        artifact_dir=str(tmp_path / "artifacts"),
    )
    notebook_path = pipeline_editor.refresh_notebook_export(
        stages_file,
        export_context=context,
    )
    assert notebook_path is not None
    edited_text = _edit_exported_source(notebook_path)

    stages_file.write_text(
        '[[demo_project]]\nC = "print(\'reimported\')\\n"\nR = "runpy"\n',
        encoding="utf-8",
    )
    result = pipeline_editor.refresh_notebook_export(
        stages_file,
        export_context=context,
        force=True,
    )

    assert result == notebook_path
    assert notebook_path.read_text(encoding="utf-8") != edited_text
    assert "reimported" in notebook_path.read_text(encoding="utf-8")


def test_workflow_export_overwrite_requires_explicit_confirmation() -> None:
    workflow_source = (
        Path(pipeline_editor.__file__).resolve().parents[1] / "pages" / "3_WORKFLOW.py"
    ).read_text(encoding="utf-8")

    assert "Confirm replacement of edited notebook exports" in workflow_source
    assert '"Overwrite notebook exports from current stages"' in workflow_source
    assert "disabled=not overwrite_confirmed" in workflow_source
