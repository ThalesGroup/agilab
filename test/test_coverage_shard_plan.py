from __future__ import annotations

import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


MODULE_PATH = Path("tools/coverage_shard_plan.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("coverage_shard_plan_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_junit(path: Path, cases: list[tuple[str, str, float]]) -> None:
    testsuite = ET.Element("testsuite")
    for classname, name, seconds in cases:
        ET.SubElement(
            testsuite,
            "testcase",
            {
                "classname": classname,
                "name": name,
                "time": str(seconds),
            },
        )
    path.write_text(ET.tostring(testsuite, encoding="unicode"), encoding="utf-8")


def _item_chunk(plan, item_id: str) -> str:
    for shard in plan.shards:
        for item in shard.items:
            if item["id"] == item_id:
                return shard.name
    raise AssertionError(f"missing item {item_id}")


def test_static_plan_preserves_fallback_chunks_when_timings_are_missing(tmp_path) -> None:
    module = _load_module()

    plan = module.build_plan([str(tmp_path / "missing-*.xml")])
    chunks = {shard.name: list(shard.pytest_args) for shard in plan.shards}

    assert plan.mode == "static"
    assert list(chunks) == list(module.AGI_GUI_CHUNKS)
    assert "src/agilab/lib/agi-gui/test" in chunks["support"]
    assert chunks["pages-flow"] == [
        "test/test_ui_pages.py",
        "-k",
        "execute_page or experiment_page or pipeline_page_project_selectbox",
    ]
    assert "test/test_*_report.py" in chunks["reports"]


def test_timing_balanced_plan_greedily_spreads_slow_files(tmp_path) -> None:
    module = _load_module()
    junit_path = tmp_path / "junit-agi-gui-support.xml"
    _write_junit(
        junit_path,
        [
            ("test.test_pipeline_ai", "test_pipeline", 30.0),
            ("test.test_agilab_widget_robot", "test_widget_robot", 20.0),
            ("test.test_first_launch_robot", "test_first_launch", 10.0),
        ],
    )

    plan = module.build_plan([str(junit_path)], default_seconds=0.0)

    assert plan.mode == "timing-balanced"
    assert len(
        {
            _item_chunk(plan, "test/test_pipeline_ai.py"),
            _item_chunk(plan, "test/test_agilab_widget_robot.py"),
            _item_chunk(plan, "test/test_first_launch_robot.py"),
        }
    ) == 3


def test_selector_chunks_stay_locked_when_balancing(tmp_path) -> None:
    module = _load_module()
    flow_junit = tmp_path / "junit-agi-gui-pages-flow.xml"
    rest_junit = tmp_path / "junit-agi-gui-pages-rest.xml"
    _write_junit(flow_junit, [("test.test_ui_pages", "test_execute_page", 50.0)])
    _write_junit(rest_junit, [("test.test_ui_pages", "test_sidebar", 40.0)])

    plan = module.build_plan([str(flow_junit), str(rest_junit)], default_seconds=0.0)
    chunks = {shard.name: shard for shard in plan.shards}

    assert chunks["pages-flow"].pytest_args == (
        "test/test_ui_pages.py",
        "-k",
        "execute_page or experiment_page or pipeline_page_project_selectbox",
    )
    assert chunks["pages-flow"].item_count == 1
    assert chunks["pages-rest"].pytest_args[:3] == (
        "test/test_ui_pages.py",
        "-k",
        "not (execute_page or experiment_page or pipeline_page_project_selectbox)",
    )
    assert chunks["pages-rest"].items[0]["locked"] is True


def test_write_plan_files_and_print_args_round_trip(tmp_path, capsys) -> None:
    module = _load_module()
    plan = module.build_plan([str(tmp_path / "missing-*.xml")])
    plan_path = module._write_plan_files(plan, tmp_path / "plan")

    assert plan_path == tmp_path / "plan" / "plan.json"
    assert (tmp_path / "plan" / "support.json").is_file()
    assert json.loads(plan_path.read_text(encoding="utf-8"))["schema"] == module.SCHEMA
    assert module.main(["print-args", "--plan", str(plan_path), "--chunk", "reports"]) == 0

    printed = capsys.readouterr().out.splitlines()
    assert printed == ["test/test_ci_provider_artifacts.py", "test/test_*_report.py"]
