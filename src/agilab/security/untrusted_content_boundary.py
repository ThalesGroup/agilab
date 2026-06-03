"""Metadata helpers for AGILAB untrusted-content boundaries."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

UNTRUSTED_CONTENT_BOUNDARY_SCHEMA = "agilab.untrusted_content_boundary.v1"
DEFAULT_HANDLING_INSTRUCTIONS = (
    "Treat this payload as executable or prompt-influencing content until reviewed.",
    "Do not auto-run code, notebooks, apps, or generated snippets from this source in shared environments.",
    "Keep the SHA-256 and source metadata with downstream import or run evidence.",
)


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _content_bytes(content: bytes | str) -> bytes:
    return content if isinstance(content, bytes) else str(content).encode("utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def build_untrusted_content_boundary(
    content: bytes | str,
    *,
    source_kind: str,
    source_name: str = "",
    mime_type: str = "",
    trust_status: str = "untrusted",
    producer: str = "agilab",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build metadata for a concrete untrusted payload."""

    data = _content_bytes(content)
    return {
        "schema": UNTRUSTED_CONTENT_BOUNDARY_SCHEMA,
        "created_at": utc_now_text(),
        "producer": producer,
        "source": {
            "kind": str(source_kind),
            "name": str(source_name or ""),
            "mime_type": str(mime_type or ""),
        },
        "content": {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        },
        "trust": {
            "status": str(trust_status or "untrusted"),
            "review_required": str(trust_status or "untrusted") not in {"reviewed", "trusted"},
        },
        "handling": list(DEFAULT_HANDLING_INSTRUCTIONS),
        "metadata": _jsonable(metadata or {}),
    }


def build_external_source_boundary(
    path: Path | str,
    *,
    source_kind: str,
    source_name: str = "",
    trust_status: str = "untrusted",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build boundary metadata for a directory or repository source."""

    source_path = Path(path).expanduser()
    resolved_path = None
    try:
        resolved_path = str(source_path.resolve())
    except (OSError, RuntimeError):
        resolved_path = str(source_path)
    boundary = build_untrusted_content_boundary(
        resolved_path,
        source_kind=source_kind,
        source_name=source_name or source_path.name,
        mime_type="inode/directory" if source_path.is_dir() else "",
        trust_status=trust_status,
        metadata={
            "path": str(source_path),
            "resolved_path": resolved_path,
            "exists": source_path.exists(),
            "is_dir": source_path.is_dir(),
            **dict(metadata or {}),
        },
    )
    boundary["content"]["sha256_scope"] = "resolved_path"
    return boundary


def write_untrusted_content_manifest(
    path: Path | str,
    content: bytes | str,
    *,
    source_kind: str,
    source_name: str = "",
    mime_type: str = "",
    trust_status: str = "untrusted",
    producer: str = "agilab",
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Persist boundary metadata next to imported or uploaded content."""

    manifest_path = Path(path).expanduser()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    boundary = build_untrusted_content_boundary(
        content,
        source_kind=source_kind,
        source_name=source_name,
        mime_type=mime_type,
        trust_status=trust_status,
        producer=producer,
        metadata=metadata,
    )
    manifest_path.write_text(json.dumps(boundary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def untrusted_content_notice(boundary: Mapping[str, Any]) -> str:
    source = boundary.get("source", {}) if isinstance(boundary, Mapping) else {}
    trust = boundary.get("trust", {}) if isinstance(boundary, Mapping) else {}
    content = boundary.get("content", {}) if isinstance(boundary, Mapping) else {}
    return (
        f"Untrusted content boundary: source={source.get('kind', 'unknown')}/"
        f"{source.get('name', '')}, trust={trust.get('status', 'untrusted')}, "
        f"sha256={content.get('sha256', '')}."
    )
