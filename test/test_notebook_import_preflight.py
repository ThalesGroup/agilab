from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPORT_PATH = Path("tools/notebook_import_preflight.py").resolve()
CORE_PATH = Path("src/agilab/notebook_pipeline_import.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _risky_notebook() -> dict[str, object]:
    return {
        "cells": [
            {
                "cell_type": "markdown",
                "source": ["# Risky import\n", "Notebook migration preflight should flag generic cleanup work."],
            },
            {
                "cell_type": "code",
                "source": [
                    "!pip install requests\n",
                    "from pathlib import Path\n",
                    "import pandas as pd\n",
                    "import requests\n",
                    "raw = pd.read_csv('data/orders.csv')\n",
                    "requests.get('https://example.invalid/data')\n",
                    "Path('/tmp/local-only.csv').write_text('debug')\n",
                    "raw.to_parquet('artifacts/orders.parquet')\n",
                ],
            },
        ],
        "metadata": {"kernelspec": {"name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def test_notebook_import_preflight_flags_generic_risks_and_contract(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_import_preflight_core_test_module")
    imported = core_module.build_notebook_pipeline_import(
        notebook=_risky_notebook(),
        source_notebook="risky.ipynb",
    )

    preflight = core_module.build_notebook_import_preflight(imported)
    contract_path = core_module.write_notebook_import_contract(
        tmp_path / "notebook_import_contract.json",
        imported,
        preflight=preflight,
        module_name="demo_project",
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    assert preflight["schema"] == "agilab.notebook_import_preflight.v1"
    assert preflight["status"] == "review"
    assert preflight["safe_to_import"] is True
    assert preflight["cleanup_required"] is True
    assert preflight["summary"]["pipeline_step_count"] == 1
    assert preflight["artifact_contract"]["inputs"] == ["data/orders.csv"]
    assert "/tmp/local-only.csv" in preflight["artifact_contract"]["outputs"]
    assert "artifacts/orders.parquet" in preflight["artifact_contract"]["outputs"]
    assert {
        risk["rule"]
        for risk in preflight["risks"]
        if risk["level"] == "warning"
    } >= {
        "dependency_install",
        "shell_execution",
        "network_access",
        "absolute_path",
        "absolute_artifact_path",
    }
    assert contract["schema"] == "agilab.notebook_import_contract.v1"
    assert contract["module_name"] == "demo_project"
    assert contract["preflight"]["status"] == "review"
    assert contract["artifact_contract"] == preflight["artifact_contract"]
    assert contract["warnings"]
    assert contract["steps"][0]["id"] == "cell-2"


def test_notebook_import_preflight_report_writes_contract(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_import_preflight_report_test_module")
    notebook_path = tmp_path / "risky.ipynb"
    output_path = tmp_path / "contract.json"
    notebook_path.write_text(json.dumps(_risky_notebook()), encoding="utf-8")

    report = module.build_report(
        repo_root=Path.cwd(),
        notebook_path=notebook_path,
        output_path=output_path,
        module_name="demo_project",
    )

    assert report["report"] == "Notebook import preflight report"
    assert report["status"] == "pass"
    assert report["summary"]["risk_status"] == "review"
    assert report["summary"]["safe_to_import"] is True
    assert report["summary"]["contract_path"] == str(output_path)
    assert output_path.is_file()
    assert {check["id"] for check in report["checks"]} == {
        "notebook_import_preflight_importable",
        "notebook_import_preflight_risks",
        "notebook_import_preflight_artifacts",
        "notebook_import_preflight_lab_steps_preview",
        "notebook_import_preflight_contract_write",
    }


def test_notebook_import_preflight_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_import_preflight_report_failure_test_module")
    missing = tmp_path / "missing.ipynb"

    report = module.build_report(repo_root=Path.cwd(), notebook_path=missing)

    assert report["status"] == "fail"
    assert report["summary"]["risk_status"] == "blocked"
    assert report["checks"][0]["id"] == "notebook_import_preflight_load"
