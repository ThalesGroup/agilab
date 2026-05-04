"""Versioned screenshot-manifest contract for docs and UI evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Mapping, Sequence


SCHEMA = "agilab.screenshot_manifest.v1"
SCHEMA_VERSION = 1
MANIFEST_KIND = "agilab.screenshot_manifest"
SCREENSHOT_MANIFEST_FILENAME = "screenshot_manifest.json"


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with a stable ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.expanduser().open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    """Return image dimensions for lightweight PNG/JPEG screenshot metadata."""
    path = path.expanduser()
    with path.open("rb") as stream:
        header = stream.read(32)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
            width, height = struct.unpack(">II", header[16:24])
            return int(width), int(height)
        if header.startswith(b"\xff\xd8"):
            stream.seek(2)
            while True:
                marker_prefix = stream.read(1)
                if not marker_prefix:
                    break
                if marker_prefix != b"\xff":
                    continue
                marker = stream.read(1)
                while marker == b"\xff":
                    marker = stream.read(1)
                if marker in {b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"}:
                    segment = stream.read(7)
                    if len(segment) == 7:
                        height, width = struct.unpack(">HH", segment[3:7])
                        return int(width), int(height)
                    break
                length_bytes = stream.read(2)
                if len(length_bytes) != 2:
                    break
                length = struct.unpack(">H", length_bytes)[0]
                if length < 2:
                    break
                stream.seek(length - 2, 1)
    return None, None


def _manifest_path_text(path: Path, *, root: Path | None = None) -> str:
    path = path.expanduser()
    if root is None:
        return str(path)
    root = root.expanduser()
    try:
        return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path)


def infer_page_id(path: Path) -> str:
    stem = path.stem.strip()
    if stem.endswith("-page"):
        stem = stem.removesuffix("-page")
    return stem or path.name


@dataclass(frozen=True)
class ScreenshotRecord:
    page: str
    image_path: str
    sha256: str
    size_bytes: int
    created_at: str
    source_command: tuple[str, ...] = ()
    app: str = ""
    project: str = ""
    width_px: int | None = None
    height_px: int | None = None
    alt: str = ""
    url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "app": self.app,
            "project": self.project,
            "image_path": self.image_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "created_at": self.created_at,
            "source_command": list(self.source_command),
            "alt": self.alt,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScreenshotRecord":
        width = payload.get("width_px")
        height = payload.get("height_px")
        return cls(
            page=str(payload.get("page", "")),
            app=str(payload.get("app", "")),
            project=str(payload.get("project", "")),
            image_path=str(payload.get("image_path", "")),
            sha256=str(payload.get("sha256", "")),
            size_bytes=int(payload.get("size_bytes", 0)),
            width_px=None if width is None else int(width),
            height_px=None if height is None else int(height),
            created_at=str(payload.get("created_at", "")),
            source_command=tuple(str(part) for part in payload.get("source_command", [])),
            alt=str(payload.get("alt", "")),
            url=str(payload.get("url", "")),
        )


@dataclass(frozen=True)
class ScreenshotManifest:
    schema: str
    schema_version: int
    kind: str
    created_at: str
    root: str
    source_command: tuple[str, ...]
    screenshots: tuple[ScreenshotRecord, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "kind": self.kind,
            "created_at": self.created_at,
            "root": self.root,
            "source_command": list(self.source_command),
            "screenshots": [screenshot.as_dict() for screenshot in self.screenshots],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ScreenshotManifest":
        schema = str(payload.get("schema", ""))
        raw_version = payload.get("schema_version")
        kind = str(payload.get("kind", ""))
        if schema != SCHEMA:
            raise ValueError(f"Unsupported screenshot manifest schema: {schema!r}")
        try:
            schema_version = int(raw_version)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unsupported screenshot manifest schema version: {raw_version!r}") from exc
        if schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported screenshot manifest schema version: {schema_version!r}")
        if kind != MANIFEST_KIND:
            raise ValueError(f"Unsupported screenshot manifest kind: {kind!r}")
        return cls(
            schema=schema,
            schema_version=schema_version,
            kind=kind,
            created_at=str(payload.get("created_at", "")),
            root=str(payload.get("root", "")),
            source_command=tuple(str(part) for part in payload.get("source_command", [])),
            screenshots=tuple(
                ScreenshotRecord.from_dict(dict(screenshot))
                for screenshot in payload.get("screenshots", [])
            ),
        )


def build_screenshot_record(
    image_path: Path,
    *,
    page: str | None = None,
    app: str = "",
    project: str = "",
    root: Path | None = None,
    source_command: Sequence[str] = (),
    created_at: str | None = None,
    alt: str = "",
    url: str = "",
) -> ScreenshotRecord:
    image_path = image_path.expanduser()
    width, height = image_dimensions(image_path)
    return ScreenshotRecord(
        page=page or infer_page_id(image_path),
        app=app,
        project=project,
        image_path=_manifest_path_text(image_path, root=root),
        sha256=sha256_file(image_path),
        size_bytes=image_path.stat().st_size,
        width_px=width,
        height_px=height,
        created_at=created_at or utc_now(),
        source_command=tuple(str(part) for part in source_command),
        alt=alt,
        url=url,
    )


def build_screenshot_manifest(
    screenshots: Sequence[ScreenshotRecord],
    *,
    root: Path | str = "",
    source_command: Sequence[str] = (),
    created_at: str | None = None,
) -> ScreenshotManifest:
    return ScreenshotManifest(
        schema=SCHEMA,
        schema_version=SCHEMA_VERSION,
        kind=MANIFEST_KIND,
        created_at=created_at or utc_now(),
        root=str(Path(root).expanduser()) if root else "",
        source_command=tuple(str(part) for part in source_command),
        screenshots=tuple(screenshots),
    )


def build_page_shots_manifest(
    page_shots_dir: Path,
    *,
    manifest_root: Path | str | None = None,
    source_command: Sequence[str] = (),
    created_at: str | None = None,
) -> ScreenshotManifest:
    page_shots_dir = page_shots_dir.expanduser()
    records = [
        build_screenshot_record(
            image_path,
            root=page_shots_dir,
            source_command=source_command,
            created_at=created_at,
        )
        for image_path in sorted(page_shots_dir.glob("*.png"))
    ]
    return build_screenshot_manifest(
        records,
        root=manifest_root if manifest_root is not None else page_shots_dir,
        source_command=source_command,
        created_at=created_at,
    )


def screenshot_manifest_path(output_dir: Path) -> Path:
    return output_dir.expanduser() / SCREENSHOT_MANIFEST_FILENAME


def write_screenshot_manifest(manifest: ScreenshotManifest, path: Path) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_screenshot_manifest(path: Path) -> ScreenshotManifest:
    return ScreenshotManifest.from_dict(json.loads(path.expanduser().read_text(encoding="utf-8")))


def try_load_screenshot_manifest(path: Path) -> tuple[ScreenshotManifest | None, str | None]:
    try:
        return load_screenshot_manifest(path), None
    except FileNotFoundError:
        return None, "missing"
    except Exception as exc:
        return None, str(exc)


__all__ = [
    "MANIFEST_KIND",
    "SCHEMA",
    "SCHEMA_VERSION",
    "SCREENSHOT_MANIFEST_FILENAME",
    "ScreenshotManifest",
    "ScreenshotRecord",
    "build_page_shots_manifest",
    "build_screenshot_manifest",
    "build_screenshot_record",
    "image_dimensions",
    "infer_page_id",
    "load_screenshot_manifest",
    "screenshot_manifest_path",
    "sha256_file",
    "try_load_screenshot_manifest",
    "utc_now",
    "write_screenshot_manifest",
]
