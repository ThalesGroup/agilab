# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Static repository knowledge index for AGILAB onboarding evidence."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


SCHEMA = "agilab.repository_knowledge_index.v1"
RECORD_CACHE_SCHEMA = "agilab.repository_knowledge_record_cache.v1"
RECORD_SCHEMA = "agilab.repository_knowledge_record.v2"
DEFAULT_RUN_ID = "repository-knowledge-index-proof"
CREATED_AT = "2026-04-25T00:00:43Z"
UPDATED_AT = "2026-04-25T00:00:43Z"
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".tokki",
        ".env",
        ".cache",
        ".tox",
        "venv",
        "env",
        "wenv",
        "html",
        "target",
        "logs",
        "reports",
        "node_modules",
        "_build",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "artifacts",
        "build",
        "dist",
        "htmlcov",
        "log",
        ".missing-first-proof-log",
    }
)
DOC_SUFFIXES = {".md", ".rst", ".toml", ".json"}
CODE_SUFFIXES = {".py"}
ROOT_RUNBOOKS = ("README.md", "AGENTS.md", "CHANGELOG.md", "README.pypi.md")
MAX_SOURCE_FILE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_INDEX_BYTES = 32 * 1024 * 1024
MAX_INDEX_FILES = 10000
MAX_SCAN_ENTRIES = 50000
MAX_PATH_BYTES = 2048
MAX_PATH_DEPTH = 40
MAX_QUERY_BYTES = 512
MAX_QUERY_TOKENS = 16
MAX_RESULTS = 50
MAX_CONTEXT_LINES = 5
MAX_CONTEXT_BYTES = 2048
MAX_OUTPUT_BYTES = 65536
MAX_CROSSLINKS = 5
SOURCE_POLICY = "agilab.repository_knowledge_confined_source.v1"


class RepositoryKnowledgeError(ValueError):
    """An unsafe, stale, corrupt, or over-budget repository index."""


def _rebuild(reason: str) -> RepositoryKnowledgeError:
    return RepositoryKnowledgeError(
        reason + " Rebuild the index explicitly with --build-index."
    )


def _identity(info: os.stat_result) -> dict[str, int]:
    return {"device": info.st_dev, "inode": info.st_ino}


