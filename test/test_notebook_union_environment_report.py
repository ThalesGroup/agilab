from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPORT_PATH = Path("tools/notebook_union_environment_report.py").resolve()
CORE_PATH = Path("src/agilab/notebook_union_environment.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_notebook_union_environment_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "notebook_union_environment_report_test_module")

    report = module.build_report(repo_root=Path.cwd(), output_dir=tmp_path)

    assert report["report"] == "Notebook union-environment report"
    assert report["status"] == "pass"
    assert report["summary"]["compatible_union_mode"] == "single_kernel_union_candidate"
    assert report["summary"]["incompatible_union_mode"] == "supervisor_notebook_required"
    assert report["summary"]["compatible_stage_count"] == 2
    assert report["summary"]["incompatible_issue_count"] >= 2
    assert report["summary"]["code_cell_count"] == 2
    assert Path(report["summary"]["notebook_path"]).is_file()
    assert {check["id"] for check in report["checks"]} == {
        "notebook_union_environment_compatible_plan",
        "notebook_union_environment_notebook_render",
        "notebook_union_environment_mixed_runtime_guard",
        "notebook_union_environment_execution_boundary",
        "notebook_union_environment_docs_reference",
    }


def test_notebook_union_environment_blocks_mixed_runtime_and_env() -> None:
    report_module = _load_module(
        REPORT_PATH,
        "notebook_union_environment_report_fixture_module",
    )
    core_module = _load_module(CORE_PATH, "notebook_union_environment_core_test_module")

    plan = core_module.build_union_environment_plan(report_module.incompatible_lab_stages())

    assert plan["run_status"] == "supervisor_required"
    assert plan["union_mode"] == "supervisor_notebook_required"
    assert plan["summary"]["compatible"] is False
    assert {issue["location"] for issue in plan["issues"]} == {
        "runtime",
        "environment",
    }


def test_notebook_union_environment_skips_non_executable_stage_entries(tmp_path: Path) -> None:
    core_module = _load_module(CORE_PATH, "notebook_union_environment_core_edge_test_module")

    plan = core_module.build_union_environment_plan(
        {
            "__meta__": [{"C": "ignored"}],
            "not_a_list": {"C": "ignored"},
            "worker": [
                "not a dict",
                {"C": "   "},
            ],
        },
        run_id="empty-proof",
    )

    assert plan["run_status"] == "supervisor_required"
    assert plan["summary"]["stage_count"] == 0
    assert plan["issues"] == [
        {
            "level": "error",
            "location": "stages",
            "message": "no executable pipeline stages found",
        }
    ]
    with pytest.raises(ValueError, match="union notebook"):
        core_module.build_union_notebook(plan)

    compatible = core_module.build_union_environment_plan({"worker": [{"D": "ok", "C": "x = 1"}]})
    compatible["stages"].insert(0, "metadata")
    notebook = core_module.build_union_notebook(compatible)
    assert [cell["cell_type"] for cell in notebook["cells"]] == ["markdown", "markdown", "code"]

    plan_path = core_module.write_union_environment_plan(tmp_path / "nested" / "plan.json", compatible)
    notebook_path = core_module.write_union_notebook(tmp_path / "nested" / "union.ipynb", notebook)
    assert plan_path.is_file()
    assert notebook_path.is_file()
