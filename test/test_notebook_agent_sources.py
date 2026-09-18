import json

import pytest

from agilab.agent_runtime import notebook_agent as agent
from agilab.agent_runtime import notebook_execution_verifier as verifier


def _notebook(source="import streamlit as st\nfrom pathlib import Path\nimport json\nPath('results.json').write_text(json.dumps({'results': {'answer': 42}}))\nst.metric('answer', 42)\n"):
    return {"nbformat": 4, "metadata": {"kernelspec": {"language": "python"}},
            "cells": [{"cell_type": "code", "source": source}]}


def _project(tmp_path, source=None):
    project = tmp_path / "project"
    project.mkdir()
    notebook = _notebook() if source is None else source
    (project / "solution.ipynb").write_text(json.dumps(notebook))
    (project / "app.py").write_text("import streamlit as st\nfrom pathlib import Path\nimport json\nrunning = st.button('Run analysis')\nif running:\n    Path('results.json').write_text(json.dumps({'results': {'answer': 43}}))\nst.metric('answer', 43 if running else 42)\n")
    (project / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.0"\n')
    return project


def test_local_source_snapshot_is_copied_and_tampering_is_detectable(tmp_path):
    notebook = tmp_path / "input.ipynb"
    marker = tmp_path / "must-not-execute"
    notebook.write_text(json.dumps(_notebook(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")))
    project = tmp_path / "project"
    project.mkdir()
    provenance = agent.fetch_source(project, notebook=notebook)
    snapshot = project / "source" / "original.ipynb"
    assert snapshot.read_text() == notebook.read_text()
    assert provenance["source_kind"] == "local"
    assert not marker.exists()
    notebook.write_text("tampered")
    assert agent.digest(snapshot) != agent.digest(notebook)


@pytest.mark.parametrize("url", [
    "http://github.com/a/b/blob/" + "a" * 40 + "/x.ipynb",
    "https://gitlab.com/a/b/blob/" + "a" * 40 + "/x.ipynb",
    "https://github.com/a/b/blob/main/x.ipynb",
    "https://github.com/a/b/blob/" + "a" * 40 + "/x.ipynb?download=1",
    "https://github.com/a/b/blob/" + "a" * 40 + "/x.txt",
])
def test_pinned_url_rejects_floating_hosts_queries_and_non_notebooks(url):
    with pytest.raises(ValueError):
        agent.pinned_notebook_url(url)


def test_download_rejects_redirect_and_oversize(monkeypatch):
    class Response:
        status_code = 302
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, _size): return [b"x"]
    monkeypatch.setattr("requests.get", lambda *a, **kw: Response())
    with pytest.raises(ValueError, match="HTTP 200"):
        agent._download_source("https://raw.githubusercontent.com/x")

    class Large(Response):
        status_code = 200
        def iter_content(self, _size): return [b"x" * (agent.MAX_SOURCE_BYTES + 1)]
    monkeypatch.setattr("requests.get", lambda *a, **kw: Large())
    with pytest.raises(ValueError, match="16 MiB"):
        agent._download_source("https://raw.githubusercontent.com/x")


def test_generic_verifier_runs_app_and_reports_visible_result(tmp_path):
    project = _project(tmp_path)
    report = verifier.verify(project)
    assert report["status"] == "passed"
    assert report["scientific_correctness_verified"] is False
    assert report["verification_scope"] == "execution_and_interface"
    assert report["result_names"] == ["answer"]


def test_generic_verifier_rejects_results_left_in_project(tmp_path):
    project = _project(tmp_path, _notebook("pass\n"))
    (project / "results.json").write_text('{"results": {"stale": 42}}')
    with pytest.raises(ValueError, match="fresh results.json"):
        verifier.verify(project)


def test_verifier_rejects_app_without_new_visible_result(tmp_path):
    project = _project(tmp_path)
    (project / "app.py").write_text("import streamlit as st\nst.button('Run analysis')\nst.write('hello')\n")
    with pytest.raises(ValueError, match="visible"):
        verifier.verify(project)
