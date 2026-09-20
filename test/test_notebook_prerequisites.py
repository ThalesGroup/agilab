"""Prerequisite decisions must not execute notebooks, imports or a provider."""

from __future__ import annotations

import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from agilab.agent_runtime import notebook_agent as agent
from agilab.notebooks import notebook_prerequisites as prerequisites
from agilab.notebooks.notebook_pipeline_import import build_notebook_pipeline_import


def notebook(*sources):
    return {
        "nbformat": 4,
        "cells": [{"cell_type": "code", "source": s} for s in sources],
    }


def inspect(*sources, available=lambda _: True, inputs=None):
    imported = build_notebook_pipeline_import(
        notebook=notebook(*sources), source_notebook="source.ipynb"
    )
    return prerequisites.inspect_prerequisites(
        imported, module_available=available, inputs=inputs
    )


def source_file(tmp_path, *sources):
    path = tmp_path / "input.ipynb"
    path.write_text(json.dumps(notebook(*sources)))
    return path


def test_required_and_optional_dependencies_are_distinguished():
    report = inspect(
        "import missing_required\ntry:\n import missing_optional\nexcept ImportError:\n pass\n"
        "def plot():\n import missing_plot\n",
        available=lambda name: name == "streamlit",
    )
    assert report["status"] == "blocked"
    errors = [i for i in report["issues"] if i["severity"] == "error"]
    assert len(errors) == 1 and "missing_required" in errors[0]["message"]
    optional = inspect(
        "try:\n import missing_optional\nexcept ImportError:\n pass\n",
        available=lambda name: name == "streamlit",
    )
    assert optional["safe_to_build"] and optional["status"] == "review"


def test_inspection_never_executes_source_or_imports_package(tmp_path, monkeypatch):
    marker = tmp_path / "executed"
    package = tmp_path / "preflight_fixture"
    package.mkdir()
    (package / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    report = inspect(
        "import preflight_fixture.child\n" + f"raise RuntimeError({str(marker)!r})\n",
        available=prerequisites._available,
    )
    assert report["safe_to_build"]
    assert not marker.exists() and "preflight_fixture" not in sys.modules


def test_input_reads_use_cell_order_and_do_not_execute_or_read_from_disk(
    tmp_path, monkeypatch
):
    # A coincidental file in the user's working directory is not a supplied input.
    (tmp_path / "observations.csv").write_text("do not copy implicitly")
    monkeypatch.chdir(tmp_path)
    report = inspect(
        "from pathlib import Path\nimport pandas as pd\nDATA = Path('observations.csv')\n",
        "frame = pd.read_csv(DATA)\nframe.to_csv('generated.csv')\n",
        "again = pd.read_csv('generated.csv')\n",
    )
    assert report["status"] == "blocked"
    assert [(i["path"], i["status"]) for i in report["inputs"]] == [
        ("observations.csv", "missing"),
        ("generated.csv", "produced_earlier"),
    ]
    assert not (tmp_path / "generated.csv").exists()
    supplied = inspect(
        "pd.read_csv('observations.csv')\n", inputs=[{"path": "observations.csv"}]
    )
    assert supplied["safe_to_build"] and supplied["inputs"][0]["status"] == "supplied"


def test_paths_follow_literal_bindings_but_do_not_reuse_stale_values():
    report = inspect(
        "from pathlib import Path\nROOT = Path('data')\nPATH = ROOT / 'input.csv'\n"
        "pd.read_csv(PATH)\nPATH = compute_path()\npd.read_csv(PATH)\n"
    )
    assert report["inputs"] == [
        {"path": "data/input.csv", "cell": "cell-1", "status": "missing"}
    ]
    assert any(i["code"] == "unresolved_file_path" for i in report["issues"])
    branch = inspect(
        "path = 'wrong.csv'\nif flag:\n path = resolve()\npd.read_csv(path)\n"
    )
    assert branch["safe_to_build"] and not branch["inputs"]


def test_optional_inputs_and_write_then_read_are_not_missing_blockers():
    report = inspect(
        "from pathlib import Path\nwith open('generated.txt', 'w') as f:\n f.write('sample')\n"
        "Path('generated.txt').read_text()\n"
        "if display_extra:\n pd.read_csv('optional.csv')\n"
        "def load():\n return pd.read_csv('later.csv')\n"
    )
    assert report["safe_to_build"]
    assert [i["status"] for i in report["inputs"]] == [
        "produced_earlier",
        "unverified",
        "unverified",
    ]
    early = inspect("pd.read_csv('later.csv')\npd.DataFrame().to_csv('later.csv')\n")
    assert not early["safe_to_build"]


@pytest.mark.parametrize(
    "path",
    [
        "../private.csv",
        "/tmp/private.csv",
        "C:/private.csv",
        "https://example.com/input.csv",
    ],
)
def test_external_notebook_paths_block_without_probing_them(path):
    report = inspect(f"pd.read_csv({path!r})\n")
    assert not report["safe_to_build"]
    assert report["issues"][0]["code"] == "external_file_path"


def test_model_requirements_are_recorded_without_claiming_cache_or_device_readiness():
    report = inspect(
        "MODEL = 'autogluon/chronos-2-small'\nREVISION = '" + "d" * 40 + "'\n",
        "model = Pipeline.from_pretrained(MODEL, revision=REVISION, device_map='cpu')\n"
        "other = Pipeline.from_pretrained(resolve_model(), device=choose_device())\n",
    )
    assert report["safe_to_build"] and report["status"] == "review"
    model = report["models"][0]
    assert (
        model["model_id"] == "autogluon/chronos-2-small"
        and model["revision"] == "d" * 40
    )
    assert model["device_map"] == "cpu" and model["status"] == "unverified"
    assert set(report["models"][1]["unresolved"]) == {"model_id", "device"}


def test_empty_source_blocks_and_magic_cells_report_incomplete_inspection():
    assert inspect()["safe_to_build"] is False
    report = inspect("%matplotlib inline\n")
    assert report["status"] == "review" and report["inspection_only"]
    assert report["issues"][0]["code"] == "unparsed_cell"


def test_explicit_inputs_are_hashed_and_protected(tmp_path):
    selected = tmp_path / "outside.csv"
    selected.write_bytes(b"a,b\n1,2\n")
    project = tmp_path / "project"
    project.mkdir()
    manifest = prerequisites.stage_input_files(project, {"data/table.csv": selected})
    assert manifest == [
        {
            "path": "data/table.csv",
            "bytes": selected.stat().st_size,
            "sha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
        }
    ]
    prerequisites.verify_input_files(project, manifest)
    (project / "data/table.csv").write_text("changed")
    with pytest.raises(ValueError, match="Supplied input changed"):
        prerequisites.verify_input_files(project, manifest)
    assert selected.read_bytes() == b"a,b\n1,2\n"


@pytest.mark.parametrize(
    "destination",
    [
        "../escape.csv",
        "/escape.csv",
        "C:/escape.csv",
        "a\\b.csv",
        "source/original.ipynb",
        "app.py",
        "APP.PY",
        "./input.csv",
    ],
)
def test_input_destination_cannot_escape_or_replace_builder_files(
    tmp_path, destination
):
    selected = tmp_path / "selected.csv"
    selected.write_text("keep")
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError):
        prerequisites.stage_input_files(project, {destination: selected})
    assert list(project.iterdir()) == []


