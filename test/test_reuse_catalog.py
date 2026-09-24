from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/agilab/reuse_catalog.py"
LAB_RUN_PATH = ROOT / "src/agilab/lab_run.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reuse_catalog_suggests_existing_network_view_and_project() -> None:
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_test_module")

    matches = module.suggest_reuse(
        "UAV relay route trajectory network map",
        kind="all",
        limit=6,
    )
    ids = {match["id"] for match in matches}

    assert "view_maps_network" in ids
    assert "uav_relay_queue_project" in ids


def test_reuse_catalog_reads_notebook_intent(tmp_path: Path) -> None:
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_notebook_test_module")
    notebook = tmp_path / "forecast.ipynb"
    notebook.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "source": [
                            "forecast_metrics = 'forecast_metrics.json'\n",
                            "predictions = 'forecast_predictions.csv'\n",
                        ],
                    }
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )

    report = module.build_suggestion_report(kind="all", from_path=notebook)
    ids = {match["id"] for match in report["matches"]}

    assert report["status"] == "match"
    assert "view_forecast_analysis" in ids
    assert "weather_forecast_project" in ids


def test_reuse_catalog_validation_covers_current_source_surfaces() -> None:
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_validation_test_module")
    pages = {
        path.name
        for path in (ROOT / "src/agilab/apps-pages").iterdir()
        if path.is_dir() and (path / "pyproject.toml").is_file()
    }
    projects = {
        path.name
        for path in (ROOT / "src/agilab/apps/builtin").iterdir()
        if path.is_dir()
        and path.name.endswith("_project")
        and (path / "pyproject.toml").is_file()
    }

    validation = module.validate_catalog(expected_pages=pages, expected_projects=projects)

    assert validation["status"] == "pass"


def test_repo_surface_discovery_ignores_empty_retired_project_directory(
    tmp_path: Path,
) -> None:
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_polluted_inventory_test_module")
    builtin_root = tmp_path / "src/agilab/apps/builtin"
    active_project = builtin_root / "active_project"
    active_project.mkdir(parents=True)
    (active_project / "pyproject.toml").write_text(
        "[project]\nname = 'active_project'\nversion = '1'\n",
        encoding="utf-8",
    )
    (builtin_root / "retired_project").mkdir()

    surfaces = module.discover_repo_surfaces(tmp_path)

    assert surfaces["project"] == {"active_project"}


def test_reuse_catalog_validation_requires_reuse_decision(tmp_path: Path) -> None:
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_policy_test_module")
    catalog = tmp_path / "reuse_catalog.toml"
    catalog.write_text(
        "\n".join(
            [
                'schema = "agilab.reuse_catalog.v1"',
                "",
                "[[page]]",
                'id = "demo_view"',
                'title = "Demo view"',
                'purpose = "Shows a demo view."',
                'when_to_use = "Use for demo review."',
                'inputs = ["demo.csv"]',
                'tags = ["demo"]',
                'reuse_policy = "Prefer this demo before creating another one."',
                "",
            ]
        ),
        encoding="utf-8",
    )

    validation = module.validate_catalog(
        catalog_path=catalog,
        expected_pages={"demo_view"},
    )

    assert validation["status"] == "fail"
    assert validation["errors"]["missing_fields"]["page:demo_view"] == [
        "reuse_decision",
        "reuse_rationale",
    ]


def test_reuse_changed_validation_requires_catalog_entry(tmp_path: Path) -> None:
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_changed_test_module")
    catalog = tmp_path / "reuse_catalog.toml"
    catalog.write_text('schema = "agilab.reuse_catalog.v1"\n', encoding="utf-8")
    page = tmp_path / "src/agilab/apps-pages/new_route_view"
    page.mkdir(parents=True)
    (page / "pyproject.toml").write_text(
        '[project]\nname = "new-route-view"\n',
        encoding="utf-8",
    )

    validation = module.validate_changed_surfaces(
        repo_root=tmp_path,
        catalog_path=catalog,
        changed_paths=["src/agilab/apps-pages/new_route_view/pyproject.toml"],
    )

    assert validation["status"] == "fail"
    assert validation["errors"]["missing_catalog_entries"] == [
        "page:new_route_view"
    ]


def test_lab_run_reuse_suggest_cli_outputs_matches(capsys) -> None:
    module = _load_module(LAB_RUN_PATH, "agilab_lab_run_reuse_catalog_test_module")

    result = module.main(["pages", "suggest", "latitude longitude map", "--limit", "2"])

    captured = capsys.readouterr()
    assert result == 0
    assert "view_maps" in captured.out


def test_lab_run_reuse_validate_cli_outputs_catalog_report(capsys) -> None:
    module = _load_module(LAB_RUN_PATH, "agilab_lab_run_reuse_validate_test_module")

    result = module.main(["reuse", "validate", "--json"])

    captured = capsys.readouterr()
    assert result == 0
    assert "agilab.reuse_catalog_validation.v1" in captured.out


