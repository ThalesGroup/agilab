from __future__ import annotations

import importlib.util
import json
import os
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path("src/agilab/pages/1_PROJECT.py")


def _load_project_module():
    spec = importlib.util.spec_from_file_location("agilab_project_page_tests", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _extract_toolbar_buttons(payload):
    buttons = payload["buttons"] if isinstance(payload, dict) else payload
    assert isinstance(buttons, list), f"expected list of buttons, got {type(buttons)!r}"
    return buttons


def test_finalize_cloned_project_environment_detaches_shared_venv(tmp_path: Path):
    module = _load_project_module()
    source_root = tmp_path / "source_project"
    dest_root = tmp_path / "clone_project"
    source_venv = source_root / ".venv"
    dest_venv = dest_root / ".venv"
    source_venv.mkdir(parents=True)
    dest_root.mkdir(parents=True)
    os.symlink(source_venv, dest_venv, target_is_directory=True)

    message = module._finalize_cloned_project_environment(
        source_root,
        dest_root,
        "detach_venv",
    )

    assert message is not None
    assert "without sharing" in message
    assert not dest_venv.exists()
    assert not dest_venv.is_symlink()


def test_project_software_metric_summary_counts_repository_tests_for_builtin_flight():
    module = _load_project_module()
    project_root = Path("src/agilab/apps/builtin/flight_telemetry_project")

    repo_test_names = {path.name for path in module._iter_repo_project_test_files(project_root)}
    summary = module._project_software_metric_summary(project_root)

    assert "test_cluster_flight_validation.py" in repo_test_names
    assert "test_flight_telemetry_project_runtime_args.py" in repo_test_names
    assert "test_notebook_import_preflight.py" not in repo_test_names
    assert summary["test_files"] >= len(repo_test_names) > 0


def test_project_worker_class_summary_detects_builtin_flight_worker_class():
    module = _load_project_module()
    project_root = Path("src/agilab/apps/builtin/flight_telemetry_project")

    worker_class, worker_caption = module._project_worker_class_summary(project_root)

    assert worker_class == "PolarsWorker"
    assert worker_caption == "FlightWorker"


def test_finalize_cloned_project_environment_keeps_shared_venv(tmp_path: Path):
    module = _load_project_module()
    source_root = tmp_path / "source_project"
    dest_root = tmp_path / "clone_project"
    source_venv = source_root / ".venv"
    dest_venv = dest_root / ".venv"
    source_venv.mkdir(parents=True)
    dest_root.mkdir(parents=True)
    os.symlink(source_venv, dest_venv, target_is_directory=True)

    message = module._finalize_cloned_project_environment(
        source_root,
        dest_root,
        "share_source_venv",
    )

    assert message is not None
    assert "shares the source .venv" in message
    assert dest_venv.is_symlink()


def test_repair_renamed_project_environment_moves_real_venv(tmp_path: Path):
    module = _load_project_module()
    source_root = tmp_path / "source_project"
    dest_root = tmp_path / "renamed_project"
    source_venv = source_root / ".venv"
    dest_venv = dest_root / ".venv"
    source_venv.mkdir(parents=True)
    dest_root.mkdir(parents=True)
    (source_venv / "marker.txt").write_text("ok", encoding="utf-8")
    os.symlink(source_venv, dest_venv, target_is_directory=True)

    message = module._repair_renamed_project_environment(source_root, dest_root)

    assert message is not None
    assert "Preserved the project .venv" in message
    assert not source_venv.exists()
    assert not source_venv.is_symlink()
    assert (dest_venv / "marker.txt").read_text(encoding="utf-8") == "ok"


def test_export_project_action_creates_zip_and_honors_gitignore(tmp_path: Path):
    module = _load_project_module()
    project_root = tmp_path / "demo_project"
    project_root.mkdir()
    (project_root / ".gitignore").write_text("ignored.txt\nignored_dir/\n", encoding="utf-8")
    (project_root / "keep.txt").write_text("ok", encoding="utf-8")
    (project_root / "ignored.txt").write_text("ignore", encoding="utf-8")
    ignored_dir = project_root / "ignored_dir"
    ignored_dir.mkdir()
    (ignored_dir / "nested.txt").write_text("ignore", encoding="utf-8")
    export_root = tmp_path / "exports"
    env = SimpleNamespace(app="demo_project", active_app=project_root, export_apps=export_root)

    result = module._export_project_action(env)

    assert result.status == "success"
    assert result.title == f"Project exported to {export_root / 'demo_project.zip'}"
    assert result.detail is None
    assert result.data["app_zip"] == "demo_project.zip"
    with zipfile.ZipFile(result.data["output_zip"], "r") as archive:
        assert sorted(archive.namelist()) == [".gitignore", "keep.txt"]


def test_export_project_action_reports_missing_gitignore(tmp_path: Path):
    module = _load_project_module()
    project_root = tmp_path / "demo_project"
    project_root.mkdir()
    (project_root / "keep.txt").write_text("ok", encoding="utf-8")
    export_root = tmp_path / "exports"
    env = SimpleNamespace(app="demo_project", active_app=project_root, export_apps=export_root)

    result = module._export_project_action(env)

    assert result.status == "success"
    assert result.detail == "No .gitignore found; exported all files."
    with zipfile.ZipFile(result.data["output_zip"], "r") as archive:
        assert archive.namelist() == ["keep.txt"]


def test_export_project_action_reports_missing_project(tmp_path: Path):
    module = _load_project_module()
    env = SimpleNamespace(
        app="missing_project",
        active_app=tmp_path / "missing_project",
        export_apps=tmp_path / "exports",
    )

    result = module._export_project_action(env)

    assert result.status == "error"
    assert result.title == "Project 'missing_project' does not exist."
    assert "select another project" in str(result.next_action)


def _write_project_archive(path: Path, files: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_import_project_action_requires_archive_selection(tmp_path: Path):
    module = _load_project_module()
    env = SimpleNamespace(export_apps=tmp_path / "exports", apps_path=tmp_path / "apps")

    result = module._import_project_action(env, project_zip="-- Select a file --")

    assert result.status == "error"
    assert result.title == "Please select a project archive."
    assert "Choose an exported project zip" in str(result.next_action)


def test_import_project_action_reports_missing_archive(tmp_path: Path):
    module = _load_project_module()
    env = SimpleNamespace(export_apps=tmp_path / "exports", apps_path=tmp_path / "apps")

    result = module._import_project_action(env, project_zip="missing_project.zip")

    assert result.status == "error"
    assert result.title == "Project archive 'missing_project.zip' does not exist."
    assert result.data["zip_path"] == tmp_path / "exports" / "missing_project.zip"


def test_import_project_action_reports_invalid_archive(tmp_path: Path):
    module = _load_project_module()
    export_root = tmp_path / "exports"
    export_root.mkdir()
    (export_root / "demo_project.zip").write_text("not a zip", encoding="utf-8")
    apps_root = tmp_path / "apps"
    env = SimpleNamespace(export_apps=export_root, apps_path=apps_root)

    result = module._import_project_action(env, project_zip="demo_project.zip")

    assert result.status == "error"
    assert result.title == "Project archive 'demo_project.zip' could not be imported."
    assert "valid exported project zip" in str(result.next_action)
    assert result.data["target_dir"] == apps_root / "demo_project"
    assert not result.data["target_dir"].exists()


def test_import_project_action_imports_archive_and_runs_clean(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    export_root = tmp_path / "exports"
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _write_project_archive(
        export_root / "demo_project.zip",
        {"README.md": "demo", "src/demo.py": "print('ok')\n"},
    )
    cleaned: list[Path] = []
    monkeypatch.setattr(module, "clean_project", lambda path: cleaned.append(path))
    env = SimpleNamespace(export_apps=export_root, apps_path=apps_root)

    result = module._import_project_action(
        env,
        project_zip="demo_project.zip",
        clean=True,
        overwrite=False,
    )

    target_dir = apps_root / "demo_project"
    assert result.status == "success"
    assert result.title == "Project 'demo_project' successfully imported."
    assert result.data["target_dir"] == target_dir
    assert (target_dir / "README.md").read_text(encoding="utf-8") == "demo"
    assert (target_dir / "src" / "demo.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert cleaned == [target_dir]


def test_import_project_action_requires_overwrite_for_existing_project(tmp_path: Path):
    module = _load_project_module()
    export_root = tmp_path / "exports"
    apps_root = tmp_path / "apps"
    target_dir = apps_root / "demo_project"
    target_dir.mkdir(parents=True)
    (target_dir / "existing.txt").write_text("keep", encoding="utf-8")
    _write_project_archive(export_root / "demo_project.zip", {"new.txt": "new"})
    env = SimpleNamespace(export_apps=export_root, apps_path=apps_root)

    result = module._import_project_action(
        env,
        project_zip="demo_project.zip",
        overwrite=False,
    )

    assert result.status == "warning"
    assert result.title == "Project 'demo_project' already exists."
    assert "Confirm overwrite" in str(result.next_action)
    assert (target_dir / "existing.txt").read_text(encoding="utf-8") == "keep"


def test_import_project_action_overwrites_existing_project(tmp_path: Path):
    module = _load_project_module()
    export_root = tmp_path / "exports"
    apps_root = tmp_path / "apps"
    target_dir = apps_root / "demo_project"
    target_dir.mkdir(parents=True)
    (target_dir / "old.txt").write_text("old", encoding="utf-8")
    _write_project_archive(export_root / "demo_project.zip", {"new.txt": "new"})
    env = SimpleNamespace(export_apps=export_root, apps_path=apps_root)

    result = module._import_project_action(
        env,
        project_zip="demo_project.zip",
        overwrite=True,
    )

    assert result.status == "success"
    assert not (target_dir / "old.txt").exists()
    assert (target_dir / "new.txt").read_text(encoding="utf-8") == "new"


def test_import_project_action_reports_unremovable_existing_project(
    tmp_path: Path,
    monkeypatch,
):
    module = _load_project_module()
    export_root = tmp_path / "exports"
    apps_root = tmp_path / "apps"
    target_dir = apps_root / "demo_project"
    target_dir.mkdir(parents=True)
    _write_project_archive(export_root / "demo_project.zip", {"new.txt": "new"})
    env = SimpleNamespace(export_apps=export_root, apps_path=apps_root)

    def _raise_unremovable(path: Path) -> None:
        assert path == target_dir
        raise OSError("locked")

    monkeypatch.setattr(module.shutil, "rmtree", _raise_unremovable)

    result = module._import_project_action(
        env,
        project_zip="demo_project.zip",
        overwrite=True,
    )

    assert result.status == "error"
    assert result.title == "Project 'demo_project' is not removable."
    assert result.detail == "locked"
    assert "filesystem permissions" in str(result.next_action)
    assert result.data["target_dir"] == target_dir


def test_create_project_clone_action_creates_project_and_reports_strategy(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []

    def _clone_project(source: Path, target: Path):
        clone_calls.append((source, target))
        (tmp_path / target).mkdir()

    env = SimpleNamespace(apps_path=tmp_path, clone_project=_clone_project)

    result = module._create_project_clone_action(
        env,
        clone_source="source_project",
        raw_project_name="New Demo",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "success"
    assert result.title == "Project 'new_demo_project' created."
    assert result.detail is not None
    assert "without sharing" in result.detail
    assert result.data["new_name"] == "new_demo_project"
    assert clone_calls == [(Path("source_project"), Path("new_demo_project"))]
    assert (tmp_path / "new_demo_project").is_dir()


def test_create_project_clone_action_resolves_builtin_source_project(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []
    (tmp_path / "builtin" / "flight_telemetry_project").mkdir(parents=True)

    def _clone_project(source: Path, target: Path):
        clone_calls.append((source, target))
        (tmp_path / target).mkdir()

    env = SimpleNamespace(apps_path=tmp_path, clone_project=_clone_project)

    result = module._create_project_clone_action(
        env,
        clone_source="flight_telemetry_project",
        raw_project_name="Flight Telemetry From Notebook",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "success"
    assert clone_calls == [
        (
            Path("builtin") / "flight_telemetry_project",
            Path("flight_telemetry_from_notebook_project"),
        )
    ]
    assert result.data["clone_source"] == Path("flight_telemetry_project")
    assert result.data["resolved_clone_source"] == Path("builtin") / "flight_telemetry_project"


def test_create_project_clone_action_repairs_builtin_core_paths(tmp_path: Path):
    module = _load_project_module()
    (tmp_path / "builtin" / "flight_telemetry_project").mkdir(parents=True)

    def _clone_project(_source: Path, target: Path):
        dest = tmp_path / target
        worker = dest / "src" / "flight_telemetry_from_notebook_worker"
        worker.mkdir(parents=True)
        (dest / "pyproject.toml").write_text(
            """
[project]
name = "flight_telemetry_from_notebook_project"

[tool.uv.sources]
agi-env = { path = "../../../core/agi-env", editable = true }
agi-node = { path = "../../../core/agi-node", editable = true }
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (worker / "pyproject.toml").write_text(
            """
[project]
name = "flight_telemetry_from_notebook_worker"

[tool.uv.sources]
agi-env = { path = "../../../../../core/agi-env", editable = true }
""".strip()
            + "\n",
            encoding="utf-8",
        )

    env = SimpleNamespace(apps_path=tmp_path, clone_project=_clone_project)

    result = module._create_project_clone_action(
        env,
        clone_source="flight_telemetry_project",
        raw_project_name="Flight Telemetry From Notebook",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "success"
    assert "Repaired local core source paths" in str(result.detail)
    dest = tmp_path / "flight_telemetry_from_notebook_project"
    app_pyproject = tomllib.loads((dest / "pyproject.toml").read_text(encoding="utf-8"))
    worker_pyproject = tomllib.loads(
        (
            dest
            / "src"
            / "flight_telemetry_from_notebook_worker"
            / "pyproject.toml"
        ).read_text(encoding="utf-8")
    )
    assert app_pyproject["tool"]["uv"]["sources"]["agi-env"]["path"] == "../../core/agi-env"
    assert worker_pyproject["tool"]["uv"]["sources"]["agi-env"]["path"] == (
        "../../../../core/agi-env"
    )


def test_repair_cloned_builtin_core_paths_ignores_non_builtin_source(tmp_path: Path):
    module = _load_project_module()
    source_root = tmp_path / "templates" / "pandas_app_template"
    dest_root = tmp_path / "clone_project"
    source_root.mkdir(parents=True)
    dest_root.mkdir()
    pyproject = dest_root / "pyproject.toml"
    original = """
[project]
name = "clone_project"

[tool.uv.sources]
agi-env = { path = "../../../core/agi-env", editable = true }
""".strip() + "\n"
    pyproject.write_text(original, encoding="utf-8")
    env = SimpleNamespace(apps_path=tmp_path)

    message = module._repair_cloned_builtin_core_source_paths(env, source_root, dest_root)

    assert message is None
    assert pyproject.read_text(encoding="utf-8") == original


def test_repair_cloned_builtin_core_paths_skips_invalid_and_non_core_sources(tmp_path: Path):
    module = _load_project_module()
    source_root = tmp_path / "builtin" / "flight_telemetry_project"
    dest_root = tmp_path / "clone_project"
    source_root.mkdir(parents=True)
    invalid = dest_root / "invalid" / "pyproject.toml"
    valid = dest_root / "valid" / "pyproject.toml"
    invalid.parent.mkdir(parents=True)
    valid.parent.mkdir(parents=True)
    invalid.write_text("[project\n", encoding="utf-8")
    original_valid = """
[project]
name = "clone_project"

[tool.uv.sources]
demo = { path = "../not-core/demo", editable = true }
plain = "not-a-table"
""".strip() + "\n"
    valid.write_text(original_valid, encoding="utf-8")
    env = SimpleNamespace(apps_path=tmp_path)

    message = module._repair_cloned_builtin_core_source_paths(env, source_root, dest_root)

    assert message is None
    assert valid.read_text(encoding="utf-8") == original_valid


def test_create_project_clone_action_reports_core_source_repair_failure(
    tmp_path: Path,
    monkeypatch,
):
    module = _load_project_module()

    def _clone_project(_source: Path, target: Path) -> None:
        (tmp_path / target).mkdir()

    def _raise_repair(*_args, **_kwargs) -> None:
        raise ValueError("rewrite failed")

    monkeypatch.setattr(module, "_repair_cloned_builtin_core_source_paths", _raise_repair)
    env = SimpleNamespace(apps_path=tmp_path, clone_project=_clone_project)

    result = module._create_project_clone_action(
        env,
        clone_source="source_project",
        raw_project_name="Needs Repair",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "error"
    assert result.title == (
        "Project 'needs_repair_project' was created, but local source paths could not be repaired."
    )
    assert result.detail == "rewrite failed"
    assert "pyproject.toml" in str(result.next_action)
    assert result.data["resolved_clone_source"] == Path("source_project")


def test_create_project_clone_action_rejects_duplicate_names(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []
    (tmp_path / "existing_project").mkdir()
    env = SimpleNamespace(
        apps_path=tmp_path,
        clone_project=lambda source, target: clone_calls.append((source, target)),
    )

    result = module._create_project_clone_action(
        env,
        clone_source="source_project",
        raw_project_name="Existing",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "warning"
    assert result.title == "Project 'existing_project' already exists."
    assert result.next_action is not None
    assert "Choose another project name" in result.next_action
    assert clone_calls == []


def test_create_project_clone_action_reports_missing_clone_output(tmp_path: Path):
    module = _load_project_module()
    env = SimpleNamespace(apps_path=tmp_path, clone_project=lambda _source, _target: None)

    result = module._create_project_clone_action(
        env,
        clone_source="source_project",
        raw_project_name="Missing Output",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "error"
    assert result.title == "Error while creating 'missing_output_project'."
    assert result.next_action is not None
    assert "filesystem permissions" in result.next_action


def test_create_project_clone_action_reports_clone_exception(tmp_path: Path):
    module = _load_project_module()

    def _raise_clone(_source: Path, _target: Path) -> None:
        raise OSError("copy denied")

    env = SimpleNamespace(apps_path=tmp_path, clone_project=_raise_clone)

    result = module._create_project_clone_action(
        env,
        clone_source="source_project",
        raw_project_name="Broken Clone",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "error"
    assert result.title == "Project 'broken_clone_project' could not be cloned."
    assert result.detail == "copy denied"
    assert "filesystem permissions" in str(result.next_action)
    assert result.data["dest_root"] == tmp_path / "broken_clone_project"


def test_create_project_clone_action_reports_environment_finalization_failure(
    tmp_path: Path,
    monkeypatch,
):
    module = _load_project_module()

    def _clone_project(_source: Path, target: Path) -> None:
        (tmp_path / target).mkdir()

    def _raise_finalize(*_args, **_kwargs) -> None:
        raise ValueError("bad strategy")

    monkeypatch.setattr(module, "_finalize_cloned_project_environment", _raise_finalize)
    env = SimpleNamespace(apps_path=tmp_path, clone_project=_clone_project)

    result = module._create_project_clone_action(
        env,
        clone_source="source_project",
        raw_project_name="Partial Clone",
        clone_env_strategy="unknown",
    )

    assert result.status == "error"
    assert result.title == (
        "Project 'partial_clone_project' was created, but environment finalization failed."
    )
    assert result.detail == "bad strategy"
    assert "rerun INSTALL" in str(result.next_action)
    assert (tmp_path / "partial_clone_project").is_dir()


def test_create_project_from_notebook_writes_project_import_artifacts(
    tmp_path: Path,
):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []

    def _clone_project(source: Path, target: Path) -> None:
        clone_calls.append((source, target))
        (tmp_path / target).mkdir()

    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {"cell_type": "markdown", "source": ["# Load data\n"]},
            {
                "cell_type": "code",
                "source": [
                    "import pandas as pd\n",
                    "df = pd.read_csv('data/orders.csv')\n",
                    "df.to_csv('outputs/orders.csv')\n",
                ],
            },
        ],
    }
    uploaded = SimpleNamespace(
        name="Demo Notebook.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(notebook).encode("utf-8"),
    )
    env = SimpleNamespace(apps_path=tmp_path, clone_project=_clone_project)

    result = module._create_project_from_notebook_action(
        env,
        template_source="pandas_app_template",
        raw_project_name="Notebook Demo",
        uploaded_notebook=uploaded,
        clone_env_strategy="detach_venv",
    )

    dest_root = tmp_path / "notebook_demo_project"
    assert result.status == "success"
    assert result.title == "Project 'notebook_demo_project' created from notebook."
    assert "ORCHESTRATE" in str(result.next_action)
    assert "EXECUTE" in str(result.next_action)
    assert "WORKFLOW" in str(result.next_action)
    assert clone_calls == [(Path("pandas_app_template"), Path("notebook_demo_project"))]
    assert (dest_root / "notebooks/source/Demo_Notebook.ipynb").is_file()
    assert result.data["source_notebook"] == "notebooks/source/Demo_Notebook.ipynb"
    assert result.data["notebook_import_cell_count"] == 1

    steps = tomllib.loads((dest_root / "lab_stages.toml").read_text(encoding="utf-8"))
    assert steps["notebook_demo_project"][0]["D"] == "Load data"
    assert steps["notebook_demo_project"][0]["NB_SOURCE_NOTEBOOK"] == (
        "notebooks/source/Demo_Notebook.ipynb"
    )

    contract = json.loads((dest_root / "notebook_import_contract.json").read_text(encoding="utf-8"))
    assert contract["artifact_contract"]["inputs"] == ["data/orders.csv"]
    assert contract["artifact_contract"]["outputs"] == ["outputs/orders.csv"]
    assert (dest_root / "notebook_import_pipeline_view.json").is_file()
    assert (dest_root / "notebook_import_view_plan.json").is_file()


def test_notebook_import_metadata_prefills_create_defaults():
    module = _load_project_module()
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "agilab": {
                "import": {
                    "schema": "agilab.notebook_import.v1",
                    "recommended_template": "flight_telemetry_project",
                    "project_name_hint": "flight-telemetry-from-notebook-project",
                }
            }
        },
        "cells": [{"cell_type": "code", "source": ["print('hello')\n"]}],
    }
    uploaded = SimpleNamespace(
        name="flight_sample.ipynb",
        getvalue=lambda: json.dumps(notebook).encode("utf-8"),
    )
    session_state: dict[str, object] = {}

    defaults = module._apply_notebook_import_defaults_from_upload(
        session_state,
        uploaded,
        ["flight_telemetry_project", "pandas_app_template", "other_template"],
    )

    assert defaults["recommended_template"] == "flight_telemetry_project"
    assert defaults["project_name_hint"] == "flight-telemetry-from-notebook-project"
    assert session_state["notebook_clone_src"] == "flight_telemetry_project"
    assert session_state["clone_dest"] == "flight-telemetry-from-notebook-project"


def test_notebook_project_source_options_include_apps_before_templates(tmp_path: Path):
    module = _load_project_module()
    (tmp_path / "builtin" / "flight_telemetry_project").mkdir(parents=True)
    (tmp_path / "mycode_project").mkdir()
    env = SimpleNamespace(
        app="flight_telemetry_project",
        projects=["flight_telemetry_project", "mycode_project"],
        apps_path=tmp_path,
    )

    assert module._notebook_project_source_options(
        env,
        ["pandas_app_template", "flight_telemetry_project"],
    ) == [
        "flight_telemetry_project",
        "mycode_project",
        "pandas_app_template",
    ]


def test_notebook_project_source_options_skip_app_sources_without_apps_path():
    module = _load_project_module()
    env = SimpleNamespace(
        app="flight_telemetry_project",
        projects=["flight_telemetry_project", "mycode_project"],
    )

    assert module._notebook_project_source_options(env, ["pandas_app_template"]) == [
        "pandas_app_template"
    ]


def test_notebook_project_source_options_resolve_installed_apps_and_skip_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _load_project_module()
    installed_root = tmp_path / "site-packages" / "flight_telemetry_project"
    installed_root.mkdir(parents=True)
    (installed_root / "pyproject.toml").write_text(
        "[project]\nname = 'agi-app-flight-telemetry'\n",
        encoding="utf-8",
    )

    def _resolve_installed_app_project(name: str):
        return installed_root if name == "flight_telemetry_project" else None

    monkeypatch.setattr(
        module,
        "resolve_installed_app_project",
        _resolve_installed_app_project,
    )
    env = SimpleNamespace(
        app="missing_project",
        projects=["flight_telemetry_project", "ghost_project"],
        apps_path=tmp_path / "workspace-apps",
    )

    assert module._notebook_project_source_options(
        env,
        ["pandas_app_template"],
    ) == ["flight_telemetry_project", "pandas_app_template"]


def test_create_project_clone_action_resolves_installed_app_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = _load_project_module()
    apps_path = tmp_path / "workspace-apps"
    installed_root = tmp_path / "site-packages" / "flight_telemetry_project"
    installed_root.mkdir(parents=True)
    (installed_root / "pyproject.toml").write_text(
        "[project]\nname = 'agi-app-flight-telemetry'\n",
        encoding="utf-8",
    )
    clone_calls: list[tuple[Path, Path]] = []

    def _resolve_installed_app_project(name: str):
        return installed_root if name == "flight_telemetry_project" else None

    def _clone_project(source: Path, target: Path):
        clone_calls.append((source, target))
        (apps_path / target).mkdir(parents=True)

    monkeypatch.setattr(
        module,
        "resolve_installed_app_project",
        _resolve_installed_app_project,
    )
    env = SimpleNamespace(apps_path=apps_path, clone_project=_clone_project)

    result = module._create_project_clone_action(
        env,
        clone_source="flight_telemetry_project",
        raw_project_name="Flight Telemetry From Notebook",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "success"
    assert clone_calls == [
        (installed_root, Path("flight_telemetry_from_notebook_project"))
    ]
    assert result.data["resolved_clone_source"] == installed_root


def test_render_notebook_import_sample_actions_only_reports_existing_packaged_source():
    module = _load_project_module()

    class _Target:
        def __init__(self):
            self.buttons = []
            self.downloads = []
            self.captions = []

        def button(self, *args, **kwargs):
            self.buttons.append((args, kwargs))
            return True

        def download_button(self, *args, **kwargs):
            self.downloads.append((args, kwargs))

        def caption(self, message):
            self.captions.append(message)

    session_state: dict[str, object] = {
        module.PROJECT_NOTEBOOK_SAMPLE_SOURCE_KEY: True,
    }
    target = _Target()

    module._render_notebook_import_sample_actions(target, session_state)

    assert target.buttons == []
    assert target.captions == ["Using AGILAB's included notebook; no local file is needed."]
    assert session_state[module.PROJECT_NOTEBOOK_SAMPLE_SOURCE_KEY] is True
    assert target.downloads == []


def test_active_notebook_import_source_uses_sample_until_user_upload():
    module = _load_project_module()
    session_state: dict[str, object] = {module.PROJECT_NOTEBOOK_SAMPLE_SOURCE_KEY: True}

    source = module._active_notebook_import_source(session_state)
    notebook = json.loads(module._read_uploaded_notebook_bytes(source).decode("utf-8"))

    assert source.name == "flight_telemetry_from_notebook.ipynb"
    assert source.type == "application/x-ipynb+json"
    assert notebook["metadata"]["agilab"]["import"]["project_name_hint"] == (
        "flight-telemetry-from-notebook-project"
    )
    assert module.PROJECT_NOTEBOOK_SAMPLE_SOURCE_KEY in session_state

    user_upload = SimpleNamespace(name="own.ipynb", getvalue=lambda: b"{}")
    session_state["create_notebook_upload"] = user_upload

    assert module._active_notebook_import_source(session_state) is user_upload
    assert module.PROJECT_NOTEBOOK_SAMPLE_SOURCE_KEY not in session_state


def test_notebook_import_create_copy_uses_newcomer_friendly_labels():
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "Start from a notebook. AGILAB clones a base project" in source
    assert "Base project to clone" in source
    assert "This notebook will create" in source
    assert "Upload your own notebook file" in source
    assert "AGILAB's included notebook is selected" in source
    assert "ORCHESTRATE opens next for INSTALL and EXECUTE" in source
    assert "Advanced" in source
    assert "then EXECUTE" in source
    assert "create_notebook_use_sample" not in source
    assert "create_notebook_sample_download" not in source
    assert 'st.session_state["project_selectbox"] = new_name' not in source
    assert 'st.session_state["lab_dir_selectbox"] = new_name' not in source
    assert 'switch_page(Path("pages/3_WORKFLOW.py"))' not in source
    assert '_switch_to_registered_navigation_page(\n                "orchestrate"' in source
    assert "Notebook source" not in source
    assert "INSTALL then RUN" not in source
    assert "chosen app or template source" not in source


def test_project_navigation_uses_registered_orchestrate_page(monkeypatch):
    module = _load_project_module()
    route = object()

    class _FakeStreamlit:
        def __init__(self):
            self.session_state = {}
            self.calls = []

        def switch_page(self, page, **kwargs):
            self.calls.append((page, kwargs.get("query_params")))

    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setitem(
        module.sys.modules,
        "__main__",
        SimpleNamespace(_NAVIGATION_PAGE_ROUTES={"orchestrate": route}),
    )

    assert module._switch_to_registered_navigation_page(
        "orchestrate",
        "ORCHESTRATE",
        query_params={"active_app": "demo_project"},
    ) is True
    assert fake_st.calls == [(route, {"active_app": "demo_project"})]


def test_project_navigation_without_registered_page_does_not_switch(monkeypatch):
    module = _load_project_module()

    class _FakeStreamlit:
        def __init__(self):
            self.session_state = {}
            self.calls = []

        def switch_page(self, page, **kwargs):
            self.calls.append((page, kwargs.get("query_params")))

    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setitem(
        module.sys.modules,
        "__main__",
        SimpleNamespace(_NAVIGATION_PAGE_ROUTES={}),
    )
    monkeypatch.setitem(
        module.sys.modules,
        "agilab.main_page",
        SimpleNamespace(_NAVIGATION_PAGE_ROUTES={}),
    )

    assert module._switch_to_registered_navigation_page(
        "orchestrate",
        "ORCHESTRATE",
        query_params={"active_app": "demo_project"},
    ) is False
    assert fake_st.calls == []


def test_notebook_import_metadata_does_not_overwrite_custom_create_defaults():
    module = _load_project_module()
    first_notebook = {
        "metadata": {
            "agilab": {
                "import": {
                    "recommended_template": "pandas_app_template",
                    "project_name_hint": "flight-telemetry-from-notebook-project",
                }
            }
        },
        "cells": [],
    }
    second_notebook = {
        "metadata": {
            "agilab": {
                "import": {
                    "recommended_template": "pandas_app_template",
                    "project_name_hint": "other-notebook-project",
                }
            }
        },
        "cells": [{"cell_type": "markdown", "source": ["changed"]}],
    }
    session_state: dict[str, object] = {}
    module._apply_notebook_import_defaults_from_upload(
        session_state,
        SimpleNamespace(
            name="first.ipynb",
            getvalue=lambda: json.dumps(first_notebook).encode("utf-8"),
        ),
        ["pandas_app_template", "other_template"],
    )
    session_state["clone_dest"] = "custom-project"
    session_state["notebook_clone_src"] = "other_template"

    module._apply_notebook_import_defaults_from_upload(
        session_state,
        SimpleNamespace(
            name="second.ipynb",
            getvalue=lambda: json.dumps(second_notebook).encode("utf-8"),
        ),
        ["pandas_app_template", "other_template"],
    )

    assert session_state["clone_dest"] == "custom-project"
    assert session_state["notebook_clone_src"] == "other_template"


def test_notebook_import_defaults_cache_same_upload_and_clear_state():
    module = _load_project_module()
    notebook = {
        "metadata": {
            "agilab": {
                "import": {
                    "recommended_template": "pandas_app_template",
                    "project_name_hint": "cached-notebook-project",
                }
            }
        },
        "cells": [],
    }

    class _ReadUpload:
        name = "cached.ipynb"

        def __init__(self, text: str):
            self.text = text
            self.seek_calls: list[int] = []

        def seek(self, offset: int):
            self.seek_calls.append(offset)

        def read(self):
            return self.text

    uploaded = _ReadUpload(json.dumps(notebook))
    session_state: dict[str, object] = {}

    defaults = module._notebook_import_defaults_from_upload(uploaded)
    visible = module._apply_notebook_import_defaults_from_upload(
        session_state,
        uploaded,
        ["pandas_app_template", "other_template"],
    )
    session_state["clone_dest"] = "user-kept-project"
    session_state["notebook_clone_src"] = "user_template"
    visible_again = module._apply_notebook_import_defaults_from_upload(
        session_state,
        uploaded,
        ["pandas_app_template", "other_template"],
    )

    assert defaults["_signature"].startswith("cached.ipynb:")
    assert uploaded.seek_calls == [0, 0, 0, 0, 0, 0]
    assert visible == {
        "recommended_template": "pandas_app_template",
        "project_name_hint": "cached-notebook-project",
    }
    assert visible_again == visible
    assert session_state["clone_dest"] == "user-kept-project"
    assert session_state["notebook_clone_src"] == "user_template"

    cleared = module._apply_notebook_import_defaults_from_upload(
        session_state,
        None,
        ["pandas_app_template"],
    )

    assert cleared == {}
    assert module.PROJECT_NOTEBOOK_IMPORT_DEFAULTS_KEY not in session_state
    assert module.PROJECT_NOTEBOOK_IMPORT_DEFAULTS_SIGNATURE_KEY not in session_state


def test_notebook_import_defaults_clear_previous_metadata_when_new_upload_has_none():
    module = _load_project_module()
    first_notebook = {
        "metadata": {
            "agilab": {
                "import": {
                    "recommended_template": "pandas_app_template",
                    "project_name_hint": "cached-notebook-project",
                }
            }
        },
        "cells": [],
    }
    plain_notebook = {
        "metadata": {},
        "cells": [{"cell_type": "markdown", "source": ["# no defaults\n"]}],
    }
    session_state: dict[str, object] = {}
    module._apply_notebook_import_defaults_from_upload(
        session_state,
        SimpleNamespace(
            name="first.ipynb",
            getvalue=lambda: json.dumps(first_notebook).encode("utf-8"),
        ),
        ["pandas_app_template", "other_template"],
    )

    defaults = module._apply_notebook_import_defaults_from_upload(
        session_state,
        SimpleNamespace(
            name="plain.ipynb",
            getvalue=lambda: json.dumps(plain_notebook).encode("utf-8"),
        ),
        ["pandas_app_template", "other_template"],
    )

    assert defaults == {}
    assert "clone_dest" not in session_state
    assert "notebook_clone_src" not in session_state
    assert session_state[module.PROJECT_NOTEBOOK_IMPORT_DEFAULTS_KEY] == {}
    assert session_state[module.PROJECT_NOTEBOOK_IMPORT_DEFAULTS_SIGNATURE_KEY].startswith(
        "plain.ipynb:"
    )


def test_notebook_import_defaults_preserve_user_edits_when_new_upload_has_none():
    module = _load_project_module()
    first_notebook = {
        "metadata": {
            "agilab": {
                "import": {
                    "recommended_template": "pandas_app_template",
                    "project_name_hint": "cached-notebook-project",
                }
            }
        },
        "cells": [],
    }
    plain_notebook = {
        "metadata": {},
        "cells": [{"cell_type": "markdown", "source": ["# no defaults\n"]}],
    }
    session_state: dict[str, object] = {}
    module._apply_notebook_import_defaults_from_upload(
        session_state,
        SimpleNamespace(
            name="first.ipynb",
            getvalue=lambda: json.dumps(first_notebook).encode("utf-8"),
        ),
        ["pandas_app_template", "other_template"],
    )
    session_state["clone_dest"] = "custom-project"
    session_state["notebook_clone_src"] = "other_template"

    defaults = module._apply_notebook_import_defaults_from_upload(
        session_state,
        SimpleNamespace(
            name="plain.ipynb",
            getvalue=lambda: json.dumps(plain_notebook).encode("utf-8"),
        ),
        ["pandas_app_template", "other_template"],
    )

    assert defaults == {}
    assert session_state["clone_dest"] == "custom-project"
    assert session_state["notebook_clone_src"] == "other_template"


def test_notebook_import_defaults_ignore_empty_non_dict_and_invalid_uploads():
    module = _load_project_module()

    assert module._notebook_import_defaults_from_upload(None) == {}
    assert module._notebook_import_defaults_from_upload(
        SimpleNamespace(name="empty.ipynb", getvalue=lambda: b"   "),
    ) == {}
    assert module._notebook_import_defaults_from_upload(
        SimpleNamespace(name="list.ipynb", getvalue=lambda: b"[]"),
    ) == {}

    session_state: dict[str, object] = {"clone_dest": "keep-project"}

    defaults = module._apply_notebook_import_defaults_from_upload(
        session_state,
        SimpleNamespace(name="broken.ipynb", getvalue=lambda: b"{"),
        ["pandas_app_template"],
    )

    assert defaults == {}
    assert session_state == {"clone_dest": "keep-project"}


def test_create_project_from_notebook_blocks_non_runnable_notebook(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [{"cell_type": "markdown", "source": ["# Notes only\n"]}],
    }
    uploaded = SimpleNamespace(
        name="notes.ipynb",
        type="application/x-ipynb+json",
        read=lambda: json.dumps(notebook).encode("utf-8"),
    )
    env = SimpleNamespace(
        apps_path=tmp_path,
        clone_project=lambda source, target: clone_calls.append((source, target)),
    )

    result = module._create_project_from_notebook_action(
        env,
        template_source="pandas_app_template",
        raw_project_name="Notes Only",
        uploaded_notebook=uploaded,
        clone_env_strategy="detach_venv",
    )

    assert result.status == "error"
    assert result.title == "Notebook cannot create a project yet."
    assert "stages=0" in str(result.detail)
    assert clone_calls == []
    assert not (tmp_path / "notes_only_project").exists()


def test_rename_project_action_preserves_venv_and_removes_source(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []
    source_root = tmp_path / "current_project"
    source_venv = source_root / ".venv"
    source_venv.mkdir(parents=True)
    (source_venv / "marker.txt").write_text("ok", encoding="utf-8")

    def _clone_project(source: Path, target: Path):
        clone_calls.append((source, target))
        (tmp_path / target).mkdir()

    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=_clone_project,
    )

    result = module._rename_project_action(env, raw_project_name="Renamed")

    assert result.status == "success"
    assert result.title == "Project renamed: 'current_project' -> 'renamed_project'"
    assert result.detail is not None
    assert "Preserved the project .venv" in result.detail
    assert result.next_action is None
    assert result.data["new_name"] == "renamed_project"
    assert clone_calls == [(Path("current_project"), Path("renamed_project"))]
    assert not source_root.exists()
    assert (tmp_path / "renamed_project/.venv/marker.txt").read_text(encoding="utf-8") == "ok"


def test_rename_project_action_rejects_duplicate_target(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []
    (tmp_path / "existing_project").mkdir()
    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=lambda source, target: clone_calls.append((source, target)),
    )

    result = module._rename_project_action(env, raw_project_name="Existing")

    assert result.status == "warning"
    assert result.title == "Project 'existing_project' already exists."
    assert result.next_action is not None
    assert "Choose another project name" in result.next_action
    assert clone_calls == []


def test_rename_project_action_reports_missing_clone_output(tmp_path: Path):
    module = _load_project_module()
    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=lambda _source, _target: None,
    )

    result = module._rename_project_action(env, raw_project_name="Missing Output")

    assert result.status == "error"
    assert result.title == "Error: Project 'missing_output_project' not found after renaming."
    assert result.next_action is not None
    assert "filesystem permissions" in result.next_action


def test_rename_project_action_reports_clone_exception(tmp_path: Path):
    module = _load_project_module()

    def _raise_clone(_source: Path, _target: Path) -> None:
        raise OSError("copy denied")

    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=_raise_clone,
    )

    result = module._rename_project_action(env, raw_project_name="Broken")

    assert result.status == "error"
    assert result.title == "Project 'current_project' could not be cloned to 'broken_project'."
    assert result.detail == "copy denied"
    assert "filesystem permissions" in str(result.next_action)
    assert result.data["dest_path"] == tmp_path / "broken_project"


def test_rename_project_action_reports_environment_preservation_failure(
    tmp_path: Path,
    monkeypatch,
):
    module = _load_project_module()
    source_root = tmp_path / "current_project"
    source_root.mkdir()

    def _clone_project(_source: Path, target: Path) -> None:
        (tmp_path / target).mkdir()

    def _raise_repair(_source: Path, _dest: Path) -> None:
        raise OSError("venv locked")

    monkeypatch.setattr(module, "_repair_renamed_project_environment", _raise_repair)
    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=_clone_project,
    )

    result = module._rename_project_action(env, raw_project_name="Renamed")

    assert result.status == "error"
    assert result.title == (
        "Project 'renamed_project' was cloned, but environment preservation failed."
    )
    assert result.detail == "venv locked"
    assert "rerun INSTALL" in str(result.next_action)
    assert (tmp_path / "renamed_project").is_dir()


def test_rename_project_action_reports_source_cleanup_failure(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    source_root = tmp_path / "current_project"
    source_root.mkdir()

    def _clone_project(_source: Path, target: Path):
        (tmp_path / target).mkdir()

    def _fail_rmtree(_path: Path):
        raise OSError("locked")

    monkeypatch.setattr(module.shutil, "rmtree", _fail_rmtree)
    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=_clone_project,
    )

    result = module._rename_project_action(env, raw_project_name="Renamed")

    assert result.status == "success"
    assert result.detail is not None
    assert "failed to remove" in result.detail
    assert result.next_action == f"Remove the old project directory manually: {source_root}"


def test_delete_project_action_requires_confirmation():
    module = _load_project_module()
    env = SimpleNamespace(app="current_project")

    result = module._delete_project_action(env, confirmed=False)

    assert result.status == "error"
    assert result.title == "Please confirm that you want to delete the project."
    assert result.next_action == "Tick the confirmation checkbox before deleting."


def test_delete_project_action_reports_missing_project(tmp_path: Path):
    module = _load_project_module()
    env = SimpleNamespace(
        app="current_project",
        active_app=tmp_path / "current_project",
    )

    result = module._delete_project_action(env, confirmed=True)

    assert result.status == "error"
    assert result.title == "Project 'current_project' does not exist."
    assert "Refresh the PROJECT page" in str(result.next_action)


def test_delete_project_action_removes_project_and_runtime_artifacts(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    project_path = tmp_path / "current_project"
    project_path.mkdir()
    wenv_path = tmp_path / "wenv" / "current_worker"
    wenv_path.mkdir(parents=True)
    data_root = tmp_path / "share" / "current"
    data_root.mkdir(parents=True)
    home_root = tmp_path / "home"
    cleanup_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(module.Path, "home", lambda: home_root)
    monkeypatch.setattr(
        module,
        "_cleanup_run_configuration_artifacts",
        lambda app, target, errors: cleanup_calls.append(("run", f"{app}:{target}")),
    )
    monkeypatch.setattr(
        module,
        "_cleanup_module_artifacts",
        lambda app, target, errors: cleanup_calls.append(("module", f"{app}:{target}")),
    )
    env = SimpleNamespace(
        app="current_project",
        active_app=project_path,
        target="current",
        wenv_abs=wenv_path,
        app_data_rel=data_root,
        projects=["current_project", "next_project"],
    )

    result = module._delete_project_action(env, confirmed=True)

    assert result.status == "success"
    assert result.title == "Project 'current_project' has been deleted."
    assert result.detail is None
    assert result.data["next_app"] == "next_project"
    assert result.data["cleanup_errors"] == ()
    assert env.projects == ["next_project"]
    assert not project_path.exists()
    assert not wenv_path.exists()
    assert not data_root.exists()
    assert cleanup_calls == [
        ("run", "current_project:current"),
        ("module", "current_project:current"),
    ]


def test_delete_project_action_reports_project_removal_failure(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    project_path = tmp_path / "current_project"
    project_path.mkdir()
    home_root = tmp_path / "home"
    original_safe_remove_path = module._safe_remove_path

    def _safe_remove_path(candidate, label, errors):
        if str(label).startswith("Project 'current_project'"):
            errors.append("Project 'current_project': locked")
            return
        original_safe_remove_path(candidate, label, errors)

    monkeypatch.setattr(module.Path, "home", lambda: home_root)
    monkeypatch.setattr(module, "_safe_remove_path", _safe_remove_path)
    monkeypatch.setattr(
        module,
        "_cleanup_run_configuration_artifacts",
        lambda _app, _target, _errors: None,
    )
    monkeypatch.setattr(
        module,
        "_cleanup_module_artifacts",
        lambda _app, _target, _errors: None,
    )
    env = SimpleNamespace(
        app="current_project",
        active_app=project_path,
        target="current",
        wenv_abs=tmp_path / "wenv" / "current_worker",
        app_data_rel=None,
        projects=["current_project", "next_project"],
    )

    result = module._delete_project_action(env, confirmed=True)

    assert result.status == "error"
    assert result.title == "Project 'current_project' could not be removed."
    assert result.detail == "Cleanup issue: Project 'current_project': locked"
    assert result.next_action == f"Remove {project_path} manually, then refresh the PROJECT page."
    assert result.data["cleanup_errors"] == ("Project 'current_project': locked",)
    assert env.projects == ["current_project", "next_project"]
    assert project_path.exists()


def test_clear_deleted_project_runtime_state_removes_stale_running_indicators():
    module = _load_project_module()
    session_state: dict[str, object] = {
        "_last_execute_failed": True,
        "current_project__last_run_log_file": "/tmp/run.log",
        "current_project__last_run_status": "running",
        "dataframe_deleted": True,
        "keep_me": "value",
        "last_run_log_path": "/tmp/run.log",
        "run_log_cache": "still running",
        "service_health_cache": [{"worker": "w1", "healthy": True}],
        "service_snapshot_path_cache": "/tmp/snapshot.json",
        "service_status_cache": "running",
        "show_run": True,
        "agilab:workflow_action_history": {
            "ORCHESTRATE::current_project::current": [{"status": "Running"}],
            "ORCHESTRATE::other_project::other": [{"status": "Done"}],
        },
        "agilab:workflow_ui_state": {
            "WORKFLOW::current_project::current": {"expanded": True},
            "WORKFLOW::other_project::other": {"expanded": False},
        },
    }

    module._clear_deleted_project_runtime_state(session_state, "current_project")

    for key in (
        "_last_execute_failed",
        "current_project__last_run_log_file",
        "current_project__last_run_status",
        "dataframe_deleted",
        "last_run_log_path",
        "run_log_cache",
        "service_health_cache",
        "service_snapshot_path_cache",
        "service_status_cache",
        "show_run",
    ):
        assert key not in session_state
    assert session_state["keep_me"] == "value"
    assert session_state["agilab:workflow_action_history"] == {
        "ORCHESTRATE::other_project::other": [{"status": "Done"}],
    }
    assert session_state["agilab:workflow_ui_state"] == {
        "WORKFLOW::other_project::other": {"expanded": False},
    }


def test_clearable_action_runner_empties_spinner_before_rendering_result():
    module = _load_project_module()
    events: list[object] = []

    class _Context:
        def __init__(self, name: str):
            self.name = name

        def __enter__(self):
            events.append(f"{self.name}:enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append(f"{self.name}:exit")
            return False

    class _SpinnerSlot(_Context):
        def empty(self):
            events.append("spinner_slot:empty")

    class _FakeStreamlit:
        def empty(self):
            return _SpinnerSlot("spinner_slot")

        def spinner(self, message):
            events.append(("spinner", message))
            return _Context("spinner")

        def success(self, message):
            events.append(("success", message))

        def info(self, message):
            events.append(("info", message))

    result = module._run_clearable_streamlit_action(
        _FakeStreamlit(),
        module.ActionSpec(
            name="Delete project",
            start_message="Deleting project 'current_project'...",
            failure_title="Project deletion failed.",
        ),
        lambda: module.ActionResult.success("Project 'current_project' has been deleted."),
        on_success=lambda _result: events.append("on_success"),
    )

    assert result.status == "success"
    assert events.index("spinner_slot:empty") < events.index(
        ("success", "Project 'current_project' has been deleted.")
    )
    assert events[-1] == "on_success"


def test_safe_remove_path_collects_probe_errors(monkeypatch):
    module = _load_project_module()
    errors: list[str] = []

    class _BrokenPath:
        def __init__(self, _value):
            pass

        def exists(self):
            raise OSError("probe failed")

        def is_symlink(self):
            return False

    monkeypatch.setattr(module, "Path", _BrokenPath)

    module._safe_remove_path("/tmp/demo", "demo", errors)

    assert errors == ["demo: probe failed"]


def test_regex_replace_rewrites_matching_file(tmp_path: Path):
    module = _load_project_module()
    target = tmp_path / "folders.xml"
    target.write_text('<folder name="demo" />\n', encoding="utf-8")
    errors: list[str] = []

    module._regex_replace(target, r'<folder name="demo" />', "", "folders", errors)

    assert target.read_text(encoding="utf-8") == "\n"
    assert errors == []


def test_regex_replace_reports_decode_errors(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    target = tmp_path / "folders.xml"
    target.write_text("demo", encoding="utf-8")
    errors: list[str] = []

    original_read_text = Path.read_text

    def _raise_decode(self, *args, **kwargs):
        if self == target:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad data")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raise_decode)

    module._regex_replace(target, "demo", "fixed", "folders", errors)

    assert errors == ["folders: 'utf-8' codec can't decode byte 0xff in position 0: bad data"]


def test_cleanup_run_configuration_artifacts_removes_matching_files(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    run_dir = tmp_path / ".idea" / "runConfigurations"
    run_dir.mkdir(parents=True)
    keep_xml = run_dir / "keep.xml"
    keep_xml.write_text('<config name="keep" />\n', encoding="utf-8")
    remove_by_pattern = run_dir / "_demo_clone.xml"
    remove_by_pattern.write_text('<config name="demo" />\n', encoding="utf-8")
    remove_by_content = run_dir / "manual.xml"
    remove_by_content.write_text('<config app="demo_app" />\n', encoding="utf-8")
    folders_xml = run_dir / "folders.xml"
    folders_xml.write_text('<folder name="demo_app" />\n<folder name="keep" />\n', encoding="utf-8")
    errors: list[str] = []

    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)

    module._cleanup_run_configuration_artifacts("demo_app", "demo_clone", errors)

    assert not remove_by_pattern.exists()
    assert not remove_by_content.exists()
    assert keep_xml.exists()
    assert '<folder name="demo_app" />' not in folders_xml.read_text(encoding="utf-8")
    assert errors == []


def test_process_files_reports_decode_errors(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    source_app = tmp_path / "demo_app"
    target_app = tmp_path / "demo_clone"
    source_app.mkdir()
    source_file = source_app / "broken.py"
    source_file.write_text("print('demo')\n", encoding="utf-8")
    warnings: list[str] = []

    original_read_text = Path.read_text

    def _raise_decode(self, *args, **kwargs):
        if self == source_file:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad data")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raise_decode)
    monkeypatch.setattr(module.st, "warning", warnings.append)

    spec = module.PathSpec.from_lines(module.GitWildMatchPattern, [])
    module.process_files(
        str(source_app),
        ["broken.py"],
        source_app,
        {"demo_app": "demo_clone"},
        spec,
    )

    assert warnings == [
        "Error processing file 'broken.py': 'utf-8' codec can't decode byte 0xff in position 0: bad data"
    ]
    assert not (target_app / "broken.py").exists()


def test_extract_attributes_code_handles_module_level_and_class_scope():
    module = _load_project_module()
    parsed = module.ast.parse(
        "GLOBAL = 1\nclass Demo:\n    value = 2\n    other: int = 3\n"
    )

    class_attributes = module._extract_attributes_code(parsed, "Demo")
    module_attributes = module._extract_attributes_code(parsed, "module-level")

    assert "value = 2" in class_attributes
    assert "other: int = 3" in class_attributes
    assert "GLOBAL = 1" in module_attributes


def test_build_updated_attributes_source_rewrites_selected_class():
    module = _load_project_module()
    original = "class Demo:\n    value = 1\n"

    updated = module._build_updated_attributes_source(
        original,
        "value = 4\nother = 5\n",
        "Demo",
    )

    assert "value = 4" in updated
    assert "other = 5" in updated
    assert "value = 1" not in updated


def test_save_code_editor_file_action_rejects_invalid_json_without_overwrite(tmp_path: Path):
    module = _load_project_module()
    target = tmp_path / "settings.json"
    target.write_text('{"ok": true}\n', encoding="utf-8")

    result = module._save_code_editor_file_action(target, "{bad json", "json")

    assert result.status == "error"
    assert result.title == "Failed to save changes to 'settings.json'."
    assert "Invalid JSON" in str(result.detail)
    assert target.read_text(encoding="utf-8") == '{"ok": true}\n'


def test_save_code_editor_file_action_writes_valid_text(tmp_path: Path):
    module = _load_project_module()
    target = tmp_path / "README.md"

    result = module._save_code_editor_file_action(target, "# Demo\n", "markdown")

    assert result.status == "success"
    assert result.title == "Changes saved to 'README.md'."
    assert target.read_text(encoding="utf-8") == "# Demo\n"


def test_project_editor_pin_supports_readme_and_other_files(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    project_root = tmp_path / "demo_project"
    project_root.mkdir()
    readme_text = "# Demo\n\nKeep this visible while navigating.\n"
    readme_path = project_root / "README.md"
    readme_path.write_text(readme_text, encoding="utf-8")
    env = SimpleNamespace(app="demo_project", active_app=project_root)
    calls: dict[str, object] = {}

    def fake_code_editor(body, **kwargs):
        calls["editor"] = (body, kwargs["lang"], kwargs["key"])
        calls["buttons"] = kwargs["buttons"]
        return {"type": module.EDITOR_PIN_RESPONSE, "text": body}

    class FakeStreamlit:
        def __init__(self):
            self.session_state = {}
            self.rerun_called = False

        def rerun(self):
            self.rerun_called = True

    fake_st = FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "code_editor", fake_code_editor)
    monkeypatch.setattr(module, "CUSTOM_BUTTONS", [{"name": "Copy"}], raising=False)
    monkeypatch.setattr(module, "INFO_BAR", {"info": [{"name": ""}]}, raising=False)
    monkeypatch.setattr(module, "comp_props", {}, raising=False)
    monkeypatch.setattr(module, "ace_props", {}, raising=False)

    module._render_readme(env)

    toolbar_buttons = _extract_toolbar_buttons(calls["buttons"])
    assert [button["name"] for button in toolbar_buttons[:2]] == ["Copy", "Pin"]
    pinned_buttons = module._project_editor_toolbar_buttons(
        {"buttons": [{"name": "Copy"}]},
        pinned=True,
    )
    pinned_toolbar = _extract_toolbar_buttons(pinned_buttons)
    assert [button["name"] for button in pinned_toolbar[:2]] == ["Copy", "Unpin"]
    assert pinned_toolbar[1]["commands"][-1] == ["response", module.EDITOR_UNPIN_RESPONSE]
    list_buttons = module._project_editor_toolbar_buttons(
        [{"name": "Copy"}],
        pinned=False,
    )
    list_toolbar = _extract_toolbar_buttons(list_buttons)
    assert [button["name"] for button in list_toolbar[:2]] == ["Copy", "Pin"]
    assert calls["editor"] == (
        readme_text,
        "markdown",
        f"readme:{readme_path}:module-level:readme:None",
    )
    panel_id = module._project_editor_panel_id(readme_path, "readme", "file", "readme")
    panel = fake_st.session_state["agilab:pinned_expanders"][panel_id]
    assert panel["title"] == "demo_project/README.md"
    assert panel["body"] == readme_text
    assert panel["body_format"] == "markdown"
    assert panel["source"] == str(readme_path)
    assert fake_st.rerun_called is True

    toml_text = "[project]\nname = \"demo\"\n"
    toml_path = project_root / "pyproject.toml"
    toml_path.write_text(toml_text, encoding="utf-8")
    calls.clear()

    module.render_code_editor(toml_path, toml_text, "toml", "pyproject", {}, {})

    toml_buttons = calls["buttons"]
    assert [button["name"] for button in _extract_toolbar_buttons(toml_buttons)[:2]] == ["Copy", "Pin"]
    assert calls["editor"] == (
        toml_text,
        "toml",
        f"pyproject:{toml_path}:module-level:pyproject:None",
    )
    toml_panel_id = module._project_editor_panel_id(toml_path, "pyproject", "file", "pyproject")
    toml_panel = fake_st.session_state["agilab:pinned_expanders"][toml_panel_id]
    assert toml_panel["title"] == "demo_project/pyproject.toml"
    assert toml_panel["body"] == toml_text
    assert toml_panel["body_format"] == "code"
    assert toml_panel["language"] == "toml"
    assert toml_panel["source"] == str(toml_path)


def test_project_editor_toolbar_buttons_preserves_dict_payload_shape():
    module = _load_project_module()
    base_buttons = [{"name": "Copy"}]

    dict_payload = module._project_editor_toolbar_buttons(
        {"buttons": base_buttons},
        pinned=False,
    )
    assert isinstance(dict_payload, list)
    dict_buttons = _extract_toolbar_buttons(dict_payload)
    assert dict_buttons[0]["name"] == "Copy"
    assert dict_buttons[1]["name"] == "Pin"
    assert dict_buttons[1]["commands"][-1] == ["response", module.EDITOR_PIN_RESPONSE]

    list_payload = module._project_editor_toolbar_buttons(
        base_buttons,
        pinned=True,
    )
    assert isinstance(list_payload, list)
    list_buttons = _extract_toolbar_buttons(list_payload)
    assert list_buttons[0]["name"] == "Copy"
    assert list_buttons[1]["name"] == "Unpin"
    assert list_buttons[1]["commands"][-1] == ["response", module.EDITOR_UNPIN_RESPONSE]

    empty_payload = module._project_editor_toolbar_buttons(None, pinned=False)
    assert isinstance(empty_payload, list)
    empty_buttons = _extract_toolbar_buttons(empty_payload)
    assert len(empty_buttons) == 1
    assert empty_buttons[0]["name"] == "Pin"


def test_update_function_source_action_preserves_module_context(tmp_path: Path):
    module = _load_project_module()
    target = tmp_path / "demo.py"
    target.write_text(
        "VALUE = 1\n\n"
        "def keep():\n"
        "    return VALUE\n\n"
        "def demo():\n"
        "    return 1\n",
        encoding="utf-8",
    )

    result = module._update_function_source_action(
        target,
        "def demo():\n    return 2\n",
        "demo",
        "module-level",
    )

    updated = target.read_text(encoding="utf-8")
    assert result.status == "success"
    assert "def keep" in updated
    assert "return VALUE" in updated
    assert "return 2" in updated
    assert "return 1" not in updated


def test_update_attributes_source_action_reports_invalid_class(tmp_path: Path):
    module = _load_project_module()
    target = tmp_path / "demo.py"
    target.write_text("class Demo:\n    value = 1\n", encoding="utf-8")

    result = module._update_attributes_source_action(target, "value = 2\n", "Missing")

    assert result.status == "error"
    assert result.title == "Error updating attributes."
    assert "Class 'Missing' not found" in str(result.detail)
    assert "value = 1" in target.read_text(encoding="utf-8")


def test_build_updated_function_source_rejects_non_function_code():
    module = _load_project_module()

    with pytest.raises(ValueError, match="must define a function or method"):
        module._build_updated_function_source(
            "def demo():\n    return 1\n",
            "value = 2\n",
            "demo",
            "module-level",
        )
