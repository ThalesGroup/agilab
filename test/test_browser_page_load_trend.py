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
    assert total.latest_seconds == pytest.approx(2.6)
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
    assert "| TOTAL | 2.4000s | n/a | n/a | 2.4000s | 2.4000s | 1 |" in markdown


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


def test_main_rejects_negative_limit() -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as exc:
        module.main(["--limit", "-1"])

    assert exc.value.code == 2