def test_conflicting_oversized_and_symlink_inputs_are_rejected(tmp_path, monkeypatch):
    selected = tmp_path / "selected.csv"
    selected.write_text("12345")
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError, match="Conflicting"):
        prerequisites.stage_input_files(
            project, {"data": selected, "data/input.csv": selected}
        )
    assert list(project.iterdir()) == []
    (project / "linked").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        prerequisites.stage_input_files(project, {"linked/escape.csv": selected})
    monkeypatch.setattr(prerequisites, "MAX_INPUT_BYTES", 4)
    with pytest.raises(ValueError, match="total limit"):
        prerequisites.stage_input_files(project, {"input.csv": selected})
    assert not (project / "input.csv").exists()


def test_missing_prerequisite_stops_before_provider_and_tokki_lookup(
    tmp_path, monkeypatch
):
    source = source_file(tmp_path, "import missing_agilab_prerequisite_fixture\n")
    monkeypatch.setattr(
        agent.shutil, "which", lambda _: pytest.fail("Tokki lookup before preflight")
    )
    monkeypatch.setattr(
        agent, "run_agent_command", lambda _: pytest.fail("provider started")
    )
    root = agent.create_run(tmp_path / "runs")
    report = agent.build(root, notebook=source)
    assert (
        report["status"] == "failed"
        and "missing_agilab_prerequisite_fixture" in report["error"]
    )
    assert report["prerequisites"]["status"] == "blocked"
    assert [e["phase"] for e in agent.read_events(root)] == [
        "import",
        "preflight",
        "failed",
    ]
    assert (
        json.loads((root / "prerequisites.json").read_text()) == report["prerequisites"]
    )


