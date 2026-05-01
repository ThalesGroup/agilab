from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
import agilab  # noqa: E402

SOURCE_PACKAGE = str(SRC_ROOT / "agilab")
if SOURCE_PACKAGE not in agilab.__path__:
    agilab.__path__.insert(0, SOURCE_PACKAGE)

from agilab.screenshot_manifest import (
    SCHEMA,
    SCHEMA_VERSION,
    build_screenshot_record,
    image_dimensions,
    build_page_shots_manifest,
    load_screenshot_manifest,
    screenshot_manifest_path,
    try_load_screenshot_manifest,
    write_screenshot_manifest,
)


def _write_png(path: Path, *, width: int = 640, height: int = 360) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _write_jpeg(path: Path, *, width: int = 320, height: int = 180) -> None:
    path.write_bytes(
        b"\xff\xd8"
        + b"\xff\xe0"
        + (16).to_bytes(2, "big")
        + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xc0"
        + (17).to_bytes(2, "big")
        + b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )


def test_screenshot_manifest_roundtrip_records_stable_contract(tmp_path: Path) -> None:
    shots = tmp_path / "page-shots"
    shots.mkdir()
    _write_png(shots / "project-page.png", width=800, height=450)

    manifest = build_page_shots_manifest(
        shots,
        manifest_root="docs/source/_static/page-shots",
        source_command=("capture", "--pages"),
        created_at="2026-04-29T12:00:00Z",
    )
    path = write_screenshot_manifest(manifest, screenshot_manifest_path(shots))
    loaded = load_screenshot_manifest(path)

    assert loaded.schema == SCHEMA
    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.created_at == "2026-04-29T12:00:00Z"
    assert loaded.root == "docs/source/_static/page-shots"
    assert loaded.source_command == ("capture", "--pages")
    assert len(loaded.screenshots) == 1
    record = loaded.screenshots[0]
    assert record.page == "project"
    assert record.image_path == "project-page.png"
    assert record.width_px == 800
    assert record.height_px == 450
    assert record.size_bytes > 0
    assert len(record.sha256) == 64


def test_screenshot_manifest_records_jpeg_and_external_paths(tmp_path: Path) -> None:
    image = tmp_path / "analysis-page.jpeg"
    _write_jpeg(image, width=1024, height=512)

    assert image_dimensions(image) == (1024, 512)

    external_record = build_screenshot_record(
        image,
        root=tmp_path / "other-root",
        source_command=("robot", "--capture"),
        created_at="2026-05-01T12:00:00Z",
        alt="analysis page",
        url="http://127.0.0.1:8501/ANALYSIS",
    )
    no_root_record = build_screenshot_record(image, root=None, created_at="2026-05-01T12:00:00Z")

    assert external_record.page == "analysis"
    assert external_record.width_px == 1024
    assert external_record.height_px == 512
    assert external_record.image_path == str(image)
    assert external_record.source_command == ("robot", "--capture")
    assert external_record.alt == "analysis page"
    assert external_record.url.endswith("/ANALYSIS")
    assert no_root_record.image_path == str(image)


def test_screenshot_manifest_loader_reports_contract_errors(tmp_path: Path) -> None:
    missing, reason = try_load_screenshot_manifest(tmp_path / "missing.json")
    assert missing is None
    assert reason == "missing"

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "wrong", "schema_version": 1, "kind": "bad"}), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported screenshot manifest schema"):
        load_screenshot_manifest(bad)

    loaded, error = try_load_screenshot_manifest(bad)
    assert loaded is None
    assert error and "Unsupported screenshot manifest schema" in error

    bad_version = tmp_path / "bad-version.json"
    bad_version.write_text(
        json.dumps({"schema": SCHEMA, "schema_version": "bad", "kind": "agilab.screenshot_manifest"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported screenshot manifest schema version"):
        load_screenshot_manifest(bad_version)

    future_version = tmp_path / "future-version.json"
    future_version.write_text(
        json.dumps({"schema": SCHEMA, "schema_version": SCHEMA_VERSION + 1, "kind": "agilab.screenshot_manifest"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported screenshot manifest schema version"):
        load_screenshot_manifest(future_version)

    bad_kind = tmp_path / "bad-kind.json"
    bad_kind.write_text(
        json.dumps({"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "kind": "wrong"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported screenshot manifest kind"):
        load_screenshot_manifest(bad_kind)
