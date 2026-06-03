from __future__ import annotations

import base64
import builtins
import importlib.util
import json
import runpy
import struct
import sys
from pathlib import Path
import zlib


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


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _write_single_record_manifest(module, root: Path, image_name: str, *, page: str, data: bytes) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    image_path = root / image_name
    image_path.write_bytes(data)
    record = module.SCREENSHOTS.build_screenshot_record(
        image_path,
        page=page,
        root=root,
        created_at="2026-05-18T00:00:00Z",
    )
    manifest = module.SCREENSHOTS.build_screenshot_manifest(
        [record],
        root=root,
        created_at="2026-05-18T00:00:00Z",
    )
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
    assert "- project:" not in module.render_human(report)


def test_visual_baseline_report_load_manifest_module_rejects_missing_spec(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)

    try:
        module._load_screenshot_manifest_module()
    except RuntimeError as exc:
        assert "Could not load screenshot manifest module" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected screenshot manifest import failure")


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


def test_visual_baseline_report_fails_on_dimension_mismatch(tmp_path) -> None:
    module = _load_module()
    current = _write_single_record_manifest(
        module,
        tmp_path / "current",
        "project-page.png",
        page="project",
        data=_png(1, 1, (255, 0, 0)),
    )
    baseline = _write_single_record_manifest(
        module,
        tmp_path / "baseline",
        "project-page.png",
        page="project",
        data=_png(2, 1, (255, 0, 0)),
    )

    report = module.build_report(
        current_manifest_path=current,
        baseline_manifest_path=baseline,
        max_diff_ratio=0.0,
        channel_threshold=10,
        allow_missing_baseline=False,
    )

    comparison = report["comparisons"][0]
    assert report["success"] is False
    assert comparison["status"] == "failed"
    assert comparison["diff_ratio"] is None
    assert "image dimensions differ" in comparison["detail"]


def test_visual_baseline_report_fails_when_pixel_diff_exceeds_threshold(tmp_path) -> None:
    module = _load_module()
    current = _write_single_record_manifest(
        module,
        tmp_path / "current",
        "analysis-page.png",
        page="analysis",
        data=_png(2, 1, (255, 255, 255)),
    )
    baseline = _write_single_record_manifest(
        module,
        tmp_path / "baseline",
        "analysis-page.png",
        page="analysis",
        data=_png(2, 1, (0, 0, 0)),
    )

    report = module.build_report(
        current_manifest_path=current,
        baseline_manifest_path=baseline,
        max_diff_ratio=0.25,
        channel_threshold=10,
        allow_missing_baseline=False,
    )

    comparison = report["comparisons"][0]
    assert report["success"] is False
    assert comparison["status"] == "failed"
    assert comparison["diff_ratio"] == 1.0
    assert comparison["diff_pixels"] == 2
    assert comparison["total_pixels"] == 2
    assert "pixel diff ratio 1.000000 > 0.250000" in comparison["detail"]


def test_visual_baseline_report_warns_when_pillow_unavailable_and_hashes_differ(
    tmp_path,
    monkeypatch,
) -> None:
    module = _load_module()
    current = _write_single_record_manifest(
        module,
        tmp_path / "current",
        "workflow-page.png",
        page="workflow",
        data=_png(1, 1, (255, 255, 255)),
    )
    baseline = _write_single_record_manifest(
        module,
        tmp_path / "baseline",
        "workflow-page.png",
        page="workflow",
        data=_png(1, 1, (0, 0, 0)),
    )
    original_import = builtins.__import__

    def block_pillow(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PIL":
            raise ModuleNotFoundError("No module named 'PIL'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", block_pillow)

    report = module.build_report(
        current_manifest_path=current,
        baseline_manifest_path=baseline,
        max_diff_ratio=0.0,
        channel_threshold=10,
        allow_missing_baseline=False,
    )

    comparison = report["comparisons"][0]
    assert report["success"] is True
    assert report["summary"]["warning_count"] == 1
    assert comparison["status"] == "warning"
    assert comparison["detail"] == "Pillow unavailable; compared metadata and hashes only"


def test_visual_baseline_records_support_absolute_paths_and_aliases(tmp_path) -> None:
    module = _load_module()
    image_path = tmp_path / "core-pages-overview.png"
    image_path.write_bytes(PNG_1X1)
    record = module.SCREENSHOTS.build_screenshot_record(
        image_path,
        page="core-pages-overview",
        root=None,
        created_at="2026-05-18T00:00:00Z",
    )
    manifest = module.SCREENSHOTS.build_screenshot_manifest(
        [record],
        root="",
        created_at="2026-05-18T00:00:00Z",
    )

    assert module._record_image_path(manifest, record) == image_path
    assert module.records_by_page(manifest)["home"] == record
    assert module.normalize_page_key("Execute now") == "orchestrate"
    assert module.normalize_page_key("project-create-page.png") == "project-create"
    assert module.normalize_page_key("project-page.png") == "project"
    assert module.normalize_page_key("custom diagnostics") == "custom-diagnostics"


def test_visual_baseline_keeps_project_create_separate_from_project(tmp_path) -> None:
    module = _load_module()
    project_create = tmp_path / "project-create-page.png"
    project = tmp_path / "project-page.png"
    project_create.write_bytes(PNG_1X1)
    project.write_bytes(PNG_1X1)
    create_record = module.SCREENSHOTS.build_screenshot_record(
        project_create,
        page="project-create-page",
        root=tmp_path,
        created_at="2026-05-18T00:00:00Z",
    )
    project_record = module.SCREENSHOTS.build_screenshot_record(
        project,
        page="project-page",
        root=tmp_path,
        created_at="2026-05-18T00:00:00Z",
    )
    manifest = module.SCREENSHOTS.build_screenshot_manifest(
        [create_record, project_record],
        root=str(tmp_path),
        created_at="2026-05-18T00:00:00Z",
    )

    records = module.records_by_page(manifest)

    assert records["project-create"] == create_record
    assert records["project"] == project_record


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


def test_visual_baseline_report_human_cli_writes_nested_output(tmp_path, capsys) -> None:
    module = _load_module()
    current = _write_manifest(module, tmp_path / "current", "settings-page.png")
    baseline = _write_manifest(module, tmp_path / "baseline", "project-page.png")
    output = tmp_path / "nested" / "report.json"

    exit_code = module.main(
        [
            "--current",
            str(current),
            "--baseline",
            str(baseline),
            "--allow-missing-baseline",
            "--output",
            str(output),
        ]
    )

    text = capsys.readouterr().out
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert "AGILAB UI visual baseline report" in text
    assert "verdict: PASS" in text
    assert "- settings: warning - no baseline screenshot matched this page" in text
    assert payload["summary"]["warning_count"] == 1


def test_visual_baseline_report_entrypoint_runs_json(tmp_path, monkeypatch, capsys) -> None:
    module = _load_module()
    current = _write_manifest(module, tmp_path / "current", "project-page.png")
    baseline = _write_manifest(module, tmp_path / "baseline", "project-page.png")
    output = tmp_path / "entrypoint-report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(MODULE_PATH),
            "--current",
            str(current),
            "--baseline",
            str(baseline),
            "--output",
            str(output),
            "--json",
        ],
    )

    try:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected entrypoint to raise SystemExit")

    assert json.loads(capsys.readouterr().out)["success"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == module.SCHEMA
