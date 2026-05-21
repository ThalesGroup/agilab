from __future__ import annotations

import base64
import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/ui_visual_baseline_report.py").resolve()
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _load_module():
    spec = importlib.util.spec_from_file_location("ui_visual_baseline_report_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_manifest(module, root: Path, image_name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / image_name).write_bytes(PNG_1X1)
    manifest = module.SCREENSHOTS.build_page_shots_manifest(root, created_at="2026-05-18T00:00:00Z")
    path = module.SCREENSHOTS.screenshot_manifest_path(root)
    module.SCREENSHOTS.write_screenshot_manifest(manifest, path)
    return path


def test_visual_baseline_report_matches_normalized_page_names(tmp_path) -> None:
    module = _load_module()
    current = _write_manifest(module, tmp_path / "current", "flight_telemetry_project-PROJECT-success.png")
    baseline = _write_manifest(module, tmp_path / "baseline", "project-page.png")

    report = module.build_report(
        current_manifest_path=current,
        baseline_manifest_path=baseline,
        max_diff_ratio=0.0,
        channel_threshold=10,
        allow_missing_baseline=False,
    )

    assert report["schema"] == module.SCHEMA
    assert report["success"] is True
    assert report["comparisons"][0]["page"] == "project"
    assert report["comparisons"][0]["status"] == "matched"


def test_visual_baseline_report_can_warn_on_missing_baseline(tmp_path) -> None:
    module = _load_module()
    current = _write_manifest(module, tmp_path / "current", "flight_telemetry_project-SETTINGS-success.png")
    baseline = _write_manifest(module, tmp_path / "baseline", "project-page.png")

    report = module.build_report(
        current_manifest_path=current,
        baseline_manifest_path=baseline,
        max_diff_ratio=0.0,
        channel_threshold=10,
        allow_missing_baseline=True,
    )

    assert report["success"] is True
    assert report["summary"]["warning_count"] == 1
    assert report["comparisons"][0]["status"] == "warning"


def test_visual_baseline_report_fails_on_missing_baseline_by_default(tmp_path) -> None:
    module = _load_module()
    current = _write_manifest(module, tmp_path / "current", "flight_telemetry_project-SETTINGS-success.png")
    baseline = _write_manifest(module, tmp_path / "baseline", "project-page.png")

    report = module.build_report(
        current_manifest_path=current,
        baseline_manifest_path=baseline,
        max_diff_ratio=0.0,
        channel_threshold=10,
        allow_missing_baseline=False,
    )
    text = module.render_human(report)

    assert report["success"] is False
    assert report["summary"]["failed_count"] == 1
    assert report["comparisons"][0]["status"] == "failed"
    assert "no baseline screenshot" in text


def test_visual_baseline_report_accepts_manifest_directory_paths(tmp_path) -> None:
    module = _load_module()
    current_dir = tmp_path / "current"
    baseline_dir = tmp_path / "baseline"
    _write_manifest(module, current_dir, "project-page.png")
    _write_manifest(module, baseline_dir, "project-page.png")

    report = module.build_report(
        current_manifest_path=current_dir,
        baseline_manifest_path=baseline_dir,
        max_diff_ratio=0.0,
        channel_threshold=10,
        allow_missing_baseline=False,
    )

    assert report["success"] is True
    assert report["current_manifest"].endswith(module.SCREENSHOTS.SCREENSHOT_MANIFEST_FILENAME)
    assert report["baseline_manifest"].endswith(module.SCREENSHOTS.SCREENSHOT_MANIFEST_FILENAME)


def test_visual_baseline_report_json_cli_writes_output(tmp_path, capsys) -> None:
    module = _load_module()
    current = _write_manifest(module, tmp_path / "current", "project-page.png")
    baseline = _write_manifest(module, tmp_path / "baseline", "project-page.png")
    output = tmp_path / "report.json"

    exit_code = module.main(
        [
            "--current",
            str(current),
            "--baseline",
            str(baseline),
            "--output",
            str(output),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == module.SCHEMA


def test_visual_baseline_report_advisory_cli_preserves_failed_report(tmp_path, capsys) -> None:
    module = _load_module()
    current = _write_manifest(module, tmp_path / "current", "settings-page.png")
    baseline = _write_manifest(module, tmp_path / "baseline", "project-page.png")

    strict_exit = module.main(["--current", str(current), "--baseline", str(baseline), "--json"])
    capsys.readouterr()
    advisory_exit = module.main(["--current", str(current), "--baseline", str(baseline), "--advisory", "--json"])

    assert strict_exit == 1
    assert advisory_exit == 0
    assert json.loads(capsys.readouterr().out)["success"] is False