def _path_parts(value: str) -> tuple[str, ...]:
    try:
        encoded = value.encode("utf-8") if isinstance(value, str) else b""
    except UnicodeError:
        raise _rebuild("Invalid UTF-8 repository source path.") from None
    if (
        not isinstance(value, str)
        or not value
        or len(encoded) > MAX_PATH_BYTES
        or chr(92) in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise _rebuild("Invalid repository source path.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or len(path.parts) > MAX_PATH_DEPTH
        or _is_excluded(path)
    ):
        raise _rebuild("Unsafe or excluded repository source path.")
    return path.parts


def _open_directory(path: Path, *, create: bool = False) -> int:
    # Open every component relative to its parent descriptor so directory and
    # symlink swaps cannot redirect later source reads outside the selected root.
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise RepositoryKnowledgeError(
            "Safe repository indexing requires no-follow directory descriptors on this platform."
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    absolute = path.absolute()
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_regular_file(
    directory: int, name: str, *, max_bytes: int, label: str
) -> tuple[bytes, os.stat_result]:
    """Read a bounded, stable regular file from an already pinned parent."""
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise _rebuild(f"{label} is not a regular file.")
        if before.st_size > max_bytes:
            raise _rebuild(f"{label} exceeds the byte limit.")
        content = source.read(max_bytes + 1)
        after = os.fstat(source.fileno())
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        len(content) > max_bytes
        or len(content) != after.st_size
        or any(
            getattr(before, field) != getattr(after, field) for field in stable_fields
        )
    ):
        raise _rebuild(f"{label} changed during reading or exceeds the byte limit.")
    return content, after


def _write_atomic_file(
    path: Path,
    payload: bytes,
    *,
    label: str,
    _expected_parent: Mapping[str, int] | None = None,
) -> None:
    """Publish through one pinned parent; clean only an exclusively owned temp."""
    if not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")) or any(
        operation not in os.supports_dir_fd
        for operation in (os.open, os.mkdir, os.stat, os.unlink, os.rename)
    ):
        raise RepositoryKnowledgeError(
            "Safe repository publication requires no-follow directory descriptors "
            "on this platform."
        )
    absolute = path.expanduser().absolute()
    if ".." in absolute.parts:
        raise RepositoryKnowledgeError(
            "Output paths must not contain parent traversal ('..')."
        )
    directory = _open_directory(absolute.parent, create=_expected_parent is None)
    temporary = None
    descriptor = None
    try:
        if _expected_parent is not None and _identity(os.fstat(directory)) != dict(
            _expected_parent
        ):
            raise RepositoryKnowledgeError("Internal temporary output parent changed.")

        def check_target() -> None:
            try:
                target = os.stat(absolute.name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                return
            if not stat.S_ISREG(target.st_mode):
                raise RepositoryKnowledgeError(f"{label} must be a regular file.")

        check_target()
        candidate = f".{absolute.name}.{secrets.token_hex(16)}.tmp"
        descriptor = os.open(
            candidate,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        temporary = candidate
        output = os.fdopen(descriptor, "wb")
        descriptor = None
        with output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        check_target()
        os.replace(temporary, absolute.name, src_dir_fd=directory, dst_dir_fd=directory)
        temporary = None
        os.fsync(directory)
    finally:
        try:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                os.unlink(temporary, dir_fd=directory)
        finally:
            os.close(directory)


def _read_source(repo_root: Path, path: Path) -> tuple[bytes, os.stat_result]:
    root = repo_root.absolute()
    # Do not resolve the source path: that would follow an untrusted symlink.
    try:
        relative = path.absolute().relative_to(repo_root.absolute()).as_posix()
    except ValueError:
        raise _rebuild("Source path is outside the selected repository root.") from None
    parts = _path_parts(relative)
    directory = None
    try:
        directory = _open_directory(root)
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        return _read_regular_file(
            directory,
            parts[-1],
            max_bytes=MAX_SOURCE_FILE_BYTES,
            label="Repository source",
        )
    except FileNotFoundError:
        raise
    except OSError:
        raise _rebuild(
            "Repository source is unavailable or contains a symlink."
        ) from None
    finally:
        if directory is not None:
            os.close(directory)


def _json_utf8_bytes(value: Any, *, label: str, indent: int | None = None) -> bytes:
    """Reject malformed metadata, including nested values and object keys."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":") if indent is None else None,
            ensure_ascii=False,
            allow_nan=False,
            indent=indent,
        ).encode("utf-8")
    except (UnicodeError, TypeError, ValueError, RecursionError):
        raise _rebuild(f"Invalid UTF-8 or JSON {label}.") from None


def _source_fingerprint(
    records: list[dict[str, Any]], root: str, identity: dict[str, int]
) -> str:
    payload = {
        "records": records,
        "repo_root": root,
        "root_identity": identity,
        "policy": SOURCE_POLICY,
    }
    return hashlib.sha256(
        _json_utf8_bytes(payload, label="repository record metadata")
    ).hexdigest()


def _path_kind(value: str) -> str | None:
    path = PurePosixPath(value)
    if value in ROOT_RUNBOOKS:
        return "runbook"
    if path.name == "pyproject.toml":
        return "package_manifest"
    for prefix, kind, suffixes in (
        ("src/agilab/", "package_source", CODE_SUFFIXES),
        ("tools/", "tool", CODE_SUFFIXES),
        ("test/", "test", CODE_SUFFIXES),
        ("docs/source/", "official_docs", DOC_SUFFIXES),
    ):
        if value.startswith(prefix) and path.suffix in suffixes:
            return kind
    return None


def _check_artifact_path(repo_root: Path, path: Path) -> None:
    try:
        name = path.expanduser().resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return
    if not _is_excluded(PurePosixPath(name)) and _path_kind(name) is not None:
        raise RepositoryKnowledgeError(
            "Store the index and record cache outside indexed source paths."
        )


def default_record_cache_path(repo_root: Path) -> Path:
    cache_root = Path(
        os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    ).expanduser()
    repo_key = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:16]
    return cache_root / "agilab" / "repository_knowledge" / f"{repo_key}.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_excluded(path: Path) -> bool:
    parts = path.parts
    for index, part in enumerate(parts):
        # The Python reports package is maintained source, while other reports
        # directories contain generated evidence and remain excluded.
        if part == "reports" and parts[max(0, index - 2) : index] == ("src", "agilab"):
            continue
        if part in EXCLUDED_PARTS or part.startswith((".venv-", ".env-", ".cache-")):
            return True
    return False


def _relative(repo_root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if stripped and not stripped.startswith((".. ", ":", "|")):
            return stripped[:120]
    return ""


def _python_outline(path: Path) -> dict[str, Any]:
    return _python_outline_text(_read_text(path))


def _python_outline_text(text: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return {
            "docstring": "",
            "function_count": 0,
            "class_count": 0,
            "import_count": 0,
            "parse_status": "syntax_error",
        }
    functions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    docstring = ast.get_docstring(tree) or ""
    return {
        "docstring": docstring.splitlines()[0][:160] if docstring else "",
        "function_count": len(functions),
        "class_count": len(classes),
        "import_count": len(imports),
        "parse_status": "parsed",
    }


def _text_line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _file_record(
    repo_root: Path,
    path: Path,
    kind: str,
    *,
    stat_result: os.stat_result | None = None,
    content_hash: str | None = None,
    source_text: str | None = None,
) -> dict[str, Any]:
    if source_text is None:
        content, stat_result = _read_source(repo_root, path)
        content_hash = hashlib.sha256(content).hexdigest()
        source_text = content.decode("utf-8", errors="replace")
    assert stat_result is not None and content_hash is not None
    text = source_text
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "path": _relative(repo_root, path),
        "kind": kind,
        "suffix": path.suffix,
        "size_bytes": stat_result.st_size,
        "line_count": _text_line_count(text),
        "sha256": content_hash,
        "source_identity": _identity(stat_result),
    }
    if path.suffix == ".py":
        record.update(_python_outline_text(text))
    else:
        record["heading"] = _first_heading(text)
    return record


def _iter_files(root: Path) -> list[Path]:
    if _is_excluded(Path(root.name)):
        return []
    try:
        info = root.lstat()
    except FileNotFoundError:
        return []
    if stat.S_ISREG(info.st_mode):
        return [] if _is_excluded(Path(root.parent.name)) else [root]
    if not stat.S_ISDIR(info.st_mode):
        return []
    files: list[Path] = []
    visited = 0

    def walk(directory: int, current: Path, depth: int) -> None:
        nonlocal visited
        if depth > MAX_PATH_DEPTH:
            raise RepositoryKnowledgeError(
                "Repository scan exceeds the path-depth limit."
            )
        with os.scandir(directory) as entries:
            names = []
            for entry in entries:
                visited += 1
                if visited > MAX_SCAN_ENTRIES:
                    raise RepositoryKnowledgeError(
                        "Repository scan exceeds the entry limit."
                    )
                relative = (current / entry.name).relative_to(root)
                if root.name == "agilab" and root.parent.name == "src":
                    relative = Path("src/agilab") / relative
                if not _is_excluded(relative):
                    names.append(entry.name)
        for name in sorted(names):
            path = current / name
            try:
                entry_stat = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if stat.S_ISDIR(entry_stat.st_mode):
                    child = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=directory,
                    )
                    try:
                        walk(child, path, depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(entry_stat.st_mode):
                    files.append(path)
            except FileNotFoundError:
                continue

    try:
        directory = _open_directory(root)
    except OSError:
        raise _rebuild(
            "Repository scan root is unavailable or contains a symlink."
        ) from None
    try:
        walk(directory, root, 0)
    except OSError:
        raise _rebuild("Repository scan changed or contains a symlink.") from None
    finally:
        os.close(directory)
    return sorted(files)


def _iter_named_files(root: Path, filename: str) -> list[Path]:
    return [path for path in _iter_files(root) if path.name == filename]


def _empty_record_cache() -> dict[str, Any]:
    return {"schema": RECORD_CACHE_SCHEMA, "entries": {}}


def _load_record_cache(path: Path | None) -> dict[str, Any]:
    """Treat unsafe, unavailable, over-budget or corrupt disposable caches as misses."""
    if path is None:
        return _empty_record_cache()
    directory = None
    try:
        absolute = path.expanduser().absolute()
        directory = _open_directory(absolute.parent)
        payload, _ = _read_regular_file(
            directory, absolute.name, max_bytes=MAX_INDEX_BYTES, label="Record cache"
        )
        data = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_json_object
        )
    except (OSError, ValueError, RecursionError):
        return _empty_record_cache()
    finally:
        if directory is not None:
            os.close(directory)
    if not isinstance(data, dict) or data.get("schema") != RECORD_CACHE_SCHEMA:
        return _empty_record_cache()
    entries = data.get("entries")
    return {
        "schema": RECORD_CACHE_SCHEMA,
        "entries": entries if isinstance(entries, dict) else {},
    }


def _write_record_cache(path: Path | None, state: Mapping[str, Any]) -> None:
    """Best-effort atomic cache refresh; unsafe targets and write errors are skipped."""
    if path is None or not isinstance(state.get("entries"), dict):
        return
    try:
        payload = (
            json.dumps(
                {"schema": RECORD_CACHE_SCHEMA, "entries": state["entries"]},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        if len(payload) <= MAX_INDEX_BYTES:
            _write_atomic_file(path, payload, label="Record cache")
    except (OSError, ValueError, RecursionError):
        return


def _record_signature(
    repo_root: Path,
    path: Path,
    kind: str,
    stat_result: os.stat_result | None = None,
    content_hash: str | None = None,
) -> dict[str, Any]:
    stat_result = stat_result or path.stat()
    content_hash = content_hash or _sha256(path)
    return {
        "repo_root": str(repo_root.resolve()),
        "schema": RECORD_SCHEMA,
        "path": _relative(repo_root, path),
        "kind": kind,
        "suffix": path.suffix,
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
        "source_identity": _identity(stat_result),
        "sha256": content_hash,
    }


def _valid_record_shape(record: Mapping[str, Any]) -> bool:
    """Share the generated per-kind record contract across caches and indexes."""
    if (
        type(record.get("size_bytes")) is not int
        or not 0 <= record["size_bytes"] <= MAX_SOURCE_FILE_BYTES
        or type(record.get("line_count")) is not int
        or record["line_count"] < 0
    ):
        return False
    if record.get("suffix") != ".py":
        return isinstance(record.get("heading"), str)
    status = record.get("parse_status")
    counts = ("function_count", "class_count", "import_count")
    if (
        not isinstance(status, str)
        or status not in {"parsed", "syntax_error"}
        or not isinstance(record.get("docstring"), str)
        or any(
            type(record.get(field)) is not int or record[field] < 0 for field in counts
        )
    ):
        return False
    return status != "syntax_error" or (
        record["docstring"] == "" and all(record[field] == 0 for field in counts)
    )


def _cached_record(
    cache_state: Mapping[str, Any], signature: Mapping[str, Any]
) -> dict[str, Any] | None:
    entries = cache_state.get("entries")
    if not isinstance(entries, dict):
        return None
    path_key = str(signature.get("path", ""))
    entry = entries.get(path_key)
    if not isinstance(entry, dict):
        return None
    cached_signature = entry.get("signature")
    if (
        not isinstance(cached_signature, dict)
        or cached_signature != dict(signature)
        or any(
            type(cached_signature.get(field)) is not int
            for field in ("size", "mtime_ns")
        )
    ):
        return None
    record = entry.get("record")
    if not isinstance(record, dict):
        return None
    try:
        _json_utf8_bytes(record, label="cached record metadata")
    except RepositoryKnowledgeError:
        return None
    if any(
        not isinstance(identity, dict)
        or any(type(identity.get(field)) is not int for field in ("device", "inode"))
        for identity in (
            cached_signature.get("source_identity"),
            record.get("source_identity"),
        )
    ):
        return None
    if (
        record.get("schema") != signature.get("schema")
        or not _valid_record_shape(record)
        or record.get("path") != signature.get("path")
        or record.get("kind") != signature.get("kind")
        or record.get("suffix") != signature.get("suffix")
        or record.get("size_bytes") != signature.get("size")
        or record.get("sha256") != signature.get("sha256")
        or record.get("source_identity") != signature.get("source_identity")
    ):
        return None
    return dict(record)


def _record_with_cache(
    repo_root: Path,
    path: Path,
    kind: str,
    *,
    cache_state: Mapping[str, Any] | None,
    updated_entries: dict[str, Any] | None,
) -> dict[str, Any]:
    content, stat_result = _read_source(repo_root, path)
    content_hash = hashlib.sha256(content).hexdigest()
    signature = _record_signature(repo_root, path, kind, stat_result, content_hash)
    record = _cached_record(cache_state or {}, signature)
    source_text = content.decode("utf-8", errors="replace")
    if record is None or record["line_count"] != _text_line_count(source_text):
        record = _file_record(
            repo_root,
            path,
            kind,
            stat_result=stat_result,
            content_hash=content_hash,
            source_text=source_text,
        )
    if updated_entries is not None:
        updated_entries[str(signature["path"])] = {
            "signature": signature,
            "record": record,
        }
    return record


def _append_record_if_available(
    records: list[dict[str, Any]],
    *,
    repo_root: Path,
    path: Path,
    kind: str,
    cache_state: Mapping[str, Any] | None,
    updated_entries: dict[str, Any] | None,
) -> bool:
    try:
        record = _record_with_cache(
            repo_root,
            path,
            kind,
            cache_state=cache_state,
            updated_entries=updated_entries,
        )
    except FileNotFoundError:
        return False
    records.append(record)
    return True


def _candidate_paths(repo_root: Path) -> list[tuple[str, Path]]:
    # The manifest scan already requires the complete bounded public inventory.
    # Classify that same inventory once, with the precedence used by validation.
    candidates = []
    for path in sorted(set(_iter_files(repo_root))):
        kind = _path_kind(path.relative_to(repo_root).as_posix())
        if kind is not None:
            candidates.append((kind, path))
    if len(candidates) > MAX_INDEX_FILES:
        raise RepositoryKnowledgeError("Repository index exceeds the file-count limit.")
    return sorted(candidates, key=lambda item: item[1].as_posix())


def _records(
    repo_root: Path,
    *,
    record_cache_path: Path | None = None,
    canonical_root: bool = False,
) -> list[dict[str, Any]]:
    repo_root = repo_root if canonical_root else repo_root.resolve()
    records: list[dict[str, Any]] = []
    cache_state = (
        _load_record_cache(record_cache_path) if record_cache_path is not None else None
    )
    updated_entries: dict[str, Any] | None = {} if cache_state is not None else None
    total_size = 0
    for kind, path in _candidate_paths(repo_root):
        if _append_record_if_available(
            records,
            repo_root=repo_root,
            path=path,
            kind=kind,
            cache_state=cache_state,
            updated_entries=updated_entries,
        ):
            total_size += records[-1]["size_bytes"]
            if total_size > MAX_SOURCE_BYTES:
                raise RepositoryKnowledgeError(
                    "Repository source exceeds the total byte budget."
                )
    if cache_state is not None and updated_entries is not None:
        _write_record_cache(
            record_cache_path,
            {"schema": RECORD_CACHE_SCHEMA, "entries": updated_entries},
        )
    return sorted(
        records, key=lambda row: (str(row.get("kind", "")), str(row.get("path", "")))
    )


def _excluded_existing(repo_root: Path) -> list[str]:
    try:
        existing_names = {path.name for path in repo_root.iterdir()}
    except OSError:
        existing_names = set()
    return sorted(
        part
        for part in EXCLUDED_PARTS
        if (repo_root / part).exists() or part in existing_names
    )


def _knowledge_maps(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind", ""))
        counts[kind] = counts.get(kind, 0) + 1
    return [
        {
            "id": "official_docs",
            "label": "Official documentation source",
            "record_count": counts.get("official_docs", 0),
            "source_of_truth": True,
        },
        {
            "id": "code_index",
            "label": "Python source and tool index",
            "record_count": counts.get("package_source", 0) + counts.get("tool", 0),
            "source_of_truth": False,
        },
        {
            "id": "test_index",
            "label": "Root regression test index",
            "record_count": counts.get("test", 0),
            "source_of_truth": False,
        },
        {
            "id": "package_manifests",
            "label": "Package and app manifest index",
            "record_count": counts.get("package_manifest", 0),
            "source_of_truth": False,
        },
        {
            "id": "runbooks",
            "label": "Root runbook index",
            "record_count": counts.get("runbook", 0),
            "source_of_truth": False,
        },
    ]


def _record_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    kind_counts: dict[str, int] = {}
    kind_line_counts: dict[str, int] = {}
    suffix_counts: dict[str, int] = {}
    suffix_line_counts: dict[str, int] = {}
    total_size_bytes = 0
    total_line_count = 0

    for record in records:
        kind = str(record.get("kind", "") or "unknown")
        suffix = str(record.get("suffix", "") or "[no extension]")
        line_count = int(record.get("line_count", 0) or 0)
        size_bytes = int(record.get("size_bytes", 0) or 0)
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        kind_line_counts[kind] = kind_line_counts.get(kind, 0) + line_count
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        suffix_line_counts[suffix] = suffix_line_counts.get(suffix, 0) + line_count
        total_line_count += line_count
        total_size_bytes += size_bytes

    return {
        "kind_counts": dict(sorted(kind_counts.items())),
        "kind_line_counts": dict(sorted(kind_line_counts.items())),
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "suffix_line_counts": dict(sorted(suffix_line_counts.items())),
        "total_line_count": total_line_count,
        "total_size_bytes": total_size_bytes,
    }


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _count_rows(
    counts: Mapping[str, int], line_counts: Mapping[str, int]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, file_count in counts.items():
        line_count = int(line_counts.get(name, 0) or 0)
        rows.append(
            {
                "id": name,
                "file_count": int(file_count or 0),
                "line_count": line_count,
                "average_lines_per_file": _safe_ratio(line_count, int(file_count or 0)),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["line_count"]), str(row["id"])))


def _top_count_rows(
    counts: Mapping[str, int], line_counts: Mapping[str, int], *, limit: int
) -> list[dict[str, Any]]:
    return _count_rows(counts, line_counts)[:limit]


def _largest_file_rows(
    records: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    rows = [
        {
            "path": str(record.get("path", "")),
            "kind": str(record.get("kind", "")),
            "suffix": str(record.get("suffix", "") or "[no extension]"),
            "line_count": int(record.get("line_count", 0) or 0),
            "size_bytes": int(record.get("size_bytes", 0) or 0),
        }
        for record in records
    ]
    return sorted(rows, key=lambda row: (-int(row["line_count"]), str(row["path"])))[
        :limit
    ]


def _query_seeds() -> list[dict[str, str]]:
    return [
        {
            "id": "evidence_flow",
            "question": "Which reports feed the public KPI evidence bundle?",
            "entrypoint": "tools/kpi_evidence_bundle.py",
        },
        {
            "id": "connector_flow",
            "question": "How do connector catalogs reach Release Decision UI evidence?",
            "entrypoint": "src/agilab/data_connector_view_surface.py",
        },
        {
            "id": "dag_flow",
            "question": "Where is the product-level DAG contract assembled?",
            "entrypoint": "tools/global_pipeline_dag_report.py",
        },
        {
            "id": "docs_source",
            "question": "Which versioned docs remain the source of truth?",
            "entrypoint": "docs/source",
        },
    ]


def build_repository_knowledge_index(
    *,
    repo_root: Path,
    run_id: str = DEFAULT_RUN_ID,
    record_cache_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if record_cache_path is not None:
        _check_artifact_path(repo_root, record_cache_path)
    records = _records(
        repo_root, record_cache_path=record_cache_path, canonical_root=True
    )
    indexed_paths = [str(record.get("path", "")) for record in records]
    excluded_existing = _excluded_existing(repo_root)
    excluded_path_hits = [
        path for path in indexed_paths if _is_excluded(PurePosixPath(path))
    ]
    stats = _record_stats(records)
    kind_counts = stats["kind_counts"]
    kind_line_counts = stats["kind_line_counts"]
    suffix_counts = stats["suffix_counts"]
    suffix_line_counts = stats["suffix_line_counts"]
    knowledge_maps = _knowledge_maps(records)
    query_seeds = _query_seeds()
    source_line_count = kind_line_counts.get("package_source", 0)
    tool_line_count = kind_line_counts.get("tool", 0)
    code_line_count = source_line_count + tool_line_count
    test_line_count = kind_line_counts.get("test", 0)
    docs_line_count = kind_line_counts.get("official_docs", 0)
    pyproject_line_count = kind_line_counts.get("package_manifest", 0)
    runbook_line_count = kind_line_counts.get("runbook", 0)
    indexed_file_count = len(records)
    issues = []
    if excluded_path_hits:
        issues.append(
            {
                "level": "error",
                "location": "exclusion_guardrail",
                "message": "excluded paths were indexed",
                "paths": excluded_path_hits,
            }
        )
    if not kind_counts.get("official_docs", 0):
        issues.append(
            {
                "level": "error",
                "location": "official_docs",
                "message": "official documentation was not indexed",
            }
        )
    summary = {
        "execution_mode": "repository_knowledge_static_index",
        "indexed_file_count": indexed_file_count,
        "source_file_count": kind_counts.get("package_source", 0),
        "code_file_count": kind_counts.get("package_source", 0)
        + kind_counts.get("tool", 0),
        "python_file_count": kind_counts.get("package_source", 0)
        + kind_counts.get("tool", 0)
        + kind_counts.get("test", 0),
        "tool_file_count": kind_counts.get("tool", 0),
        "test_file_count": kind_counts.get("test", 0),
        "docs_file_count": kind_counts.get("official_docs", 0),
        "pyproject_count": kind_counts.get("package_manifest", 0),
        "runbook_count": kind_counts.get("runbook", 0),
        "total_line_count": stats["total_line_count"],
        "source_line_count": source_line_count,
        "code_line_count": code_line_count,
        "python_line_count": kind_line_counts.get("package_source", 0)
        + tool_line_count
        + kind_line_counts.get("test", 0),
        "tool_line_count": tool_line_count,
        "test_line_count": test_line_count,
        "docs_line_count": docs_line_count,
        "pyproject_line_count": pyproject_line_count,
        "runbook_line_count": runbook_line_count,
        "total_size_bytes": stats["total_size_bytes"],
        "kind_counts": stats["kind_counts"],
        "kind_line_counts": stats["kind_line_counts"],
        "suffix_counts": stats["suffix_counts"],
        "suffix_line_counts": suffix_line_counts,
        "average_lines_per_indexed_file": _safe_ratio(
            stats["total_line_count"], indexed_file_count
        ),
        "test_to_code_line_ratio": _safe_ratio(test_line_count, code_line_count),
        "docs_to_code_line_ratio": _safe_ratio(docs_line_count, code_line_count),
        "manifest_to_code_line_ratio": _safe_ratio(
            pyproject_line_count, code_line_count
        ),
        "top_kinds_by_lines": _top_count_rows(kind_counts, kind_line_counts, limit=8),
        "top_suffixes_by_lines": _top_count_rows(
            suffix_counts, suffix_line_counts, limit=8
        ),
        "largest_files_by_lines": _largest_file_rows(records, limit=10),
        "knowledge_map_count": len(knowledge_maps),
        "query_seed_count": len(query_seeds),
        "excluded_root_count": len(EXCLUDED_PARTS),
        "excluded_existing_count": len(excluded_existing),
        "excluded_path_hit_count": len(excluded_path_hits),
        "generated_wiki_source_of_truth": False,
        "official_docs_source_of_truth": True,
        "private_repository_indexed": False,
        "command_execution_count": 0,
        "network_probe_count": 0,
    }
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "indexed" if not issues else "invalid",
        "execution_mode": summary["execution_mode"],
        "summary": summary,
        "records": records,
        "repo_root": str(repo_root),
        "root_identity": _identity(repo_root.stat()),
        "source_policy": SOURCE_POLICY,
        "source_fingerprint": _source_fingerprint(
            records, str(repo_root), _identity(repo_root.stat())
        ),
        "knowledge_maps": knowledge_maps,
        "query_seeds": query_seeds,
        "excluded_roots": sorted(EXCLUDED_PARTS),
        "excluded_existing_roots": excluded_existing,
        "issues": issues,
        "provenance": {
            "executes_commands": False,
            "queries_network": False,
            "source": "local_repository_files",
            "generated_content_source_of_truth": False,
            "official_docs_remain_source_of_truth": True,
        },
    }


def write_repository_knowledge_index(
    path: Path,
    state: Mapping[str, Any],
    *,
    _expected_parent: Mapping[str, int] | None = None,
) -> Path:
    path = path.expanduser()
    if path.suffix != ".json":
        raise RepositoryKnowledgeError(
            "Repository index output must be a regular .json file."
        )
    payload = (
        _json_utf8_bytes(state, label="repository index metadata", indent=2) + b"\n"
    )
    if len(payload) > MAX_INDEX_BYTES:
        raise RepositoryKnowledgeError("Repository index exceeds the byte limit.")
    _write_atomic_file(
        path,
        payload,
        label="Repository index output",
        _expected_parent=_expected_parent,
    )
    return path


def _validate_index_metadata(state: Mapping[str, Any]) -> None:
    status = state.get("run_status")
    if not isinstance(status, str) or status not in ("indexed", "invalid"):
        raise _rebuild("Invalid or missing repository index run_status.")
    for field in ("run_id", "created_at", "updated_at"):
        value = state.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > MAX_PATH_BYTES
        ):
            raise _rebuild(f"Invalid or missing repository index {field}.")
    mode = "repository_knowledge_static_index"
    if state.get("execution_mode") != mode:
        raise _rebuild("Invalid or missing repository index execution_mode.")
    for field, item_type in (
        ("knowledge_maps", dict),
        ("query_seeds", dict),
        ("excluded_roots", str),
        ("excluded_existing_roots", str),
        ("issues", dict),
    ):
        value = state.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, item_type) for item in value
        ):
            raise _rebuild(f"Invalid or missing repository index {field}.")
    if (status == "indexed") != (not state["issues"]):
        raise _rebuild("Repository index run_status disagrees with its issues.")
    summary = state.get("summary")
    if (
        not isinstance(summary, dict)
        or summary.get("execution_mode") != mode
        or any(
            type(summary.get(field)) is not int or summary[field] < 0
            for field in ("indexed_file_count", "total_line_count", "total_size_bytes")
        )
    ):
        raise _rebuild("Invalid or missing repository index summary.")
    provenance = state.get("provenance")
    expected = {
        "executes_commands": False,
        "queries_network": False,
        "source": "local_repository_files",
        "generated_content_source_of_truth": False,
        "official_docs_remain_source_of_truth": True,
    }
    if not isinstance(provenance, dict) or any(
        type(provenance.get(key)) is not type(value) or provenance[key] != value
        for key, value in expected.items()
    ):
        raise _rebuild("Invalid or missing repository index provenance.")


def _validated_sources(
    state: Mapping[str, Any],
    repo_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, bytes]]:
    root = repo_root.absolute()
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise _rebuild("Unsupported or corrupt repository index.")
    _json_utf8_bytes(state, label="repository index metadata")
    _validate_index_metadata(state)
    if state.get("repo_root") != str(root) or state.get("root_identity") != _identity(
        root.stat()
    ):
        raise _rebuild("Repository index root mismatch.")
    if state.get("source_policy") != SOURCE_POLICY:
        raise _rebuild("Repository index source policy mismatch.")
    records = state.get("records")
    if not isinstance(records, list) or len(records) > MAX_INDEX_FILES:
        raise _rebuild("Invalid repository index record count.")
    by_path = {}
    total = 0
    for record in records:
        if not isinstance(record, dict):
            raise _rebuild("Invalid repository index record.")
        name = record.get("path")
        _path_parts(name)
        if name in by_path:
            raise _rebuild("Duplicate repository index path.")
        digest = record.get("sha256")
        size = record.get("size_bytes")
        if (
            record.get("schema") != RECORD_SCHEMA
            or record.get("kind") != _path_kind(name)
            or record.get("suffix") != PurePosixPath(name).suffix
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or not _valid_record_shape(record)
            or not isinstance(record.get("source_identity"), dict)
        ):
            raise _rebuild("Invalid repository index record metadata.")
        by_path[name] = record
        total += size
    if total > MAX_SOURCE_BYTES:
        raise _rebuild("Repository index exceeds the source byte budget.")
    summary = state["summary"]
    if (
        summary["indexed_file_count"] != len(records)
        or summary["total_size_bytes"] != total
        or summary["total_line_count"]
        != sum(record["line_count"] for record in records)
    ):
        raise _rebuild("Repository index summary disagrees with its records.")
    fingerprint = _source_fingerprint(records, str(root), _identity(root.stat()))
    if state.get("source_fingerprint") != fingerprint:
        raise _rebuild("Repository index fingerprint mismatch.")
    current = {
        path.relative_to(root).as_posix(): kind for kind, path in _candidate_paths(root)
    }
    if current != {name: record["kind"] for name, record in by_path.items()}:
        raise _rebuild("Repository source inventory changed.")
    contents = {}
    for name, record in sorted(by_path.items()):
        try:
            content, info = _read_source(root, root / name)
        except FileNotFoundError:
            raise _rebuild("Repository source is missing.") from None
        if (
            _identity(info) != record["source_identity"]
            or len(content) != record["size_bytes"]
            or hashlib.sha256(content).hexdigest() != record["sha256"]
            or _text_line_count(content.decode("utf-8", errors="replace"))
            != record["line_count"]
        ):
            raise _rebuild("Repository source bytes or identity changed.")
        contents[name] = content
    return by_path, contents


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _rebuild("Duplicate repository index object key.")
        result[key] = value
    return result


def load_repository_knowledge_index(
    path: Path, *, repo_root: Path | None = None
) -> dict[str, Any]:
    """Reload an index only against an explicitly selected, unchanged repository."""
    if repo_root is None:
        raise RepositoryKnowledgeError(
            "An explicit repo_root is required to verify the index."
        )
    directory = None
    try:
        absolute = path.expanduser().absolute()
        directory = _open_directory(absolute.parent)
        payload, _ = _read_regular_file(
            directory,
            absolute.name,
            max_bytes=MAX_INDEX_BYTES,
            label="Repository index",
        )
        state = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_json_object
        )
    except (OSError, ValueError, RecursionError):
        raise _rebuild("Unreadable or corrupt repository index.") from None
    finally:
        if directory is not None:
            os.close(directory)
    _validated_sources(state, repo_root.resolve())
    return state


def _source_link(record: Mapping[str, Any], line: int = 1) -> dict[str, Any]:
    return {
        "path": record["path"],
        "kind": record["kind"],
        "sha256": record["sha256"],
        "line": line,
        "source_ref": record["path"] + "#L" + str(line),
    }


def _literal_crosslinks(
    text: str,
    current: str,
    records: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    # Require exact indexed paths in source, never an inferred relationship.
    delimiters = str.maketrans({c: " " for c in "\"'[](){}<>:,;=#" + chr(96)})
    found = {}
    for number, line in enumerate(text.splitlines(), 1):
        for token in line.translate(delimiters).split():
            if token != current and token in records and token not in found:
                found[token] = {
                    **_source_link(records[token]),
                    "from_line": number,
                    "relationship": "literal_path_reference",
                }
                if len(found) == MAX_CROSSLINKS:
                    return [found[key] for key in sorted(found)]
    return [found[key] for key in sorted(found)]


def _excerpt(
    lines: list[str],
    number: int,
    terms: list[str],
    context_lines: int,
    budget: int,
) -> tuple[str, int, int, bool]:
    start, end = (
        max(0, number - context_lines),
        min(len(lines), number + context_lines + 1),
    )
    excerpt = "\n".join(lines[start:end])
    if len(excerpt.encode("utf-8")) <= budget:
        return excerpt, start + 1, end, False
    line = lines[number]
    term = terms[0]
    offset = len(line[: line.find(term)].encode("utf-8"))
    begin = max(0, offset - (budget - len(term.encode("utf-8"))) // 2)
    excerpt = line.encode("utf-8")[begin : begin + budget].decode(
        "utf-8", errors="ignore"
    )
    return excerpt, number + 1, number + 1, True


def _query_utf8_bytes(query: str) -> bytes:
    try:
        return query.encode("utf-8") if isinstance(query, str) else b""
    except UnicodeError:
        raise RepositoryKnowledgeError(
            "Use a valid UTF-8 query of at most 512 bytes."
        ) from None


def search_repository_knowledge_index(
    state: Mapping[str, Any],
    *,
    repo_root: Path,
    query: str,
    mode: str = "literal",
    limit: int = 10,
    context_lines: int = 2,
    context_bytes: int = 1024,
    output_bytes: int = 32768,
) -> dict[str, Any]:
    """Search verified source lines with finite, case-sensitive literal terms."""
    query_bytes = _query_utf8_bytes(query)
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query_bytes) > MAX_QUERY_BYTES
        or any(ord(c) < 32 or ord(c) == 127 for c in query)
        or mode not in {"literal", "tokens"}
    ):
        raise RepositoryKnowledgeError(
            "Use a nonempty single-line literal query of at most 512 UTF-8 bytes."
        )
    terms = [query] if mode == "literal" else query.split()
    if len(terms) > MAX_QUERY_TOKENS:
        raise RepositoryKnowledgeError("Token search accepts at most 16 terms.")
    for value, lower, upper, label in (
        (limit, 1, MAX_RESULTS, "result count"),
        (context_lines, 0, MAX_CONTEXT_LINES, "context lines"),
        (context_bytes, MAX_QUERY_BYTES, MAX_CONTEXT_BYTES, "context UTF-8 bytes"),
        (output_bytes, 2048, MAX_OUTPUT_BYTES, "output UTF-8 bytes"),
    ):
        if type(value) is not int or not lower <= value <= upper:
            raise RepositoryKnowledgeError(
                f"Invalid {label}; allowed range is {lower} to {upper}."
            )
    root = repo_root.resolve()
    records, contents = _validated_sources(state, root)
    result = {
        "schema": "agilab.repository_knowledge_search.v1",
        "status": "pass",
        "source_fingerprint": state["source_fingerprint"],
        "query": query,
        "mode": mode,
        "match_count": 0,
        "results": [],
        "results_truncated": False,
        "official_documentation": [],
        "authority": "Versioned docs/source files remain authoritative. Crosslinks are literal path references.",
        "limits": {
            "results": limit,
            "context_lines": context_lines,
            "context_utf8_bytes": context_bytes,
            "output_utf8_bytes": output_bytes,
        },
    }
    docs = {}
    checked = set()
    for name, record in sorted(records.items()):
        text = contents[name].decode("utf-8", errors="replace")
        lines = text.splitlines()
        links = None
        for number, line in enumerate(lines):
            if not all(term in line for term in terms):
                continue
            result["match_count"] += 1
            if len(result["results"]) >= limit:
                continue
            excerpt, start, end, clipped = _excerpt(
                lines, number, terms, context_lines, context_bytes
            )
            if links is None:
                links = _literal_crosslinks(text, name, records)
            hit = {
                **_source_link(record, number + 1),
                "line_start": start,
                "line_end": end,
                "excerpt": excerpt,
                "excerpt_truncated": clipped,
                "crosslinks": links,
            }
            result["results"].append(hit)
            checked.add(name)
            if record["kind"] == "official_docs":
                docs.setdefault(name, _source_link(record, number + 1))
            for link in links:
                checked.add(link["path"])
                if link["kind"] == "official_docs":
                    docs.setdefault(link["path"], _source_link(records[link["path"]]))
    result["official_documentation"] = [
        docs[name] for name in sorted(docs)[:MAX_CROSSLINKS]
    ]
    result["results_truncated"] = result["match_count"] > len(result["results"])
    # Bound the pretty representation too; compact CLI output is never larger.
    while (
        len(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False).encode(
                "utf-8"
            )
        )
        + 1
        > output_bytes
    ):
        if result["results"]:
            result["results"].pop()
            result["results_truncated"] = True
        elif result["official_documentation"]:
            result["official_documentation"].pop()
        else:
            raise RepositoryKnowledgeError(
                "Query metadata exceeds the output UTF-8 byte budget."
            )
    for name in sorted(checked):
        try:
            current, info = _read_source(root, root / name)
        except FileNotFoundError:
            raise _rebuild("Repository source disappeared during search.") from None
        if (
            current != contents[name]
            or _identity(info) != records[name]["source_identity"]
        ):
            raise _rebuild("Repository source changed during search.")
    return result


def persist_repository_knowledge_index(
    *,
    repo_root: Path,
    output_path: Path,
    record_cache_path: Path | None = None,
    _expected_parent: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    _check_artifact_path(repo_root, output_path)
    state = build_repository_knowledge_index(
        repo_root=repo_root,
        record_cache_path=record_cache_path,
    )
    path = write_repository_knowledge_index(
        output_path, state, _expected_parent=_expected_parent
    )
    reloaded = load_repository_knowledge_index(path, repo_root=repo_root)
    return {
        "ok": state == reloaded and state.get("run_status") == "indexed",
        "path": str(path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