def test_catalog_validation_reports_structural_errors_and_inventory_drift(tmp_path):
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_corrupt_test")
    catalog = tmp_path / "reuse_catalog.toml"
    assert module.load_catalog(catalog) == ()
    catalog.write_text("not valid [", encoding="utf-8")
    assert "load" in module.validate_catalog(catalog_path=catalog)["errors"]
    catalog.write_text(
        '[[page]]\nid = "duplicate"\nreuse_decision = "invented"\n'
        '[[page]]\nid = "duplicate"\nreuse_decision = "extend"\n'
        '[[project]]\nid = "orphan_project"\nreuse_decision = "new"\n',
        encoding="utf-8",
    )
    result = module.validate_catalog(catalog_path=catalog, expected_pages=["required"])
    assert result["status"] == "fail"
    assert result["errors"]["duplicate_ids"] == ["page:duplicate"]
    assert result["errors"]["invalid_reuse_decisions"] == {"page:duplicate": "invented"}
    assert result["errors"]["missing_checked_against"] == {
        "page:duplicate": "extend", "project:orphan_project": "new",
    }
    assert result["errors"]["coverage"]["page"] == {"missing": ["required"], "extra": ["duplicate"]}
    assert "inputs" in result["errors"]["missing_fields"]["page:duplicate"]
    assert "artifacts" in result["errors"]["missing_fields"]["project:orphan_project"]
    catalog.write_text('page = [1, "ignored"]\nproject = "not-a-list"\n', encoding="utf-8")
    assert module.load_catalog(catalog) == ()


def test_reuse_source_extraction_reads_bounded_text_directory_and_notebook_outputs(tmp_path):
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_extraction_test")
    assert module.text_from_path(tmp_path / "missing") == str(tmp_path / "missing")
    large = tmp_path / "long.txt"
    large.write_text("a" * (module.MAX_SOURCE_CHARS + 1), encoding="utf-8")
    assert len(module.text_from_path(large)) == module.MAX_SOURCE_CHARS
    project = tmp_path / "project"
    (project / "src" / "pkg").mkdir(parents=True)
    (project / "README.md").write_text("root intent", encoding="utf-8")
    (project / "src" / "lab_stages.toml").write_text("stages intent", encoding="utf-8")
    (project / "src" / "pkg" / "pyproject.toml").write_text("package intent", encoding="utf-8")
    text = module.text_from_path(project)
    assert all(term in text for term in ["root intent", "stages intent", "package intent"])
    notebook = tmp_path / "mixed.IPYNB"
    notebook.write_text(json.dumps({
        "metadata": {"intent": "network"}, "cells": [
            None, {"source": "single string", "outputs": [None, {"data": {"text/plain": "result"}}]},
            {"source": ["line a", 2], "outputs": "ignored"},
        ],
    }), encoding="utf-8")
    text = module.text_from_path(notebook)
    assert all(term in text for term in ["network", "single string", "result", "line a", "2"])


def test_changed_path_inventory_combines_successes_and_retains_paths_with_spaces(tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_git_inventory_test")
    calls = []
    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if "--cached" in command:
            raise subprocess.CalledProcessError(1, command)
        if "ls-files" in command:
            return SimpleNamespace(stdout="new path.py\0same.py\0")
        return SimpleNamespace(stdout="same.py\0tracked.py\0")
    monkeypatch.setitem(module.git_changed_paths.__globals__, "subprocess",
                        SimpleNamespace(run=fake_run, CalledProcessError=subprocess.CalledProcessError))
    assert module.git_changed_paths(tmp_path, base_ref="origin/main") == ("new path.py", "same.py", "tracked.py")
    assert len(calls) == 3
    assert calls[0][0][-2:] == ("origin/main", "--")
    assert all(call[1]["cwd"] == tmp_path for call in calls)


def test_changed_surface_similarity_requires_explicit_acknowledgement(tmp_path):
    module = _load_module(MODULE_PATH, "agilab_reuse_catalog_similarity_contract_test")
    pages = tmp_path / "src/agilab/apps-pages"
    pages.mkdir(parents=True)
    for name in ("first", "second"):
        (pages / f"{name}.py").write_text("forecast metric analysis", encoding="utf-8")
    catalog = tmp_path / "reuse_catalog.toml"
    def write_catalog(acknowledged):
        rows = []
        for name in ("first", "second"):
            rows.append(
                f'[[page]]\nid = "{name}"\ntitle = "forecast metric analysis"\n'
                'purpose = "forecast metric analysis"\nwhen_to_use = "forecast metrics"\n'
                'tags = ["forecast", "metric", "analysis"]\ninputs = ["forecast.csv"]\n'
                'reuse_policy = "reuse"\nreuse_decision = "reuse"\nreuse_rationale = "existing"\n'
                + ('checked_against = ["page:second"]\n' if name == "first" and acknowledged else "")
            )
        catalog.write_text("\n".join(rows), encoding="utf-8")
    write_catalog(False)
    changed = ["src/agilab/apps-pages/first.py", "src/agilab/apps-pages/templates/template.py", "README.md"]
    result = module.validate_changed_surfaces(repo_root=tmp_path, changed_paths=changed, catalog_path=catalog, similarity_threshold=1)
    assert result["changed_surfaces"] == ["page:first"]
    assert result["errors"]["unacknowledged_similarity"]["page:first"][0]["match"] == "page:second"
    write_catalog(True)
    result = module.validate_changed_surfaces(repo_root=tmp_path, changed_paths=changed, catalog_path=catalog, similarity_threshold=1)
    assert result["status"] == "pass"
    assert result["errors"] == {}
