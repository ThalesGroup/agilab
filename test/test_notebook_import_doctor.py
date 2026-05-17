from __future__ import annotations

import importlib.util
import json
import sys
import types
import ast
from pathlib import Path

REPORT_PATH = Path("tools/notebook_import_doctor_report.py").resolve()
DOCTOR_PATH = Path("src/agilab/notebook_import_doctor.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_agilab_module(path: Path, name: str):
    package = types.ModuleType("agilab")
    package.__path__ = [str(Path("src/agilab").resolve())]
    sys.modules["agilab"] = package
    return _load_module(path, name)


doctor = _load_agilab_module(DOCTOR_PATH, "agilab.notebook_import_doctor")


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


def test_notebook_import_doctor_reports_syntax_and_missing_names() -> None:
    notebook = {
        "cells": [
            {"cell_type": "code", "execution_count": 1, "source": ["value = \n"]},
            {"cell_type": "code", "execution_count": 2, "source": ["result = missing_value + 1\n"]},
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    report = doctor.diagnose_notebook(notebook, source_notebook="bad.ipynb")
    codes = {issue["code"] for issue in report["issues"]}

    assert report["status"] == "fail"
    assert {"syntax_error", "missing_name"} <= codes
    assert report["cell_reports"][0]["role"] == "invalid"
    assert report["readiness_score"] == 50
    assert any("undefined names" in item for item in report["recommendations"])


def test_notebook_import_doctor_detects_tuple_bindings_keyword_paths_and_load_role() -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": 1,
                "source": [
                    "from pathlib import Path\n",
                    "output_path = Path('artifacts/out.txt')\n",
                    "data = read_csv(filepath_or_buffer='data/input.csv')\n",
                    "Path(output_path).write_text('done')\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": 2,
                "source": ["data = load(path='models/model.pkl')\n"],
            },
        ],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    report = doctor.diagnose_notebook(notebook, source_notebook="paths.ipynb")

    assert report["artifact_contract"]["inputs"] == ["data/input.csv", "models/model.pkl"]
    assert report["artifact_contract"]["outputs"] == ["artifacts/out.txt"]
    assert report["cell_reports"][1]["role"] == "load"
    assert doctor._target_names(ast.parse("(left, (right,)) = (1, (2,))").body[0].targets[0]) == [
        "left",
        "right",
    ]


def test_notebook_import_doctor_helper_edges_cover_empty_and_low_score_cases(tmp_path: Path) -> None:
    tree = ast.parse("read_json(fname='data/input.json')\nsavefig('plots/result.png')\n")
    contract = doctor._artifact_contract(tree, {})

    assert contract["inputs"] == ["data/input.json"]
    assert contract["outputs"] == ["plots/result.png"]
    assert doctor._looks_like_artifact("") is False
    assert doctor._cell_role(ast.parse("value = 1\n"), {"inputs": [], "outputs": []}) == "transform"
    assert doctor._readiness_score(
        [
            doctor.NotebookImportDoctorIssue("error", "e", "a", "b"),
            doctor.NotebookImportDoctorIssue("warning", "w", "a", "b"),
            doctor.NotebookImportDoctorIssue("info", "i", "a", "b"),
        ]
        * 4
    ) == 0

    output_path = doctor.write_doctor_report(tmp_path / "nested" / "doctor.json", {"ok": True})
    assert output_path.read_text(encoding="utf-8") == '{\n  "ok": true\n}\n'
