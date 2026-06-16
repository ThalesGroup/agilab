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
        if path.is_dir() and path.name.endswith("_project")
    }

    validation = module.validate_catalog(expected_pages=pages, expected_projects=projects)

    assert validation["status"] == "pass"


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
