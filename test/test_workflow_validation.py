from __future__ import annotations

import ast
import json
import textwrap
from pathlib import Path

from agilab import workflow_validation


def _write_stages(path: Path, text: str) -> Path:
    path.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")
    return path


def _issue_ids(report: dict[str, object]) -> set[str]:
    return {
        str(issue["check_id"])
        for issue in report.get("issues", [])
        if isinstance(issue, dict)
    }


def test_workflow_validation_builds_static_graph_and_artifact_edges(tmp_path: Path) -> None:
    apps_root = tmp_path / "apps"
    (apps_root / "demo_project").mkdir(parents=True)
    stages_file = _write_stages(
        tmp_path / "lab_stages.toml",
        """
        [__meta__]
        schema = "agilab.lab_stages.v1"
        version = 1

        [[stages]]
        id = "load"
        label = "Load source data"
        R = "runpy"
        NB_RUNTIME_ROLE = "manager"
        C = '''
        APP = "demo_project"
        data_out = "raw"
        '''

        [[stages]]
        id = "train"
        D = "Train model"
        R = "agi.run"
        depends_on = ["load"]
        C = '''
        AGI.run(data_in="raw", data_out="model", NB_RUNTIME_ROLE="worker")
        '''
        """,
    )

    report = workflow_validation.validate_lab_stages_file(stages_file, apps_root=apps_root)

    assert report["status"] == "pass"
    assert report["summary"]["stage_count"] == 2
    assert report["summary"]["dependency_count"] == 1
    assert report["summary"]["artifact_produced_count"] == 2
    assert report["summary"]["artifact_consumed_count"] == 1
    assert report["external_inputs"] == []
    assert report["dependency_edges"] == [
        {"source": "load", "target": "train", "kind": "depends_on"}
    ]
    assert report["artifact_edges"] == [
        {"source": "load", "target": "train", "artifact": "raw", "kind": "artifact_flow"}
    ]
    train = next(stage for stage in report["stages"] if stage["id"] == "train")
    assert train["kind"] == "run"
    assert train["runtime_role"] == "worker"
    assert train["consumes"] == ["raw"]
    assert train["produces"] == ["model"]
    assert len(train["code_sha256"]) == 64


def test_workflow_validation_reports_dependency_and_code_hazards(tmp_path: Path) -> None:
    stages_file = _write_stages(
        tmp_path / "lab_stages.toml",
        """
        [[stages]]
        R = "custom-engine"
        C = '''
        import os
        APP = "missing_project"
        data_in = "external.csv"
        data_out = "shared"
        os.system("echo risky")
        eval("1")
        '''

        [[stages]]
        id = "consumer"
        depends_on = ["missing", "later"]
        consumes = ["external.csv"]
        produces = ["shared"]

        [[stages]]
        id = "later"
        depends_on = ["consumer"]
        produces = ["shared"]
        """,
    )

    report = workflow_validation.validate_lab_stages_file(stages_file)
    ids = _issue_ids(report)

    assert report["status"] == "fail"
    assert {
        "metadata-missing",
        "stage-id-missing",
        "stage-engine-unknown",
        "runtime-role-missing",
        "app-reference-missing",
        "stage-code-risky-call",
        "dependency-missing",
        "dependency-forward-reference",
        "dependency-cycle",
        "artifact-produced-twice",
    } <= ids
    assert {"stage_id": "stages_001", "artifact": "external.csv", "kind": "external_input"} in report[
        "external_inputs"
    ]
    text_report = workflow_validation._text_report(report)
    assert "status: fail" in text_report
    assert "dependency-cycle" in text_report
    assert json.loads(workflow_validation._json_dump(report))["schema"] == (
        workflow_validation.WORKFLOW_DRY_RUN_SCHEMA
    )


def test_workflow_validation_fail_fast_cases(tmp_path: Path) -> None:
    missing = workflow_validation.validate_lab_stages_file(tmp_path / "missing.toml")
    assert missing["status"] == "fail"
    assert _issue_ids(missing) == {"stages-file-missing"}

    bad_toml = _write_stages(tmp_path / "bad.toml", "[__meta__")
    unreadable = workflow_validation.validate_lab_stages_file(bad_toml)
    assert unreadable["status"] == "fail"
    assert _issue_ids(unreadable) == {"stages-file-unreadable"}

    empty = _write_stages(
        tmp_path / "empty.toml",
        """
        [__meta__]
        schema = "agilab.lab_stages.v1"
        version = 1
        """,
    )
    no_stages = workflow_validation.validate_lab_stages_file(empty)
    assert no_stages["status"] == "fail"
    assert _issue_ids(no_stages) == {"no-stages"}

    meta_shape = _write_stages(
        tmp_path / "meta-shape.toml",
        """
        __meta__ = "legacy"

        [[steps]]
        id = "step"
        """,
    )
    assert "metadata-shape" in _issue_ids(workflow_validation.validate_lab_stages_file(meta_shape))

    meta_values = _write_stages(
        tmp_path / "meta-values.toml",
        """
        [__meta__]
        schema = "agilab.unknown"
        version = "bad"

        [[steps]]
        id = "step"
        """,
    )
    assert {"metadata-schema", "metadata-version"} <= _issue_ids(
        workflow_validation.validate_lab_stages_file(meta_values)
    )

    meta_future = _write_stages(
        tmp_path / "meta-future.toml",
        """
        [__meta__]
        schema = "agilab.lab_stages.v1"
        version = 999

        [[steps]]
        id = "step"
        """,
    )
    assert "metadata-version" in _issue_ids(workflow_validation.validate_lab_stages_file(meta_future))


