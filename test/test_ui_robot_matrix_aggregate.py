from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path


MODULE_PATH = Path("tools/ui_robot_matrix_aggregate.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("ui_robot_matrix_aggregate_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _shard_result_dir(root: Path, shard: str) -> Path:
    return root / f"ui-robot-matrix-{shard}-1" / "test-results" / "ui-robot-matrix" / shard


def _shard_screenshot_dir(root: Path, shard: str) -> Path:
    return root / f"ui-robot-matrix-{shard}-1" / "screenshots" / "ui-robot-matrix" / shard


def _write_shard(
    root: Path,
    shard: str,
    *,
    success: bool = True,
    failed_count: int = 0,
    exit_code: str = "0",
    retry_artifacts: bool = False,
) -> Path:
    shard_root = _shard_result_dir(root, shard)
    shard_root.mkdir(parents=True)
    (shard_root / "summary.json").write_text(
        json.dumps(
            {
                "schema": "agilab.widget_robot_matrix.v1",
                "success": success,
                "scenario_count": 2,
                "app_count": 3,
                "page_count": 4,
                "widget_count": 10,
                "interacted_count": 6,
                "probed_count": 4,
                "skipped_count": 0,
                "failed_count": failed_count,
                "cached_count": 1,
                "failure_artifact_retry_count": 1 if retry_artifacts else 0,
                "failure_artifact_retry_passed_count": 0,
                "duration_seconds": 12.5,
                "failed_scenarios": [f"{shard}-scenario"] if failed_count else [],
                "failure_samples": [
                    {
                        "scenario": f"{shard}-scenario",
                        "app": "flight_telemetry_project",
                        "page": "ORCHESTRATE",
                        "kind": "button",
                        "label": "Run",
                        "detail": "failed",
                    }
                ]
                if failed_count
                else [],
            }
        ),
        encoding="utf-8",
    )
    (shard_root / "trend-report.json").write_text(
        json.dumps(
            {
                "schema": "agilab.ui_robot_trend_report.v1",
                "success": success,
                "summary": {
                    "page_count": 4,
                    "failed_page_count": failed_count,
                    "flaky_page_count": 0,
                    "slow_page_count": 0,
                    "parse_error_count": 0,
                    "budget_violation_count": 0,
                    "total_duration_seconds": 11.0,
                    "mean_page_duration_seconds": 2.75,
                },
            }
        ),
        encoding="utf-8",
    )
    (shard_root / "exit-code.txt").write_text(f"{exit_code}\n", encoding="utf-8")
    if failed_count:
        bundle = shard_root / "failure-bundles" / f"{shard}-scenario" / "_scenario"
        bundle.mkdir(parents=True)
        manifest = {
            "schema": "agilab.widget_robot_matrix_failure_bundle.v1",
            "scenario": f"{shard}-scenario",
            "command": [
                "python",
                "tools/agilab_widget_robot.py",
                "--pages",
                "ORCHESTRATE",
            ],
        }
        if retry_artifacts:
            manifest["failure_artifact_retry"] = {
                "success": False,
                "returncode": 1,
                "duration_seconds": 4.0,
                "summary_path": str(shard_root / "failure-retry" / f"{shard}-scenario.json"),
                "progress_path": str(shard_root / "failure-retry" / f"{shard}-scenario.ndjson"),
                "trace_dir": str(shard_root / "failure-artifacts" / "traces" / f"{shard}-scenario"),
                "har_dir": str(shard_root / "failure-artifacts" / "har" / f"{shard}-scenario"),
                "video_dir": str(shard_root / "failure-artifacts" / "video" / f"{shard}-scenario"),
                "command": [
                    "python",
                    "tools/agilab_widget_robot.py",
                    "--trace-dir",
                    str(shard_root / "failure-artifacts" / "traces" / f"{shard}-scenario"),
                ],
            }
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return shard_root


def _write_screenshots(root: Path, shard: str, count: int) -> Path:
    screenshot_dir = _shard_screenshot_dir(root, shard)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (screenshot_dir / f"{shard}-{index}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return screenshot_dir


def test_build_aggregate_summarizes_all_shards(tmp_path: Path) -> None:
    module = _load_module()
    for shard in ("core", "state", "quality", "layout"):
        _write_shard(tmp_path, shard)

    report = module.build_aggregate(tmp_path)
    markdown = module.render_markdown(report)

    assert report["schema"] == module.SCHEMA
    assert report["success"] is True
    assert report["missing_shards"] == []
    assert report["failed_shards"] == []
    assert report["summary"]["shard_count"] == 4
    assert report["summary"]["scenario_count"] == 8
    assert report["summary"]["page_count"] == 16
    assert report["summary"]["widget_count"] == 40
    assert report["summary"]["cached_count"] == 4
    assert report["summary"]["failure_artifact_retry_count"] == 0
    assert report["summary"]["trend"]["failed_page_count"] == 0
    assert "| core | PASS |" in markdown


def test_build_aggregate_includes_extra_shards_after_expected_shards(tmp_path: Path) -> None:
    module = _load_module()
    for shard in ("core", "state", "quality", "layout", "experimental"):
        _write_shard(tmp_path, shard)

    report = module.build_aggregate(tmp_path)

    assert report["success"] is True
    assert report["extra_shards"] == ["experimental"]
    assert [shard["name"] for shard in report["shards"]] == [
        "core",
        "state",
        "quality",
        "layout",
        "experimental",
    ]
    assert report["summary"]["shard_count"] == 5


def test_build_aggregate_uses_shard_manifest_discovery(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    shard_root = _write_shard(
        tmp_path / "artifacts",
        "core",
        success=False,
        failed_count=1,
        exit_code="1",
        retry_artifacts=True,
    )
    screenshot_dir = tmp_path / "screenshots" / "core"
    screenshot_dir.mkdir(parents=True)
    (screenshot_dir / "failed.png").write_bytes(b"png")

    manifest = module.write_shard_manifest(
        result_dir=shard_root,
        screenshot_dir=screenshot_dir,
        shard="core",
        generated_at="2026-05-18T00:00:00Z",
    )

    def fail_summary_discovery(root: Path) -> dict[str, Path]:
        raise AssertionError(f"legacy summary discovery should not run for {root}")

    monkeypatch.setattr(module, "discover_shard_summary_paths", fail_summary_discovery)
    report = module.build_aggregate(tmp_path, expected_shards=("core",))

    assert manifest["schema"] == module.SHARD_MANIFEST_SCHEMA
    assert manifest["screenshot_count"] == 1
    assert manifest["screenshot_dir"].startswith("..")
    assert report["discovery"] == {"mode": "manifest", "manifest_count": 1, "shard_count": 1}
    assert report["summary"]["screenshot_count"] == 1
    assert report["shards"][0]["manifest_file"].endswith(module.SHARD_MANIFEST_FILENAME)
    assert report["shards"][0]["failure_bundles"][0]["scenario"] == "core-scenario"
    assert report["failure_samples"][0]["failure_artifact_retry_status"] == "FAIL"


def test_manifest_discovery_reports_shard_with_missing_summary_as_failed(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    shard_root = _shard_result_dir(tmp_path, "core")
    shard_root.mkdir(parents=True)
    (shard_root / "exit-code.txt").write_text("2\n", encoding="utf-8")
    module.write_shard_manifest(
        result_dir=shard_root,
        screenshot_dir=_write_screenshots(tmp_path, "core", 0),
        shard="core",
    )

    def fail_summary_discovery(root: Path) -> dict[str, Path]:
        raise AssertionError(f"legacy summary discovery should not run for {root}")

    monkeypatch.setattr(module, "discover_shard_summary_paths", fail_summary_discovery)
    report = module.build_aggregate(tmp_path, expected_shards=("core",))

    assert report["success"] is False
    assert report["failed_shards"] == ["core"]
    assert report["missing_shards"] == []
    assert report["shards"][0]["summary_file"].endswith("summary.json")
    assert report["shards"][0]["trend"]["schema"] == ""


def test_build_aggregate_reports_missing_and_failed_shards(tmp_path: Path) -> None:
    module = _load_module()
    _write_shard(tmp_path, "core")
    _write_shard(tmp_path, "state", success=False, failed_count=1, exit_code="1", retry_artifacts=True)

    report = module.build_aggregate(tmp_path)

    assert report["success"] is False
    assert report["missing_shards"] == ["quality", "layout"]
    assert report["failed_shards"] == ["state"]
    assert report["failed_scenarios"] == ["state:state-scenario"]
    assert report["failure_samples"][0]["shard"] == "state"
    assert report["failure_samples"][0]["failure_bundle"].endswith(
        "failure-bundles/state-scenario/_scenario"
    )
    assert "tools/ui_robot_failure_replay.py" in report["failure_samples"][0]["failure_replay_command"]
    assert report["failure_samples"][0]["failure_artifact_retry_status"] == "FAIL"
    assert report["failure_samples"][0]["failure_artifact_retry_trace_dir"].endswith(
        "failure-artifacts/traces/state-scenario"
    )
    assert report["shards"][1]["failure_bundles"][0]["manifest"].endswith("manifest.json")
    assert report["shards"][1]["failure_artifact_retry_count"] == 1
    assert report["summary"]["failure_artifact_retry_count"] == 1
    assert report["summary"]["trend"]["failed_page_count"] == 1


def test_build_aggregate_marks_missing_trend_or_nonzero_exit_as_failed(tmp_path: Path) -> None:
    module = _load_module()
    core = _write_shard(tmp_path, "core")
    (core / "trend-report.json").unlink()
    _write_shard(tmp_path, "state", exit_code="2")
    _write_shard(tmp_path, "quality")
    _write_shard(tmp_path, "layout")

    report = module.build_aggregate(tmp_path)

    assert report["success"] is False
    assert report["failed_shards"] == ["core", "state"]
    assert report["shards"][0]["trend"]["schema"] == ""
    assert report["shards"][1]["exit_code"] == "2"


def test_discovery_skips_summaries_without_exit_code_and_bad_failure_manifests(tmp_path: Path) -> None:
    module = _load_module()
    shard_root = _write_shard(tmp_path, "core", success=False, failed_count=1, exit_code="1")
    orphan = tmp_path / "orphan" / "summary.json"
    orphan.parent.mkdir(parents=True)
    orphan.write_text(json.dumps({"success": True}), encoding="utf-8")
    bad_manifest = shard_root / "failure-bundles" / "bad" / "_scenario" / "manifest.json"
    bad_manifest.parent.mkdir(parents=True)
    bad_manifest.write_text(json.dumps({"command": "not-a-list"}), encoding="utf-8")

    summaries = module.discover_shard_summary_paths(tmp_path)
    bundles = module.discover_failure_bundles(tmp_path, shard_root)

    assert summaries == {"core": shard_root / "summary.json"}
    assert list(bundles) == ["core-scenario"]


def test_discovery_helpers_ignore_invalid_inputs(tmp_path: Path) -> None:
    module = _load_module()
    bad_manifest = tmp_path / "bad" / "manifest.json"
    bad_manifest.parent.mkdir()
    bad_manifest.write_text("{", encoding="utf-8")
    wrong_schema = tmp_path / "wrong" / module.SHARD_MANIFEST_FILENAME
    wrong_schema.parent.mkdir()
    wrong_schema.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    missing_shard = tmp_path / "missing-shard" / module.SHARD_MANIFEST_FILENAME
    missing_shard.parent.mkdir()
    missing_shard.write_text(json.dumps({"schema": module.SHARD_MANIFEST_SCHEMA}), encoding="utf-8")
    malformed_shard = tmp_path / "malformed" / module.SHARD_MANIFEST_FILENAME
    malformed_shard.parent.mkdir()
    malformed_shard.write_text("{", encoding="utf-8")

    assert module._relative(Path("/definitely/outside"), tmp_path) == "/definitely/outside"
    assert module._resolve_manifest_path(bad_manifest, "") is None
    assert module._shard_from_summary_path(tmp_path / "plain" / "summary.json") == "plain"
    assert module._scenario_from_bundle_manifest(bad_manifest) == ""
    assert module.discover_shard_manifests(tmp_path) == {}


def test_discover_failure_bundles_tolerates_manifest_load_race(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    shard_root = tmp_path / "shard"
    manifest_path = shard_root / "failure-bundles" / "race" / "_scenario" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"scenario": "race", "command": ["python"]}), encoding="utf-8")

    def flaky_load_json(path: Path):
        if path == manifest_path:
            raise json.JSONDecodeError("race", "{", 0)
        return {}

    monkeypatch.setattr(module, "_scenario_from_bundle_manifest", lambda _path: "race")
    monkeypatch.setattr(module, "_load_json", flaky_load_json)

    bundles = module.discover_failure_bundles(tmp_path, shard_root, manifest_paths=[manifest_path])

    assert bundles["race"][0]["scenario"] == "race"
    assert "failure_artifact_retry" not in bundles["race"][0]


def test_load_shard_payload_ignores_non_mapping_failure_samples(tmp_path: Path) -> None:
    module = _load_module()
    shard_root = _write_shard(tmp_path, "core", success=False, failed_count=1, exit_code="1")
    summary_path = shard_root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["failure_samples"] = [
        "not-a-sample",
        {
            "scenario": "core-scenario",
            "app": "flight_telemetry_project",
            "page": "ORCHESTRATE",
        },
        {
            "scenario": "missing-bundle-scenario",
            "app": "flight_telemetry_project",
            "page": "ANALYSIS",
        },
    ]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    payload = module._load_shard_payload(
        tmp_path,
        "core",
        shard_dir=shard_root,
        summary_path=summary_path,
        trend_path=shard_root / "trend-report.json",
        exit_code_path=shard_root / "exit-code.txt",
    )

    assert len(payload["failure_samples"]) == 2
    assert payload["failure_samples"][0]["scenario"] == "core-scenario"
    assert payload["failure_samples"][0]["failure_bundle"]
    assert payload["failure_samples"][1]["scenario"] == "missing-bundle-scenario"
    assert "failure_bundle" not in payload["failure_samples"][1]


def test_render_markdown_includes_failure_replay_command(tmp_path: Path) -> None:
    module = _load_module()
    _write_shard(tmp_path, "core", success=False, failed_count=1, exit_code="1", retry_artifacts=True)
    _write_shard(tmp_path, "state")
    _write_shard(tmp_path, "quality")
    _write_shard(tmp_path, "layout")

    markdown = module.render_markdown(module.build_aggregate(tmp_path))

    assert "Bundle: `" in markdown
    assert (
        "Replay: `uv --preview-features extra-build-dependencies run python "
        "tools/ui_robot_failure_replay.py"
    ) in markdown
    assert "Artifact retry: `FAIL`" in markdown
    assert "Trace: `" in markdown
    assert "HAR: `" in markdown
    assert "Video: `" in markdown


def test_render_markdown_handles_minimal_retry_without_artifact_paths() -> None:
    module = _load_module()

    markdown = module.render_markdown(
        {
            "success": False,
            "summary": {"shard_count": 1, "expected_shard_count": 1},
            "missing_shards": [],
            "shards": [
                {
                    "name": "core",
                    "success": False,
                    "scenario_count": 1,
                    "trend": {"success": False},
                }
            ],
            "failure_samples": [
                {
                    "shard": "core",
                    "scenario": "demo",
                    "failure_artifact_retry": {"success": True},
                    "failure_artifact_retry_status": "PASS",
                }
            ],
        }
    )

    assert "Artifact retry: `PASS`" in markdown
    assert "Bundle:" not in markdown
    assert "Replay:" not in markdown
    assert "Trace:" not in markdown
    assert "HAR:" not in markdown
    assert "Video:" not in markdown


def test_render_markdown_reports_bundle_without_retry() -> None:
    module = _load_module()

    markdown = module.render_markdown(
        {
            "success": False,
            "summary": {"shard_count": 1, "expected_shard_count": 1},
            "missing_shards": [],
            "shards": [],
            "failure_samples": [
                {
                    "shard": "core",
                    "scenario": "demo",
                    "page": "ANALYSIS",
                    "kind": "text",
                    "label": "View",
                    "detail": "missing",
                    "failure_bundle": "bundle/path",
                    "failure_replay_command": "uv run replay",
                }
            ],
        }
    )

    assert "Bundle: `bundle/path`" in markdown
    assert "Replay: `uv run replay`" in markdown
    assert "Artifact retry:" not in markdown


def test_render_markdown_skips_non_mapping_rows() -> None:
    module = _load_module()

    markdown = module.render_markdown(
        {
            "success": False,
            "summary": {},
            "missing_shards": [],
            "shards": ["not-a-shard"],
            "failure_samples": ["not-a-sample"],
        }
    )

    assert "UI robot matrix aggregate" in markdown
    assert "not-a-shard" not in markdown


def test_render_markdown_reports_missing_shards_and_empty_samples(tmp_path: Path) -> None:
    module = _load_module()
    _write_shard(tmp_path, "core")

    markdown = module.render_markdown(module.build_aggregate(tmp_path))

    assert "### Missing Shards" in markdown
    assert "`state`" in markdown
    assert "No failure samples recorded." in markdown


def test_main_writes_json_and_markdown(tmp_path: Path, capsys) -> None:
    module = _load_module()
    for shard in ("core", "state", "quality", "layout"):
        _write_shard(tmp_path / "artifacts", shard)
    output = tmp_path / "aggregate.json"
    markdown = tmp_path / "summary.md"

    exit_code = module.main(
        [
            "--root",
            str(tmp_path / "artifacts"),
            "--output",
            str(output),
            "--summary-markdown",
            str(markdown),
            "--compact",
        ]
    )

    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["success"] is True
    assert "UI robot matrix aggregate" in markdown.read_text(encoding="utf-8")
    assert json.loads(capsys.readouterr().out)["schema"] == module.SCHEMA


def test_main_writes_shard_manifest(tmp_path: Path, capsys) -> None:
    module = _load_module()
    shard_root = _write_shard(tmp_path, "core")
    screenshot_dir = tmp_path / "screenshots"
    screenshot_dir.mkdir()
    (screenshot_dir / "page.png").write_bytes(b"png")

    exit_code = module.main(
        [
            "--write-shard-manifest",
            "--result-dir",
            str(shard_root),
            "--screenshot-dir",
            str(screenshot_dir),
            "--shard",
            "core",
            "--compact",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["schema"] == module.SHARD_MANIFEST_SCHEMA
    assert payload["screenshot_count"] == 1
    assert (shard_root / module.SHARD_MANIFEST_FILENAME).is_file()


def test_main_rejects_incomplete_shard_manifest_args() -> None:
    module = _load_module()

    try:
        module.main(["--write-shard-manifest", "--result-dir", "."])
    except SystemExit as exc:
        assert "--write-shard-manifest requires" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected incomplete manifest args to fail")


def test_main_returns_failure_for_missing_expected_shards(tmp_path: Path, capsys) -> None:
    module = _load_module()
    _write_shard(tmp_path / "artifacts", "core")
    output = tmp_path / "aggregate.json"

    exit_code = module.main(
        [
            "--root",
            str(tmp_path / "artifacts"),
            "--expected-shards",
            "core,state",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["missing_shards"] == ["state"]
    assert json.loads(output.read_text(encoding="utf-8"))["success"] is False


def test_parse_expected_shards_uses_default_for_empty_input() -> None:
    module = _load_module()

    assert module._parse_expected_shards(" ,, ") == module.DEFAULT_EXPECTED_SHARDS


def test_module_entrypoint_writes_compact_aggregate(tmp_path: Path, monkeypatch, capsys) -> None:
    _write_shard(tmp_path / "artifacts", "core")
    output = tmp_path / "aggregate.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(MODULE_PATH),
            "--root",
            str(tmp_path / "artifacts"),
            "--expected-shards",
            "core",
            "--output",
            str(output),
            "--compact",
        ],
    )

    try:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected entrypoint to raise SystemExit")

    assert json.loads(output.read_text(encoding="utf-8"))["success"] is True
    assert json.loads(capsys.readouterr().out)["success"] is True


def test_load_json_rejects_non_object_payload(tmp_path: Path) -> None:
    module = _load_module()
    payload = tmp_path / "payload.json"
    payload.write_text("[]", encoding="utf-8")

    try:
        module._load_json(payload)
    except ValueError as exc:
        assert "JSON object" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected non-object JSON to be rejected")
