from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest


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


def test_expand_paths_deduplicates_and_skips_non_files(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    results = tmp_path / "test-results"
    results.mkdir()
    junit = results / "junit-agi-gui-support.xml"
    junit.write_text("<testsuites />", encoding="utf-8")
    directory_match = results / "junit-agi-gui-directory.xml"
    directory_match.mkdir()

    paths = module._expand_paths(
        [
            "test-results/junit-agi-gui-*.xml",
            "test-results/junit-agi-gui-support.xml",
        ]
    )

    assert paths == [junit]


def test_load_records_handles_artifact_directory_chunks_and_bad_junit(tmp_path: Path, capsys) -> None:
    module = _load_module()
    artifact_dir = tmp_path / "coverage-gui-junit-custom"
    artifact_dir.mkdir()
    junit = artifact_dir / "results.xml"
    bad_junit = artifact_dir / "bad.xml"
    _write_junit(
        junit,
        [
            ("", "missing_classname", "not-a-number"),
            ("test_lonely_module", "top_level", -3.0),
            ("package.test_nested", "nested", 0.5),
        ],
    )
    bad_junit.write_text("<testsuites>", encoding="utf-8")

    records = module.load_records([str(junit), str(bad_junit)])

    assert [record.chunk for record in records] == ["custom", "custom", "custom"]
    assert [record.test_path for record in records] == [
        "unknown",
        "test/test_lonely_module.py",
        "package/test_nested.py",
    ]
    assert [record.seconds for record in records] == [0.0, 0.0, 0.5]
    assert "ignoring unreadable JUnit" in capsys.readouterr().err


def test_unknown_chunks_sort_after_known_chunks_when_tied() -> None:
    module = _load_module()

    known = module.ChunkTiming(chunk="support", files=1, tests=1, seconds=1.0, percentage=50.0)
    unknown = module.ChunkTiming(chunk="custom", files=1, tests=1, seconds=1.0, percentage=50.0)

    assert sorted([unknown, known], key=module._chunk_sort_key) == [known, unknown]
    assert module._chunk_from_path(Path("plain-results.xml")) == "unknown"


def test_empty_chunk_markers_fall_back_to_unknown() -> None:
    module = _load_module()

    assert module._chunk_from_path(Path("junit-agi-gui-.xml")) == "unknown"
    assert module._chunk_from_path(Path("coverage-gui-junit-") / "results.xml") == "unknown"


def test_render_markdown_handles_positive_report_without_slowest_chunk() -> None:
    module = _load_module()
    report = module.TimingReport(
        sources=("synthetic.xml",),
        chunks=(),
        files=(),
        slow_tests=(),
        total_tests=1,
        total_seconds=0.0,
        slowest_chunk=None,
        imbalance_ratio=0.0,
    )

    markdown = module.render_markdown(report)

    assert "Slowest chunk" not in markdown
    assert "## Chunks" in markdown


def test_script_entrypoint_writes_empty_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "missing-junit-*.xml"])

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")

    assert exc.value.code == 0
    assert "No AGI-GUI JUnit timing files were found." in capsys.readouterr().out