def test_workflow_validation_cli_defaults_to_validate_and_honors_strict(
    tmp_path: Path,
    capsys,
) -> None:
    warning_only = _write_stages(
        tmp_path / "warn.toml",
        """
        [[stages]]
        D = "Order-dependent generated id"
        """,
    )

    assert workflow_validation.main([str(warning_only)]) == 0
    assert "status: warn" in capsys.readouterr().out

    assert workflow_validation.main(["validate", str(warning_only), "--strict"]) == 1
    assert "stage-id-missing" in capsys.readouterr().out

    assert workflow_validation.main(["validate", str(warning_only), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "warn"

    assert workflow_validation.main(["validate", str(tmp_path / "missing.toml")]) == 2
    assert "stages-file-missing" in capsys.readouterr().out


def test_workflow_validation_parser_helper_edges(tmp_path: Path, monkeypatch) -> None:
    original_toml_loads = workflow_validation.tomllib.loads
    stages_file = _write_stages(
        tmp_path / "shape.toml",
        """
        [__meta__]
        schema = "agilab.lab_stages.v1"
        version = 1
        """,
    )
    monkeypatch.setattr(workflow_validation.tomllib, "loads", lambda _text: [])
    shape = workflow_validation.validate_lab_stages_file(stages_file)
    assert shape["status"] == "fail"
    assert _issue_ids(shape) == {"stages-file-shape"}
    monkeypatch.setattr(workflow_validation.tomllib, "loads", original_toml_loads)

    syntax_file = _write_stages(
        tmp_path / "syntax.toml",
        """
        [__meta__]
        schema = "agilab.lab_stages.v1"
        version = 1

        [[steps]]
        id = "bad-code"
        C = "for"
        """,
    )
    syntax = workflow_validation.validate_lab_stages_file(syntax_file)
    assert "stage-code-syntax" in _issue_ids(syntax)

    install_file = _write_stages(
        tmp_path / "install.toml",
        """
        [__meta__]
        schema = "agilab.lab_stages.v1"
        version = 1

        [[steps]]
        id = "install"
        R = "agi.install"
        Q = '''

        Install dependencies
        '''
        inputs = [{ artifact = "wheelhouse" }]
        outputs = [{ path = "worker-env" }]
        C = '''
        runtime_role = "analysis"
        '''
        """,
    )
    install = workflow_validation.validate_lab_stages_file(install_file)
    stage = install["stages"][0]
    assert stage["kind"] == "install"
    assert stage["label"] == "Install dependencies"
    assert stage["runtime_role"] == "analysis"
    assert stage["consumes"] == ["wheelhouse"]
    assert stage["produces"] == ["worker-env"]

    repo_root = tmp_path / "repo"
    (repo_root / "src" / "agilab").mkdir(parents=True)
    (repo_root / "src" / "agilab" / "apps" / "builtin" / "demo_project").mkdir(parents=True)
    (repo_root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    assert workflow_validation._repo_root_from(repo_root / "src" / "agilab" / "x.toml") == repo_root
    assert workflow_validation._app_exists(
        "demo_project",
        apps_root=None,
        repo_root=repo_root,
        stages_file=repo_root / "lab_stages.toml",
    )
    assert workflow_validation._items({"id": "artifact-id"}) == ["artifact-id"]
    assert workflow_validation._items({"other": "ignored"}) == []
    assert workflow_validation._items(5) == ["5"]
    assert workflow_validation._unique_texts(["", "a", "a", "b"]) == ["a", "b"]
    assert workflow_validation._first_line("\n\n  title\n  body") == "title"
    assert workflow_validation._first_line("\n  \n") == ""
    assert workflow_validation._extract_stage_entries({"steps": ["skip", {"id": "kept"}]}) == [
        ("steps", 1, {"id": "kept"})
    ]
    assert workflow_validation._text_report({"summary": {}, "issues": ["bad-shape"]}).startswith(
        "status: unknown"
    )

    annotated = ast.parse("obj.target: str = 'x'").body[0]
    assert workflow_validation._assignment_name_value(annotated) == ("", annotated.value)
    tuple_assign = ast.parse("a[0] = 'x'").body[0]
    assert workflow_validation._assignment_name_value(tuple_assign) == ("", tuple_assign.value)
    division = ast.parse("path / 'child'", mode="eval").body
    assert workflow_validation._expr_to_text(division) == "path / child"
    tuple_value = ast.parse("('a', 'b')", mode="eval").body
    assert workflow_validation._expr_to_text(tuple_value) == "a,b"
    monkeypatch.setattr(workflow_validation.ast, "unparse", lambda _node: (_ for _ in ()).throw(RuntimeError("boom")))
    assert workflow_validation._expr_to_text(ast.parse("value", mode="eval").body) == ""
    call = ast.parse("pkg.mod.func()").body[0].value
    assert workflow_validation._call_name(call) == "pkg.mod.func"
    unsupported_call = ast.Call(func=ast.Constant("bad"), args=[], keywords=[])
    assert workflow_validation._call_name(unsupported_call) == ""
    assert workflow_validation._call_attribute_prefix(ast.Constant("bad")) == ""
    facts, fact_issues = workflow_validation._code_facts(
        "NB_RUNTIME_ROLE = 'worker'\nAGI.run(**{'data_in': 'x'})\nAGI.run(role='analysis')",
        stage_id="facts",
        path=str(tmp_path / "facts.py"),
    )
    assert fact_issues == []
    assert facts["role"] == "analysis"

    duplicate = workflow_validation.validate_lab_stages_file(
        _write_stages(
            tmp_path / "duplicate.toml",
            """
            [[steps]]
            id = "same"

            [[steps]]
            id = "same"
            """,
        )
    )
    assert "stage-id-duplicate" in _issue_ids(duplicate)
