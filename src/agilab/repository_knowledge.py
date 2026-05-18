# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Static repository knowledge index for AGILAB onboarding evidence."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "agilab.repository_knowledge_index.v1"
RECORD_CACHE_SCHEMA = "agilab.repository_knowledge_record_cache.v1"
DEFAULT_RUN_ID = "repository-knowledge-index-proof"
CREATED_AT = "2026-04-25T00:00:43Z"
UPDATED_AT = "2026-04-25T00:00:43Z"
EXCLUDED_PARTS = frozenset(
    {
        ".git",
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


def default_record_cache_path(repo_root: Path) -> Path:
    cache_root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache").expanduser()
    repo_key = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:16]
    return cache_root / "agilab" / "repository_knowledge" / f"{repo_key}.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS for part in path.parts)


def _relative(repo_root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(repo_root)).replace("\\", "/")


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
    text = _read_text(path)
    try:
        tree = ast.parse(text)
    except SyntaxError:
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


def _file_record(
    repo_root: Path,
    path: Path,
    kind: str,
    *,
    stat_result: os.stat_result | None = None,
) -> dict[str, Any]:
    stat_result = stat_result or path.stat()
    record: dict[str, Any] = {
        "path": _relative(repo_root, path),
        "kind": kind,
        "suffix": path.suffix,
        "size_bytes": stat_result.st_size,
        "sha256": _sha256(path),
    }
    if path.suffix == ".py":
        record.update(_python_outline(path))
    else:
        record["heading"] = _first_heading(_read_text(path))
    return record


def _iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root] if not _is_excluded(root) else []
    files = []
    for path in root.rglob("*"):
        if path.is_file() and not _is_excluded(path):
            files.append(path)
    return sorted(files)


def _iter_named_files(root: Path, filename: str) -> list[Path]:
    if not root.exists():
        return []
    matches: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(dirname for dirname in dirnames if dirname not in EXCLUDED_PARTS)
        if filename in filenames:
            matches.append(Path(dirpath) / filename)
    return sorted(matches)


def _empty_record_cache() -> dict[str, Any]:
    return {"schema": RECORD_CACHE_SCHEMA, "entries": {}}


def _load_record_cache(path: Path | None) -> dict[str, Any]:
    if path is None:
        return _empty_record_cache()
    try:
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_record_cache()
    if not isinstance(data, dict) or data.get("schema") != RECORD_CACHE_SCHEMA:
        return _empty_record_cache()
    entries = data.get("entries")
    return {"schema": RECORD_CACHE_SCHEMA, "entries": entries if isinstance(entries, dict) else {}}


def _write_record_cache(path: Path | None, state: Mapping[str, Any]) -> None:
    if path is None:
        return
    entries = state.get("entries")
    if not isinstance(entries, dict):
        return
    payload = {"schema": RECORD_CACHE_SCHEMA, "entries": entries}
    try:
        cache_path = path.expanduser()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_name(f"{cache_path.name}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp_path.replace(cache_path)
    except OSError:
        return


def _record_signature(
    repo_root: Path,
    path: Path,
    kind: str,
    stat_result: os.stat_result | None = None,
) -> dict[str, Any]:
    stat_result = stat_result or path.stat()
    return {
        "repo_root": str(repo_root),
        "path": _relative(repo_root, path),
        "kind": kind,
        "suffix": path.suffix,
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
    }


def _cached_record(cache_state: Mapping[str, Any], signature: Mapping[str, Any]) -> dict[str, Any] | None:
    entries = cache_state.get("entries")
    if not isinstance(entries, dict):
        return None
    path_key = str(signature.get("path", ""))
    entry = entries.get(path_key)
    if not isinstance(entry, dict) or entry.get("signature") != dict(signature):
        return None
    record = entry.get("record")
    if not isinstance(record, dict):
        return None
    if (
        record.get("path") != signature.get("path")
        or record.get("kind") != signature.get("kind")
        or record.get("suffix") != signature.get("suffix")
        or record.get("size_bytes") != signature.get("size")
        or not isinstance(record.get("sha256"), str)
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
    stat_result = path.stat()
    signature = _record_signature(repo_root, path, kind, stat_result)
    record = _cached_record(cache_state or {}, signature)
    if record is None:
        record = _file_record(repo_root, path, kind, stat_result=stat_result)
    if updated_entries is not None:
        updated_entries[str(signature["path"])] = {"signature": signature, "record": record}
    return record


def _records(repo_root: Path, *, record_cache_path: Path | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    cache_state = _load_record_cache(record_cache_path) if record_cache_path is not None else None
    updated_entries: dict[str, Any] | None = {} if cache_state is not None else None
    scan_roots = [
        ("package_source", repo_root / "src" / "agilab"),
        ("tool", repo_root / "tools"),
        ("official_docs", repo_root / "docs" / "source"),
    ]
    seen: set[Path] = set()
    for kind, root in scan_roots:
        for path in _iter_files(root):
            if path in seen:
                continue
            if kind == "official_docs" and path.suffix not in DOC_SUFFIXES:
                continue
            if kind in {"package_source", "tool"} and path.suffix not in CODE_SUFFIXES:
                continue
            records.append(
                _record_with_cache(
                    repo_root,
                    path,
                    kind,
                    cache_state=cache_state,
                    updated_entries=updated_entries,
                )
            )
            seen.add(path)
    for path in _iter_named_files(repo_root, "pyproject.toml"):
        if path in seen or _is_excluded(path):
            continue
        records.append(
            _record_with_cache(
                repo_root,
                path,
                "package_manifest",
                cache_state=cache_state,
                updated_entries=updated_entries,
            )
        )
        seen.add(path)
    for filename in ROOT_RUNBOOKS:
        path = repo_root / filename
        if path.is_file() and path not in seen:
            records.append(
                _record_with_cache(
                    repo_root,
                    path,
                    "runbook",
                    cache_state=cache_state,
                    updated_entries=updated_entries,
                )
            )
            seen.add(path)
    if cache_state is not None and updated_entries is not None:
        _write_record_cache(record_cache_path, {"schema": RECORD_CACHE_SCHEMA, "entries": updated_entries})
    return sorted(records, key=lambda row: (str(row.get("kind", "")), str(row.get("path", ""))))


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
    records = _records(repo_root, record_cache_path=record_cache_path)
    indexed_paths = [str(record.get("path", "")) for record in records]
    excluded_existing = _excluded_existing(repo_root)
    excluded_path_hits = [
        path for path in indexed_paths if any(part in Path(path).parts for part in EXCLUDED_PARTS)
    ]
    kind_counts: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind", ""))
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    knowledge_maps = _knowledge_maps(records)
    query_seeds = _query_seeds()
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
        "indexed_file_count": len(records),
        "python_file_count": kind_counts.get("package_source", 0)
        + kind_counts.get("tool", 0),
        "tool_file_count": kind_counts.get("tool", 0),
        "docs_file_count": kind_counts.get("official_docs", 0),
        "pyproject_count": kind_counts.get("package_manifest", 0),
        "runbook_count": kind_counts.get("runbook", 0),
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


def write_repository_knowledge_index(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_repository_knowledge_index(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_repository_knowledge_index(
    *,
    repo_root: Path,
    output_path: Path,
    record_cache_path: Path | None = None,
) -> dict[str, Any]:
    state = build_repository_knowledge_index(
        repo_root=repo_root,
        record_cache_path=record_cache_path,
    )
    path = write_repository_knowledge_index(output_path, state)
    reloaded = load_repository_knowledge_index(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "indexed",
        "path": str(path),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
