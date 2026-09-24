"""Fresh notebook and persisted workflow acceptance contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from agilab.agent_runtime import notebook_verifier, notebook_workflow_verifier


def _workflow(project, source, **stage):
    import toml
    (project / "lab_stages.toml").write_text(
        toml.dumps({"demo": [{"C": source, **stage}]}), encoding="utf-8")


def _verify_workflow(project):
    return notebook_workflow_verifier.verify(
        project, module="demo", result_file="results.json",
        expected_sha256=notebook_workflow_verifier.result_digest({"value": 7}))


def test_workflow_verification_binds_fresh_result_and_source_and_restores_process(tmp_path):
    _workflow(tmp_path, "import json\nfrom pathlib import Path\nPath('results.json').write_text(json.dumps({'value':7}))")
    source = (tmp_path / "lab_stages.toml").read_bytes()
    cwd, path = Path.cwd(), sys.path[:]
    report = _verify_workflow(tmp_path)
    assert report["status"] == "passed"
    assert report["stage_count"] == 1
    assert report["stages_sha256"] == hashlib.sha256(source).hexdigest()
    assert report["scientific_correctness_verified"] is False
    assert Path.cwd() == cwd and sys.path == path
    assert not (tmp_path / "results.json").exists()


@pytest.mark.parametrize(
    ("source", "stage", "message"),
    [("", {}, "no Python source"), ("pass", {"R": "shell"}, "local runpy"),
     ("pass", {"E": ["previous"]}, "execution controls"),
     ("pass", {"enabled": True}, "execution controls"),
     ("pass", {}, "fresh results.json"),
     ("from pathlib import Path\nPath('results.json').write_text('{}')", {}, "differs"),
     ("from pathlib import Path\nPath('results.json').symlink_to(PROJECT_ROOT / 'stale.json')", {}, "fresh results.json")],
)
def test_workflow_rejection_restores_import_path_and_cwd(tmp_path, source, stage, message):
    (tmp_path / "stale.json").write_text('{"value":7}')
    _workflow(tmp_path, source, **stage)
    cwd, path = Path.cwd(), sys.path[:]
    with pytest.raises(ValueError, match=message):
        _verify_workflow(tmp_path)
    assert Path.cwd() == cwd and sys.path == path


@pytest.mark.parametrize("contract", ["", "[demo]\nC='pass'", "[[demo]]\nC='pass'\n[__meta__]\nversion=1"])
def test_workflow_rejects_empty_or_automation_contract(tmp_path, contract):
    (tmp_path / "lab_stages.toml").write_text(contract)
    with pytest.raises(ValueError, match="executable stages|automation metadata"):
        _verify_workflow(tmp_path)


def test_workflow_rejects_source_mutation_during_execution(tmp_path):
    _workflow(tmp_path, "from pathlib import Path\nPath('results.json').write_text('{\"value\":7}')\n(PROJECT_ROOT / 'lab_stages.toml').write_text('changed')")
    with pytest.raises(ValueError, match="changed during"):
        _verify_workflow(tmp_path)


@pytest.mark.parametrize("mode", ["missing", "symlink", "unsupported"])
def test_workflow_requires_regular_source_and_supported_result(tmp_path, mode):
    if mode == "symlink":
        target = tmp_path / "actual.toml"
        target.write_text("")
        (tmp_path / "lab_stages.toml").symlink_to(target)
    with pytest.raises(ValueError, match="Missing regular|Unsupported notebook"):
        notebook_workflow_verifier.verify(tmp_path, module="demo",
            result_file="other.json" if mode == "unsupported" else "results.json",
            expected_sha256="unused")


@pytest.fixture
def notebook_project(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(sys.modules, "models", None)
    (tmp_path / "models.py").write_text(
        "from sklearn.neighbors import KNeighborsClassifier\n"
        "def build_models(max_depth=3, seed=42):\n"
        "    return {str(i): KNeighborsClassifier(n_neighbors=3) for i in range(3)}\n")
    (tmp_path / "app.py").write_text("pass")
    cells = [{"cell_type": "code", "source": ["import json\n", "from pathlib import Path\n"]},
             {"cell_type": "code", "source": "Path('metrics.json').write_text(json.dumps([{'accuracy': .9}]*3))"}]
    (tmp_path / "solution.ipynb").write_text(json.dumps({"cells": cells}))
    return tmp_path


def _fake_app(monkeypatch, *, startup=False, interaction=False, slider=True, display=True, at_min=False):
    from streamlit.testing.v1 import AppTest
    app = SimpleNamespace(exception=[SimpleNamespace(message="startup")] if startup else [],
                          metric=[1] if display else [], dataframe=[1] if display else [])
    values = []
    def run():
        app.exception = [SimpleNamespace(message="interaction")] if interaction else []
        return app
    def set_value(value):
        values.append(value)
        return SimpleNamespace(run=run)
    app.slider = [SimpleNamespace(min=1, max=5, value=1 if at_min else 3, set_value=set_value)] if slider else []
    monkeypatch.setattr(AppTest, "from_file", lambda *a, **k: SimpleNamespace(run=lambda: app))
    return values


@pytest.mark.parametrize("at_min", [False, True])
def test_notebook_verifier_executes_fresh_cells_and_checks_app_contract(notebook_project, monkeypatch, at_min):
    values = _fake_app(monkeypatch, at_min=at_min)
    cwd = Path.cwd()
    report = notebook_verifier.verify(notebook_project)
    assert report["status"] == "passed"
    assert len(report["scores"]) == 9
    assert {row["seed"] for row in report["scores"]} == {7, 29, 83}
    assert values == [5 if at_min else 1]
    assert report["result_sha256"] == notebook_workflow_verifier.result_digest([{"accuracy": .9}]*3)
    assert Path.cwd() == cwd
    assert not (notebook_project / "metrics.json").exists()


@pytest.mark.parametrize(("options", "message"), [
    ({"startup": True}, "App startup failed"),
    ({"slider": False}, "max-depth slider"),
    ({"interaction": True}, "App interaction failed"),
    ({"display": False}, "metric and a model comparison"),
])
def test_notebook_verifier_rejects_incomplete_app_contract(notebook_project, monkeypatch, options, message):
    _fake_app(monkeypatch, **options)
    with pytest.raises(ValueError, match=message):
        notebook_verifier.verify(notebook_project)


@pytest.mark.parametrize(("cells", "message"), [
    ([], "at least two"),
    ([{"cell_type":"code", "source":"pass"}, {"cell_type":"code", "source":"from pathlib import Path\nPath('metrics.json').write_text('[]')"}], "three model results"),
    ([{"cell_type":"code", "source":"pass"}, {"cell_type":"code", "source":"from pathlib import Path\nPath('metrics.json').write_text('[{\"accuracy\":0.1},{},{ }]')"}], "Invalid notebook accuracy"),
])
def test_notebook_verifier_rejects_missing_or_bad_fresh_metrics(notebook_project, cells, message):
    (notebook_project / "solution.ipynb").write_text(json.dumps({"cells":cells}))
    cwd = Path.cwd()
    with pytest.raises(ValueError, match=message):
        notebook_verifier.verify(notebook_project)
    assert Path.cwd() == cwd


def test_notebook_verifier_requires_three_learning_models(notebook_project):
    (notebook_project / "models.py").write_text("def build_models(**kwargs): return {}")
    with pytest.raises(ValueError, match="at least three sklearn"):
        notebook_verifier.verify(notebook_project)


def test_notebook_verifier_rejects_symlinked_generated_files(notebook_project):
    path = notebook_project / "app.py"
    path.unlink()
    path.symlink_to(notebook_project / "models.py")
    with pytest.raises(ValueError, match="Missing regular generated file: app.py"):
        notebook_verifier.verify(notebook_project)


@pytest.mark.parametrize("workflow", [False, True])
@pytest.mark.parametrize("success", [False, True])
def test_verifier_cli_reports_machine_readable_result(monkeypatch, capsys, workflow, success):
    module = notebook_workflow_verifier if workflow else notebook_verifier
    def verify(*args, **kwargs):
        if not success:
            raise ValueError("invalid artifact")
        return {"status":"passed", "result_sha256":"verified"}
    monkeypatch.setattr(module, "verify", verify)
    monkeypatch.setattr(sys, "argv", ["verifier", "--module", "demo", "--result-file",
        "results.json", "--expected-sha256", "expected"] if workflow else ["verifier"])
    assert module.main() == (0 if success else 1)
    result = json.loads(capsys.readouterr().out)
    assert result == ({"status":"passed", "result_sha256":"verified"} if success else
                      {"status":"failed", "error":"ValueError: invalid artifact"})


@pytest.fixture
def execution_project(tmp_path):
    (tmp_path / "app.py").write_text("pass")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"')
    _execution_notebook(tmp_path, "from pathlib import Path\nPath('results.json').write_text('{\"results\":{\"answer\":42}}')")
    return tmp_path


def _execution_notebook(project, source, **updates):
    notebook = {"nbformat": 4, "cells": [{"cell_type":"code", "source":[source]}]}
    notebook.update(updates)
    (project / "solution.ipynb").write_text(json.dumps(notebook))


def _execution_app(monkeypatch, mode):
    from streamlit.testing.v1 import AppTest
    app = SimpleNamespace(exception=[], metric=[], dataframe=[], json=[], markdown=[], text=[])
    if mode == "startup":
        app.exception = [SimpleNamespace(message="startup")]
    def run():
        if mode == "interaction":
            app.exception = [SimpleNamespace(message="interaction")]
        elif mode != "unchanged":
            app.metric = [SimpleNamespace(value=42)]
        return app
    button = SimpleNamespace(label="Run analysis", click=lambda: SimpleNamespace(run=run))
    app.button = [] if mode == "missing_button" else [button,button] if mode == "duplicate_button" else [button]
    monkeypatch.setattr(AppTest, "from_file", lambda *a, **k: SimpleNamespace(run=lambda: app))


@pytest.mark.parametrize(("mode", "message"), [
    ("success", None), ("startup", "startup failed"),
    ("interaction", "interaction failed"), ("unchanged", "new or changed"),
    ("missing_button", "exactly one"), ("duplicate_button", "exactly one"),
])
def test_execution_verifier_requires_changed_visible_result(execution_project, monkeypatch, mode, message):
    from agilab.agent_runtime import notebook_execution_verifier as verifier
    _execution_app(monkeypatch, mode)
    cwd, path = Path.cwd(), sys.path[:]
    if message:
        with pytest.raises(ValueError, match=message):
            verifier.verify(execution_project)
    else:
        result = verifier.verify(execution_project)
        assert result["result_names"] == ["answer"]
        assert result["verification_scope"] == "execution_and_interface"
        assert result["scientific_correctness_verified"] is False
        assert result["result_sha256"] == notebook_workflow_verifier.result_digest({"results":{"answer":42}})
    assert Path.cwd() == cwd and sys.path == path
    assert not (execution_project / "results.json").exists()


@pytest.mark.parametrize(("payload", "message"), [
    ("[]", "results object"), ('{"results":{}}', "nonempty"),
    ('{"results":{"value":null}}', "nonempty"), ('{"results":{"value":"  "}}', "nonempty"),
    ('{"results":{"value":NaN}}', "Non-finite"),
])
def test_execution_verifier_rejects_empty_or_nonfinite_results(execution_project, payload, message):
    from agilab.agent_runtime import notebook_execution_verifier as verifier
    _execution_notebook(execution_project, "from pathlib import Path\nPath('results.json').write_text(" + repr(payload) + ")")
    cwd, path = Path.cwd(), sys.path[:]
    with pytest.raises(ValueError, match=message):
        verifier.verify(execution_project)
    assert Path.cwd() == cwd and sys.path == path


@pytest.mark.parametrize(("updates", "message"), [
    ({"nbformat":3}, "version 4"), ({"cells":[]}, "runnable Python"),
    ({"metadata":{"kernelspec":{"language":"julia"}}}, "Python notebooks"),
])
def test_execution_verifier_rejects_unsupported_notebooks(execution_project, updates, message):
    from agilab.agent_runtime import notebook_execution_verifier as verifier
    _execution_notebook(execution_project, "pass", **updates)
    with pytest.raises(ValueError, match=message):
        verifier.verify(execution_project)


@pytest.mark.parametrize("symlink", [False, True])
def test_execution_verifier_requires_fresh_regular_result(execution_project, symlink):
    from agilab.agent_runtime import notebook_execution_verifier as verifier
    source = "pass"
    if symlink:
        (execution_project / "stale.json").write_text('{"results":{"x":1}}')
        source = "from pathlib import Path\nPath('results.json').symlink_to(PROJECT_ROOT / 'stale.json')"
    _execution_notebook(execution_project, source)
    with pytest.raises(ValueError, match="fresh results.json"):
        verifier.verify(execution_project)


def test_execution_verifier_requires_project_metadata(execution_project):
    from agilab.agent_runtime import notebook_execution_verifier as verifier
    (execution_project / "pyproject.toml").write_text("[tool.example]")
    with pytest.raises(ValueError, match="project metadata"):
        verifier.verify(execution_project)


@pytest.mark.parametrize(("value", "expected"), [
    (False, True), (0, True), (float("inf"), False), ([None, {"value":"yes"}], True),
    ([None, ""], False), (object(), False),
])
def test_execution_result_presence_distinguishes_empty_from_zero_or_false(value, expected):
    from agilab.agent_runtime import notebook_execution_verifier as verifier
    assert verifier._has_value(value) is expected
