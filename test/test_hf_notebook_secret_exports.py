"""Notebook content is inspected before any Hugging Face export mutation."""

from __future__ import annotations

import json

import pytest

from agilab import bridge_cli


def _notebook(source, metadata=None):
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": metadata or {},
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": source,
            }
        ],
    }


@pytest.mark.parametrize(
    "placement", ["project", "evidence-file", "evidence-directory"]
)
@pytest.mark.parametrize(
    "kind", ["source", "split-source", "metadata", "uri", "escaped-key"]
)
def test_notebook_credentials_refused_before_export_mutation(tmp_path, placement, kind):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("print('safe')\n", encoding="utf-8")
    sentinel = "audit-dummy-nonproduction-0123456789"
    source = "print('safe')"
    metadata = {}
    if kind == "source":
        source = f'OPENAI_API_KEY = "{sentinel}"'
    elif kind == "split-source":
        source = ["OPENAI_", "API_KEY", " = ", f'"{sentinel}"']
    elif kind == "metadata":
        metadata = {"credentials": {"password": sentinel}}
    elif kind == "uri":
        source = "secret://audit-private-reference"
    else:
        metadata = {f'API_KEY = "{sentinel}"': ""}
    if placement == "project":
        notebook = project / "analysis.IPYNB"
        evidence = None
    else:
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        notebook = evidence_dir / "analysis.ipynb"
        evidence = notebook if placement == "evidence-file" else evidence_dir
    notebook.write_text(json.dumps(_notebook(source, metadata)), encoding="utf-8")
    original = notebook.read_bytes()
    output = tmp_path / "export"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_bytes(b"existing evidence")
    with pytest.raises(RuntimeError, match="secret-like") as exc:
        bridge_cli.export_hf_space(project, output, evidence_path=evidence, force=True)
    assert sentinel not in str(exc.value)
    assert notebook.read_bytes() == original
    assert list(output.iterdir()) == [marker]
    assert marker.read_bytes() == b"existing evidence"


@pytest.mark.parametrize("payload", [b"not-json", b"\xff", b'{"cells":[],"cells":[]}'])
def test_invalid_notebook_refused_without_output_or_content_echo(tmp_path, payload):
    project = tmp_path / "project"
    project.mkdir()
    (project / "analysis.ipynb").write_bytes(payload)
    output = tmp_path / "export"
    with pytest.raises(RuntimeError, match="secret-like") as exc:
        bridge_cli.export_hf_space(project, output)
    assert "not-json" not in str(exc.value)
    assert not output.exists()


@pytest.mark.parametrize(
    "source",
    ['print("safe")', 'API_KEY = "changeme"', ["API_", "KEY = ", '"<redacted>"']],
)
def test_safe_notebooks_and_placeholders_still_export(tmp_path, source):
    project = tmp_path / "project"
    project.mkdir()
    notebook = project / "analysis.ipynb"
    notebook.write_text(
        json.dumps(_notebook(source, {"password": "<redacted>"})), encoding="utf-8"
    )
    original = notebook.read_bytes()
    output = tmp_path / "export"
    result = bridge_cli.export_hf_space(project, output)
    assert result["status"] == "pass"
    assert (output / "agilab_project" / "analysis.ipynb").read_bytes() == original


@pytest.mark.parametrize("placement", ["project", "evidence-file", "evidence-directory"])
@pytest.mark.parametrize("kind", ["stream", "text/plain", "application/javascript", "image/svg+xml"])
def test_split_notebook_output_credentials_are_refused(tmp_path, placement, kind):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("pass\n", encoding="utf-8")
    sentinel = "audit-dummy-output-0123456789"
    payload = _notebook("print('safe')")
    pieces = ["OPENAI_API_", "KEY = ", f'"{sentinel}"']
    output = (
        {"output_type": "stream", "name": "stdout", "text": pieces}
        if kind == "stream" else
        {"output_type": "display_data", "metadata": {}, "data": {kind: pieces}}
    )
    payload["cells"][0]["outputs"] = [output]
    folder = project if placement == "project" else tmp_path / "evidence"
    folder.mkdir(exist_ok=True)
    notebook = folder / "analysis.ipynb"
    notebook.write_text(json.dumps(payload), encoding="utf-8")
    before = notebook.read_bytes()
    evidence = None if placement == "project" else notebook if placement == "evidence-file" else folder
    target = tmp_path / "export"
    with pytest.raises(RuntimeError, match="secret-like") as exc:
        bridge_cli.export_hf_space(project, target, evidence_path=evidence)
    assert sentinel not in str(exc.value)
    assert notebook.read_bytes() == before
    assert not target.exists()


@pytest.mark.parametrize("kind", ["stream", "text/plain", "application/javascript", "image/svg+xml"])
def test_split_notebook_output_placeholders_still_export(tmp_path, kind):
    project = tmp_path / "project"
    project.mkdir()
    payload = _notebook("pass")
    pieces = ["API_", "KEY = ", '"<redacted>"']
    payload["cells"][0]["outputs"] = [
        {"output_type": "stream", "name": "stdout", "text": pieces}
        if kind == "stream" else
        {"output_type": "display_data", "metadata": {}, "data": {kind: pieces}}
    ]
    notebook = project / "analysis.ipynb"
    notebook.write_text(json.dumps(payload), encoding="utf-8")
    before = notebook.read_bytes()
    target = tmp_path / "export"
    assert bridge_cli.export_hf_space(project, target)["status"] == "pass"
    assert (target / "agilab_project" / notebook.name).read_bytes() == before
