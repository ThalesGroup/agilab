from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from agilab import notebook_import_doctor as doctor


REPORT_PATH = Path("tools/notebook_import_doctor_report.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_notebook_import_doctor_detects_hidden_state_and_artifacts() -> None:
    fixture = Path.cwd() / "docs/source/data/notebook_pipeline_import_sample.ipynb"

    report = doctor.diagnose_notebook_file(fixture)

    assert report["schema"] == "agilab.notebook_import_doctor.v1"
    assert report["status"] == "warn"
    assert report["summary"]["hidden_global_count"] == 1
    assert report["artifact_contract"]["inputs"] == []
    assert report["artifact_contract"]["outputs"] == [
        "artifacts/summary.json",
        "data/flights.csv",
    ]
    assert report["artifact_contract"]["ambiguous"] == ["artifacts/trajectory.png"]
    hidden = [issue for issue in report["issues"] if issue["code"] == "hidden_global"]
    assert hidden[0]["location"] == "cell-4"
    assert hidden[0]["evidence"] == ["Path"]
    assert report["readiness_score"] == 80
    assert any("Move imports" in item for item in report["recommendations"])


def test_notebook_import_doctor_flags_risky_notebook(tmp_path: Path) -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 5,
                "source": [
                    "import pandas as pd\n",
                    "threshold = 10\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "source": ["print('peek')\n"],
            },
            {
                "cell_type": "code",
                "execution_count": 2,
                "source": [
                    "data = pd.read_csv('data/orders.csv')\n",
                    "result = data[data['value'] > threshold]\n",
                    "result.to_parquet('artifacts/orders.parquet')\n",
                ],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path = tmp_path / "risky.ipynb"
    path.write_text(json.dumps(notebook), encoding="utf-8")

    report = doctor.diagnose_notebook_file(path)

    codes = {issue["code"] for issue in report["issues"]}
    assert report["status"] == "warn"
    assert {"hidden_global", "partial_execution_counts", "execution_order_risk", "scratch_cell"} <= codes
    assert report["artifact_contract"]["inputs"] == ["data/orders.csv"]
    assert report["artifact_contract"]["outputs"] == ["artifacts/orders.parquet"]
    assert report["summary"]["scratch_cell_count"] == 1
    assert report["summary"]["hidden_global_count"] == 1
    assert report["readiness_score"] == 68


def test_notebook_import_doctor_keeps_local_function_arguments_local() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "source": [
                    "def normalize(value):\n",
                    "    return value.strip().lower()\n",
                    "\n",
                    "labels = [normalize(' Flight ')]\n",
                ],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    report = doctor.diagnose_notebook(notebook, source_notebook="functions.ipynb")

    assert report["status"] == "pass"
    assert report["summary"]["missing_name_count"] == 0
    assert report["cell_reports"][0]["missing_names"] == []


def test_notebook_import_doctor_report_persists_evidence(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_import_doctor_report_test_module")
    output_path = tmp_path / "doctor.json"

    report = module.build_report(output_path=output_path)

    assert report["report"] == "Notebook Import Doctor report"
    assert report["status"] == "pass"
    assert output_path.is_file()
    assert report["summary"]["doctor_status"] == "warn"
    assert report["summary"]["hidden_global_count"] == 1
    assert {check["id"] for check in report["checks"]} == {
        "notebook_import_doctor_schema",
        "notebook_import_doctor_artifacts",
        "notebook_import_doctor_hidden_state",
        "notebook_import_doctor_persistence",
    }


def test_notebook_import_doctor_report_handles_load_failure(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_import_doctor_report_failure_test_module")
    missing = tmp_path / "missing.ipynb"

    report = module.build_report(notebook_path=missing, output_path=tmp_path / "doctor.json")

    assert report["status"] == "fail"
    assert report["checks"][0]["id"] == "notebook_import_doctor_load"
    assert report["checks"][0]["evidence"] == [str(missing)]
