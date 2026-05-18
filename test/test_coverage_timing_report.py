from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/coverage_timing_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("coverage_timing_report_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_junit(path: Path, cases: list[tuple[str, str, float]]) -> None:
    body = "\n".join(
        f'    <testcase classname="{classname}" name="{name}" time="{seconds}" />'
        for classname, name, seconds in cases
    )
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
{body}
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )


def test_build_report_summarizes_chunks_files_and_slowest_tests(tmp_path: Path) -> None:
    module = _load_module()
    pages = tmp_path / "junit-agi-gui-pages-flow.xml"
    views = tmp_path / "junit-agi-gui-views.xml"
    _write_junit(
        pages,
        [
            ("test.test_ui_pages", "test_sidebar", 3.0),
            ("test.test_ui_pages", "test_project", 2.0),
            ("test.test_app_args", "test_form", 1.0),
        ],
    )
    _write_junit(
        views,
        [
            ("test.test_view_maps", "test_map", 1.5),
            ("test.test_view_maps", "test_network", 0.5),
        ],
    )

    report = module.build_report([str(pages), str(views)], top_files=2, top_tests=2)

    assert report.total_tests == 5
    assert report.total_seconds == 8.0
    assert report.slowest_chunk == "pages-flow"
    assert report.chunks[0].chunk == "pages-flow"
    assert report.chunks[0].tests == 3
    assert report.chunks[0].files == 2
    assert report.files[0].test_path == "test/test_ui_pages.py"
    assert report.files[0].seconds == 5.0
    assert report.slow_tests[0].test_name == "test_sidebar"


def test_render_markdown_highlights_slowest_chunk_and_files(tmp_path: Path) -> None:
    module = _load_module()
    junit = tmp_path / "junit-agi-gui-pages-flow.xml"
    _write_junit(junit, [("test.test_ui_pages", "test_sidebar", 61.25)])

    markdown = module.render_markdown(module.build_report([str(junit)]))

    assert "# AGI-GUI Coverage Timing" in markdown
    assert "Slowest chunk: `pages-flow`" in markdown
    assert "`test/test_ui_pages.py`" in markdown
    assert "1m 1.2s" in markdown


def test_main_writes_markdown_and_json_outputs(tmp_path: Path, capsys) -> None:
    module = _load_module()
    junit = tmp_path / "junit-agi-gui-robots.xml"
    markdown_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"
    _write_junit(junit, [("test.test_agilab_widget_robot", "test_robot", 0.25)])

    exit_code = module.main(
        [
            str(junit),
            "--markdown-output",
            str(markdown_path),
            "--json-output",
            str(json_path),
            "--format",
            "json",
        ]
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert markdown_path.read_text(encoding="utf-8").startswith("# AGI-GUI Coverage Timing")
    assert payload["slowest_chunk"] == "robots"
    assert payload["chunks"][0]["seconds"] == 0.25
    assert json.loads(capsys.readouterr().out)["total_tests"] == 1


def test_missing_junit_files_emit_empty_report(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["missing-junit-*.xml"])

    assert exit_code == 0
    assert "No AGI-GUI JUnit timing files were found." in capsys.readouterr().out