def test_check_cli_is_provider_free_and_recovers_with_explicit_input(
    tmp_path, monkeypatch, capsys
):
    source = source_file(
        tmp_path, "from pathlib import Path\nPath('data/input.txt').read_text()\n"
    )
    data = tmp_path / "selected.txt"
    data.write_text("the actual analysis input")
    monkeypatch.setattr(agent.shutil, "which", lambda _: pytest.fail("Tokki lookup"))
    monkeypatch.setattr(
        agent, "run_agent_command", lambda _: pytest.fail("provider started")
    )
    monkeypatch.setattr(agent, "create_run", lambda _: pytest.fail("build run created"))
    assert agent.main(["--check", "--notebook", str(source)]) == 1
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["inputs"][0]["status"] == "missing"
    assert (
        agent.main(
            [
                "--check",
                "--notebook",
                str(source),
                "--input-file",
                f"data/input.txt={data}",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["inputs"][0]["status"] == "supplied"
    assert report["source_sha256"] == agent.digest(source)
    assert str(tmp_path) not in json.dumps(report)
    assert report["inspection_only"]


def test_input_manifest_reaches_provider_and_mutations_prevent_success(
    tmp_path, monkeypatch
):
    source = source_file(
        tmp_path, "from pathlib import Path\nPath('input.txt').read_text()\n"
    )
    data = tmp_path / "data.txt"
    data.write_text("original")
    root = agent.create_run(tmp_path / "runs")
    monkeypatch.setattr(agent.shutil, "which", lambda _: sys.executable)

    def mutate(config):
        inventory = json.loads((config.cwd / "source/prerequisites.json").read_text())
        assert inventory["supplied_inputs"][0]["sha256"] == agent.digest(data)
        assert "source/prerequisites.json" in config.command[-1]
        assert "Preserve recorded model IDs and revisions" in config.command[-1]
        (config.cwd / "input.txt").write_text("replacement")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(agent, "run_agent_command", mutate)
    report = agent.build(root, notebook=source, input_files={"input.txt": data})
    assert report["status"] == "failed" and "Supplied input changed" in report["error"]
    assert "ready" not in [e["phase"] for e in agent.read_events(root)]


def test_supplied_data_survives_notebook_app_and_persisted_workflow_checks(
    tmp_path, monkeypatch
):
    source = source_file(
        tmp_path,
        "from pathlib import Path\nvalue = int(Path('input.txt').read_text())\n",
    )
    data = tmp_path / "actual_input.txt"
    data.write_text("73")
    root = agent.create_run(tmp_path / "runs")
    monkeypatch.setattr(agent.shutil, "which", lambda _: sys.executable)

    def generate(config):
        # Simulate code delivery only. Both notebook runs and the UI interaction
        # are exercised by the actual independent verifier subprocesses.
        (config.cwd / "solution.ipynb").write_text(
            json.dumps(
                notebook(
                    "from pathlib import Path\nimport json\nvalue = int((PROJECT_ROOT / 'input.txt').read_text())\n",
                    "Path('results.json').write_text(json.dumps({'results': {'value': value}}))\n",
                )
            )
        )
        (config.cwd / "app.py").write_text(
            "from pathlib import Path\nimport streamlit as st\nst.title('Input analysis')\n"
            "if st.button('Run analysis'):\n"
            "    st.metric('Value', int(Path(__file__).with_name('input.txt').read_text()))\n"
        )
        (config.cwd / "pyproject.toml").write_text(
            '[project]\nname = "input-fixture"\nversion = "0.0.0"\n'
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(agent, "run_agent_command", generate)
    report = agent.build(root, notebook=source, input_files={"input.txt": data})
    assert report["status"] == "passed", report
    assert report["prerequisites"]["supplied_inputs"][0]["sha256"] == agent.digest(data)
    assert (
        report["verification"]["result_sha256"]
        == report["verification"]["workflow"]["result_sha256"]
    )
    assert report["verification"]["workflow"]["status"] == "passed"


def test_explicit_local_module_is_discoverable_without_importing_it():
    report = inspect(
        "from project_helper import analyze\n",
        available=lambda name: name == "streamlit",
        inputs=[{"path": "project_helper.py"}],
    )
    assert report["safe_to_build"]
    assert report["modules"][-1]["status"] == "discoverable"


def test_replacing_a_literal_with_a_function_does_not_keep_stale_input_or_model_identity():
    report = inspect(
        "model = 'old/model'\npath = 'old.csv'\n",
        "def model():\n return selected_model\ndef path():\n return selected_path\n",
        "Pipeline.from_pretrained(model)\npd.read_csv(path)\n",
    )
    assert report["safe_to_build"] and not report["inputs"]
    assert report["models"][0]["model_id"] is None
    assert report["models"][0]["unresolved"] == ["model_id"]


@pytest.mark.parametrize(
    "args",
    [
        ["--check"],
        ["--ui", "--check"],
        ["--notebook", "n.ipynb", "--input-file", "bad"],
        ["--ui", "--notebook", "n.ipynb", "--input-file", "x=y"],
    ],
)
def test_invalid_cli_combinations_fail_explicitly(args):
    with pytest.raises(SystemExit) as exc:
        agent.main(args)
    assert exc.value.code == 2
