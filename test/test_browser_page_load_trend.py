from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path("tools/browser_page_load_trend.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("browser_page_load_trend_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_artifact(path: Path, *, about: float, analysis: float, total: float) -> None:
    path.write_text(
        json.dumps(
            {
                "success": True,
                "total_duration_seconds": total,
                "steps": [
                    {
                        "label": "ABOUT first visible render",
                        "success": True,
                        "duration_seconds": about,
                    },
                    {
                        "label": "ANALYSIS first visible render",
                        "success": True,
                        "duration_seconds": analysis,
                    },
                    {
                        "label": "page-load advisory budget",
                        "success": True,
                        "duration_seconds": 0.0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_extract_samples_derive_total_from_page_render_steps(tmp_path: Path) -> None:
    module = _load_module()
    artifact = tmp_path / "mixed-page-load.json"
    _write_artifact(artifact, about=0.4, analysis=0.6, total=10.0)

    trends = {trend.page: trend for trend in module.collect_trends([artifact])}

    assert trends["TOTAL"].latest_seconds == pytest.approx(1.0)


def test_extract_samples_ignore_top_level_total_without_page_steps(tmp_path: Path) -> None:
    module = _load_module()
    artifact = tmp_path / "failed-page-load.json"
    artifact.write_text(
        json.dumps(
            {
                "success": False,
                "total_duration_seconds": 9.5,
                "steps": [
                    {
                        "label": "streamlit health",
                        "success": True,
                        "duration_seconds": 1.2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert module.collect_trends([artifact]) == []


def test_collect_trends_reports_latest_previous_delta_best_and_worst(tmp_path: Path) -> None:
    module = _load_module()
    first = tmp_path / "first-page-load.json"
    second = tmp_path / "second-page-load.json"
    _write_artifact(first, about=0.9, analysis=0.7, total=2.8)
    _write_artifact(second, about=0.6, analysis=0.8, total=2.6)
    os.utime(first, ns=(100, 100))
    os.utime(second, ns=(200, 200))

    trends = {trend.page: trend for trend in module.collect_trends([second, first])}

    about = trends["ABOUT"]
    assert about.latest_seconds == pytest.approx(0.6)
    assert about.previous_seconds == pytest.approx(0.9)
    assert about.delta_seconds == pytest.approx(-0.3)
    assert about.best_seconds == pytest.approx(0.6)
    assert about.worst_seconds == pytest.approx(0.9)
    assert about.samples == 2
    assert about.artifact == second.as_posix()

    total = trends["TOTAL"]
    assert total.latest_seconds == pytest.approx(1.4)
    assert total.delta_seconds == pytest.approx(-0.2)


def test_render_markdown_includes_core_page_rows(tmp_path: Path) -> None:
    module = _load_module()
    artifact = tmp_path / "sample-page-load.json"
    _write_artifact(artifact, about=0.61, analysis=0.73, total=2.4)

    trends = module.collect_trends([artifact])
    markdown = module.render_markdown(trends, pattern="test-results/*page-load*.json")

    assert "# Browser page-load trend" in markdown
    assert "| ABOUT | 0.6100s | n/a | n/a | 0.6100s | 0.6100s | 1 |" in markdown
    assert "| ANALYSIS | 0.7300s | n/a | n/a | 0.7300s | 0.7300s | 1 |" in markdown
    assert "| TOTAL | 1.3400s | n/a | n/a | 1.3400s | 1.3400s | 1 |" in markdown


def test_main_json_and_allow_empty(tmp_path: Path, monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.chdir(tmp_path)

    assert module.main(["--pattern", "missing/*.json", "--allow-empty"]) == 0
    assert "No browser page-load artifacts" in capsys.readouterr().out

    artifact_dir = tmp_path / "test-results"
    artifact_dir.mkdir()
    _write_artifact(artifact_dir / "one-page-load.json", about=0.4, analysis=0.6, total=1.5)

    assert module.main(["--pattern", "test-results/*page-load*.json", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pattern"] == "test-results/*page-load*.json"
    assert {trend["page"] for trend in payload["trends"]} == {"ABOUT", "ANALYSIS", "TOTAL"}


def test_main_fails_when_latest_regression_exceeds_threshold(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = _load_module()
    monkeypatch.chdir(tmp_path)
    artifact_dir = tmp_path / "test-results"
    artifact_dir.mkdir()
    first = artifact_dir / "first-page-load.json"
    second = artifact_dir / "second-page-load.json"
    _write_artifact(first, about=0.5, analysis=0.7, total=1.5)
    _write_artifact(second, about=0.9, analysis=0.71, total=2.2)
    os.utime(first, ns=(100, 100))
    os.utime(second, ns=(200, 200))

    result = module.main(
        [
            "--pattern",
            "test-results/*page-load*.json",
            "--max-regression-seconds",
            "0.2",
        ]
    )
    captured = capsys.readouterr()

    assert result == 2
    assert "Browser page-load regression gate failed" in captured.err
    assert "ABOUT +0.4000s" in captured.err
    assert "TOTAL +0.4100s" in captured.err
    assert "ANALYSIS" not in captured.err


def test_main_json_reports_regression_gate_result(tmp_path: Path, monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.chdir(tmp_path)
    artifact_dir = tmp_path / "test-results"
    artifact_dir.mkdir()
    first = artifact_dir / "first-page-load.json"
    second = artifact_dir / "second-page-load.json"
    _write_artifact(first, about=0.5, analysis=0.7, total=1.5)
    _write_artifact(second, about=0.55, analysis=0.71, total=1.6)
    os.utime(first, ns=(100, 100))
    os.utime(second, ns=(200, 200))

    assert (
        module.main(
            [
                "--pattern",
                "test-results/*page-load*.json",
                "--json",
                "--max-regression-seconds",
                "0.2",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["max_regression_seconds"] == pytest.approx(0.2)
    assert payload["regressions"] == []


def test_main_rejects_negative_limit() -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as exc:
        module.main(["--limit", "-1"])

    assert exc.value.code == 2


def test_main_rejects_negative_regression_threshold() -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as exc:
        module.main(["--max-regression-seconds", "-0.1"])

    assert exc.value.code == 2
