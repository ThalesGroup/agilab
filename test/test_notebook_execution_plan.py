"""Real execution regressions for the notebook-to-workflow handoff."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from types import SimpleNamespace

import pytest

from agilab.agent_runtime import notebook_agent as agent
from agilab.agent_runtime import notebook_workflow_verifier as verifier
from agilab.notebooks.notebook_pipeline_import import (
    apply_notebook_runtime_roles,
    build_lab_stages_preview,
    build_notebook_pipeline_import,
    write_lab_stages_preview,
)
from agilab.notebooks.notebook_export_support import (
    NotebookExportContext,
    build_notebook_document,
)


def imported_notebook(*sources):
    return build_notebook_pipeline_import(
        notebook={
            "nbformat": 4,
            "metadata": {},
            "cells": [{"cell_type": "code", "source": source} for source in sources],
        },
        source_notebook="example.ipynb",
    )


def stateful_notebook():
    return imported_notebook(
        "from pathlib import Path\nimport json\nvalues = [2, 3]\nalias = values\n",
        "alias.append(5)\ndef total():\n    return sum(values) * scale\n",
        "scale = 4\nPath('results.json').write_text(json.dumps({'results': {'total': total()}}))\n",
    )


def write_stages(project, imported, *, preserve=True):
    stages = build_lab_stages_preview(
        imported,
        module_name="demo",
        preserve_notebook_state=preserve,
    )
    write_lab_stages_preview(project / "lab_stages.toml", stages)
    return stages["demo"]


def run_verifier(project, expected):
    return subprocess.run(
        [
            sys.executable,
            str(Path(verifier.__file__).resolve()),
            "--module",
            "demo",
            "--result-file",
            "results.json",
            "--expected-sha256",
            verifier.result_digest(expected),
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_legacy_projection_loses_state_but_compiled_workflow_replays_in_fresh_process(
    tmp_path,
):
    imported = stateful_notebook()
    original = copy.deepcopy(imported)
    expected = {"results": {"total": 40}}
    write_stages(tmp_path, imported, preserve=False)
    failed = run_verifier(tmp_path, expected)
    assert failed.returncode == 1
    assert "NameError" in failed.stdout and "alias" in failed.stdout

    stages = write_stages(tmp_path, imported)
    assert len(stages) == 1
    assert stages[0]["NB_EXECUTION_STRATEGY"] == "shared_namespace"
    assert [cell["index"] for cell in stages[0]["NB_SOURCE_CELLS"]] == [1, 2, 3]
    assert imported == original
    # A stale project result cannot be used by the fresh-directory check.
    (tmp_path / "results.json").write_text('{"results": {"stale": true}}')
    result = run_verifier(tmp_path, expected)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["checks"] == [
        "fresh_workflow_execution",
        "fresh_result_artifact",
        "notebook_result_agreement",
    ]
    assert report["stages_sha256"] == agent.digest(tmp_path / "lab_stages.toml")
    assert report["scientific_correctness_verified"] is False


def test_compile_never_executes_cells_and_toml_retains_original_sources(tmp_path):
    marker = tmp_path / "must-not-execute"
    imported = imported_notebook(
        f"open({str(marker)!r}, 'w').write('unexpected')\n", "print('done')\n"
    )
    write_stages(tmp_path, imported)
    assert not marker.exists()
    stages = tomllib.loads((tmp_path / "lab_stages.toml").read_text())["demo"]
    assert [cell["source"] for cell in stages[0]["NB_SOURCE_CELLS"]] == [
        "".join(stage["source_lines"]) for stage in imported["pipeline_stages"]
    ]


def test_cell_scope_preserves_future_imports_and_shadowed_builtin_names(tmp_path):
    imported = imported_notebook(
        "from __future__ import annotations\ndef f(x: Unknown):\n    return x\n",
        "compile = None\nexec = None\nglobals = None\n",
        "def g(x: AnotherUnknown):\n    return f(x)\nfrom pathlib import Path\nimport json\n"
        "Path('results.json').write_text(json.dumps({'results': {'answer': f(42)}}))\n",
    )
    write_stages(tmp_path, imported)
    result = run_verifier(tmp_path, {"results": {"answer": 42}})
    assert result.returncode == 0, result.stdout + result.stderr


def test_python_error_keeps_original_cell_location(tmp_path):
    imported = imported_notebook("value = 0\n", "answer = 1 / value\n")
    stage = write_stages(tmp_path, imported)[0]
    with pytest.raises(ZeroDivisionError) as raised:
        exec(stage["C"], {"__name__": "__main__"})
    assert any(entry.path == "notebook:cell-2" for entry in raised.traceback)


@pytest.mark.parametrize(
    "source", ["%matplotlib inline\n", "value =\n", "await work()\n"]
)
def test_unsupported_python_is_rejected_before_stage_persistence(tmp_path, source):
    with pytest.raises(SyntaxError):
        write_stages(tmp_path, imported_notebook(source))
    assert not (tmp_path / "lab_stages.toml").exists()


def test_mixed_runtime_choices_require_explicit_artifact_boundaries():
    imported = apply_notebook_runtime_roles(
        stateful_notebook(),
        {"cell-1": "manager", "cell-2": "worker", "cell-3": "worker"},
    )
    with pytest.raises(ValueError, match="one reviewed runtime"):
        build_lab_stages_preview(imported, preserve_notebook_state=True)


def test_existing_supervisor_graph_remains_separate():
    imported = stateful_notebook()
    imported["source"]["import_mode"] = "agilab_supervisor_metadata"
    for index, stage in enumerate(imported["pipeline_stages"]):
        stage["stage_id_explicit"] = True
        stage["depends_on"] = [f"cell-{index}"] if index else []
    assert build_lab_stages_preview(
        imported, preserve_notebook_state=True
    ) == build_lab_stages_preview(imported)


def test_compiled_stage_roundtrip_preserves_source_mapping_until_code_is_edited(
    tmp_path,
):
    stages = build_lab_stages_preview(
        stateful_notebook(),
        module_name="demo",
        preserve_notebook_state=True,
    )
    exported = build_notebook_document(
        stages,
        tmp_path / "lab_stages.toml",
        export_context=NotebookExportContext(
            project_name="demo", module_path="demo", artifact_dir=str(tmp_path)
        ),
    )
    imported = build_notebook_pipeline_import(
        notebook=exported, source_notebook="export.ipynb"
    )
    restored = build_lab_stages_preview(imported, module_name="demo")["demo"][0]
    for key in (
        "C",
        "NB_EXECUTION_PLAN_SCHEMA",
        "NB_EXECUTION_STRATEGY",
        "NB_SOURCE_CELLS",
        "NB_SOURCE_SHA256",
        "NB_COMPILED_SHA256",
    ):
        assert restored[key] == stages["demo"][0][key]
    cell = next(
        cell
        for cell in exported["cells"]
        if cell.get("metadata", {}).get("agilab", {}).get("stage_cell", {}).get("kind")
        == "source"
    )
    cell["source"] = ["STAGE_000_CODE = 'print(42)\\n'\n"]
    edited = build_notebook_pipeline_import(
        notebook=exported, source_notebook="export.ipynb"
    )
    edited_stage = build_lab_stages_preview(edited, module_name="demo")["demo"][0]
    assert "NB_EXECUTION_PLAN_SCHEMA" not in edited_stage


def test_changed_result_cannot_be_reported_as_workflow_agreement(tmp_path):
    write_stages(tmp_path, stateful_notebook())
    result = run_verifier(tmp_path, {"results": {"total": 41}})
    assert result.returncode == 1
    assert "differs from the verified notebook" in result.stdout


@pytest.mark.parametrize(
    "control",
    [
        {"enabled": False},
        {"skip": True},
        {"E": "/other/runtime"},
        {"depends_on": ["missing"]},
    ],
)
def test_workflow_verifier_does_not_ignore_execution_controls(tmp_path, control):
    stage = write_stages(tmp_path, stateful_notebook())[0]
    stage.update(control)
    write_lab_stages_preview(tmp_path / "lab_stages.toml", {"demo": [stage]})
    result = run_verifier(tmp_path, {"results": {"total": 40}})
    assert result.returncode == 1
    assert "full AGILAB runtime verifier" in result.stdout


def test_stale_result_and_workflow_mutation_fail_closed(tmp_path):
    (tmp_path / "results.json").write_text('{"results": {"answer": 42}}')
    write_stages(tmp_path, imported_notebook("pass\n"))
    result = run_verifier(tmp_path, {"results": {"answer": 42}})
    assert result.returncode == 1
    assert "fresh results.json" in result.stdout

    write_stages(
        tmp_path,
        imported_notebook(
            "from pathlib import Path\nimport json\n"
            "(PROJECT_ROOT / 'lab_stages.toml').write_text('changed')\n"
            "Path('results.json').write_text(json.dumps({'results': {'answer': 42}}))\n"
        ),
    )
    result = run_verifier(tmp_path, {"results": {"answer": 42}})
    assert result.returncode == 1
    assert "changed during workflow verification" in result.stdout


@pytest.mark.parametrize("break_handoff", [False, True])
def test_builder_requires_actual_persisted_workflow_verification(
    tmp_path, monkeypatch, break_handoff
):
    source = tmp_path / "input.ipynb"
    source.write_text(json.dumps({"nbformat": 4, "cells": [{"cell_type": "code", "source": "answer = 42\n"}]}))
    root = tmp_path / "run"
    root.mkdir()
    monkeypatch.setattr(agent.shutil, "which", lambda _: sys.executable)

    def generate(config):
        cells = [
            "from pathlib import Path\nimport json\nanswer = 42\n",
            "Path('results.json').write_text(json.dumps({'results': {'answer': answer}}))\n",
        ]
        (config.cwd / "solution.ipynb").write_text(
            json.dumps(
                {
                    "nbformat": 4,
                    "cells": [{"cell_type": "code", "source": code} for code in cells],
                }
            )
        )
        (config.cwd / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = "0.0.0"\n'
        )
        (config.cwd / "app.py").write_text(
            "import streamlit as st\nst.title('Fixture')\n"
            "if st.button('Run analysis'):\n    st.metric('Answer', 42)\n"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(agent, "run_agent_command", generate)
    if break_handoff:

        def legacy_preview(imported, *, module_name, **kwargs):
            return build_lab_stages_preview(imported, module_name=module_name)

        monkeypatch.setattr(agent, "build_lab_stages_preview", legacy_preview)
    report = agent.build(root, notebook=source)
    phases = [event["phase"] for event in agent.read_events(root)]
    assert "verify_workflow" in phases
    if break_handoff:
        assert report["status"] == "failed"
        assert "workflow verification failed" in report["error"]
        assert "ready" not in phases
        assert "NameError" in (root / "workflow_verification.log").read_text()
    else:
        assert report["status"] == "passed", report
        assert report["workflow_stages"] == 1
        assert (
            report["verification"]["workflow"]["result_sha256"]
            == report["verification"]["result_sha256"]
        )
        assert (
            report["verification"]["workflow"]["stages_sha256"]
            == report["files"]["lab_stages.toml"]
        )
        assert phases[-1] == "ready"
