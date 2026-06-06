#!/usr/bin/env python3
"""Small deterministic caches for local AGILAB performance helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "agilab.performance-cache.v1"
DEFAULT_CACHE_PATH = REPO_ROOT / ".pytest_cache" / "agilab" / "performance_cache.json"


def _empty_cache() -> dict[str, object]:
    return {"schema": SCHEMA_VERSION, "entries": {}}


def _load_cache(cache_path: Path = DEFAULT_CACHE_PATH) -> dict[str, object]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_cache()
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA_VERSION:
        return _empty_cache()
    if not isinstance(payload.get("entries"), dict):
        return _empty_cache()
    return payload


def _write_cache(
    cache: dict[str, object], cache_path: Path = DEFAULT_CACHE_PATH
) -> None:
    entries = cache.get("entries")
    if not isinstance(entries, dict):
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_name(f"{cache_path.name}.tmp")
    tmp_path.write_text(
        json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp_path.replace(cache_path)


def file_signature(path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except OSError as exc:
        return {"state": "missing", "error": exc.__class__.__name__}
    return {
        "state": "file" if path.is_file() else "directory",
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "inode": getattr(stat, "st_ino", 0),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cached_file_sha256(
    path: Path,
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
    namespace: str = "file-sha256",
    use_cache: bool = True,
) -> str:
    resolved = path.expanduser().resolve()
    signature = file_signature(resolved)
    if signature.get("state") != "file":
        raise FileNotFoundError(str(resolved))

    cache = _load_cache(cache_path) if use_cache else _empty_cache()
    entries = cache.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        cache["entries"] = entries
    key = f"{namespace}:{resolved}"
    cached = entries.get(key)
    if (
        isinstance(cached, dict)
        and cached.get("signature") == signature
        and isinstance(cached.get("sha256"), str)
    ):
        return str(cached["sha256"])

    digest = _sha256_file(resolved)
    if use_cache:
        entries[key] = {"signature": signature, "sha256": digest}
        _write_cache(cache, cache_path)
    return digest


def manifest_digest(
    paths: Iterable[Path],
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
    namespace: str = "manifest",
    use_cache: bool = True,
) -> dict[str, object]:
    files: list[dict[str, object]] = []
    digest = hashlib.sha256()
    for raw_path in sorted(
        (path.expanduser() for path in paths), key=lambda item: item.as_posix()
    ):
        resolved = raw_path.resolve()
        signature = file_signature(resolved)
        entry: dict[str, object] = {
            "path": resolved.as_posix(),
            "signature": signature,
        }
        if signature.get("state") == "file":
            entry["sha256"] = cached_file_sha256(
                resolved,
                cache_path=cache_path,
                namespace=namespace,
                use_cache=use_cache,
            )
        files.append(entry)
        digest.update(
            json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
    return {"digest": digest.hexdigest(), "files": files}
