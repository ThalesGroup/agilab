#!/usr/bin/env python3
"""Emit AGILAB repository knowledge-index evidence."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Any, Iterator, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_RELATIVE_PATH = Path("docs/source/features.rst")


def _ensure_repo_on_path(repo_root: Path) -> None:
    src_root = repo_root / "src"
    for entry in (str(src_root), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    package = sys.modules.get("agilab")
    package_path = str(src_root / "agilab")
    package_paths = getattr(package, "__path__", None)
    if package_paths is not None and package_path not in list(package_paths):
        try:
            package_paths.append(package_path)
        except AttributeError:
            package.__path__ = [*package_paths, package_path]


_ensure_repo_on_path(REPO_ROOT)

from agilab.repository_knowledge import (  # noqa: E402
    SCHEMA,
    RepositoryKnowledgeError,
    _identity,
    _open_directory,
    _query_utf8_bytes,
    _read_source,
    default_record_cache_path,
    load_repository_knowledge_index,
    search_repository_knowledge_index,
    persist_repository_knowledge_index,
)


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "evidence": list(evidence),
        "details": details or {},
    }


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "repository knowledge index report",
        "tools/repository_knowledge_report.py --compact",
        "agilab.repository_knowledge_index.v1",
        "repository_knowledge_static_index",
        "root tests",
        "deterministic file, line, size, kind, and suffix statistics",
        "generated wiki as an exploration aid",
    ]
    doc_path = repo_root / DOC_RELATIVE_PATH
    try:
        content, _ = _read_source(repo_root, doc_path)
        text = " ".join(content.decode("utf-8").split())
        missing = [needle for needle in required if needle not in text]
        ok = not missing
        details = {"missing": missing}
    except (RepositoryKnowledgeError, OSError, UnicodeError) as exc:
        ok = False
        details = {"error": str(exc)[:512]}
    return _check_result(
        "repository_knowledge_docs_reference",
        "Repository knowledge docs reference",
        ok,
        (
            "features docs expose the repository knowledge-index command"
            if ok
            else "features docs do not expose the repository knowledge-index command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


@contextmanager
def _temporary_report_output() -> Iterator[tuple[Path, dict[str, int]]]:
    # Only the internally selected temporary root may follow system aliases.
    # Caller-supplied output and cache paths retain the strict no-follow writer.
    root = Path(tempfile.gettempdir()).resolve(strict=True)
    parent = _open_directory(root)
    name = f"agilab-repository-knowledge-{secrets.token_hex(16)}"
    directory = None
    identity = None
    filename = "repository_knowledge_index.json"
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent)
        identity = _identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
        directory = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
        )
        if _identity(os.fstat(directory)) != identity:
            raise RepositoryKnowledgeError("Internal temporary directory changed.")
        yield root / name / filename, identity
    finally:
        try:
            if directory is not None:
                try:
                    os.unlink(filename, dir_fd=directory)
                except FileNotFoundError:
                    pass
                finally:
                    os.close(directory)
            if identity is not None:
                try:
                    current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    if _identity(current) == identity:
                        os.rmdir(name, dir_fd=parent)
        finally:
            os.close(parent)


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    output_path: Path | None = None,
    record_cache_path: Path | None = None,
    use_record_cache: bool = True,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    effective_cache_path = (
        record_cache_path
        if use_record_cache and record_cache_path is not None
        else default_record_cache_path(repo_root)
        if use_record_cache
        else None
    )
    if output_path is None:
        with _temporary_report_output() as (temporary_output, parent_identity):
            return _build_report_with_path(
                repo_root=repo_root,
                output_path=temporary_output,
                record_cache_path=effective_cache_path,
                _expected_parent=parent_identity,
            )
    return _build_report_with_path(
        repo_root=repo_root,
        output_path=output_path,
        record_cache_path=effective_cache_path,
    )


def _build_report_with_path(
    *,
    repo_root: Path,
    output_path: Path,
    record_cache_path: Path | None,
    _expected_parent: dict[str, int] | None = None,
) -> dict[str, Any]:
    proof = persist_repository_knowledge_index(
        repo_root=repo_root,
        output_path=output_path,
        record_cache_path=record_cache_path,
        _expected_parent=_expected_parent,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    excluded_roots = set(state.get("excluded_roots", []))
    checks = [
        _check_result(
            "repository_knowledge_schema",
            "Repository knowledge schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "indexed"
            and state.get("execution_mode") == "repository_knowledge_static_index",
            "repository knowledge index uses the supported schema",
            evidence=["src/agilab/repository_knowledge.py"],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "round_trip_ok": proof["round_trip_ok"],
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "repository_knowledge_code_docs_runbooks",
            "Repository knowledge code/docs/runbook coverage",
            int(summary.get("python_file_count", 0) or 0) > 20
            and int(summary.get("tool_file_count", 0) or 0) > 10
            and int(summary.get("test_file_count", 0) or 0) > 10
            and int(summary.get("docs_file_count", 0) or 0) > 10
            and int(summary.get("runbook_count", 0) or 0) >= 3,
            "index covers source files, tools, tests, official docs, and root runbooks",
            evidence=[
                "src/agilab",
                "tools",
                "test",
                "docs/source",
                "README.md",
                "AGENTS.md",
            ],
            details={"summary": summary},
        ),
        _check_result(
            "repository_knowledge_statistics",
            "Repository knowledge statistics",
            int(summary.get("total_line_count", 0) or 0) > 0
            and int(summary.get("python_line_count", 0) or 0) > 0
            and int(summary.get("docs_line_count", 0) or 0) > 0
            and int(summary.get("test_line_count", 0) or 0) > 0
            and int(summary.get("total_size_bytes", 0) or 0) > 0
            and isinstance(summary.get("kind_counts"), dict)
            and isinstance(summary.get("kind_line_counts"), dict)
            and isinstance(summary.get("suffix_counts"), dict)
            and isinstance(summary.get("suffix_line_counts"), dict)
            and isinstance(summary.get("top_kinds_by_lines"), list)
            and isinstance(summary.get("top_suffixes_by_lines"), list)
            and isinstance(summary.get("largest_files_by_lines"), list)
            and float(summary.get("average_lines_per_indexed_file", 0) or 0) > 0
            and float(summary.get("test_to_code_line_ratio", 0) or 0) > 0
            and float(summary.get("docs_to_code_line_ratio", 0) or 0) > 0,
            "index exposes deterministic file, line, size, ratio, top-kind, and suffix statistics",
            evidence=["src/agilab/repository_knowledge.py"],
            details={
                "total_line_count": summary.get("total_line_count", 0),
                "python_line_count": summary.get("python_line_count", 0),
                "docs_line_count": summary.get("docs_line_count", 0),
                "test_line_count": summary.get("test_line_count", 0),
                "total_size_bytes": summary.get("total_size_bytes", 0),
                "average_lines_per_indexed_file": summary.get(
                    "average_lines_per_indexed_file", 0
                ),
                "test_to_code_line_ratio": summary.get("test_to_code_line_ratio", 0),
                "docs_to_code_line_ratio": summary.get("docs_to_code_line_ratio", 0),
                "manifest_to_code_line_ratio": summary.get(
                    "manifest_to_code_line_ratio", 0
                ),
                "kind_counts": summary.get("kind_counts", {}),
                "kind_line_counts": summary.get("kind_line_counts", {}),
                "suffix_counts": summary.get("suffix_counts", {}),
                "suffix_line_counts": summary.get("suffix_line_counts", {}),
                "top_kinds_by_lines": summary.get("top_kinds_by_lines", []),
                "top_suffixes_by_lines": summary.get("top_suffixes_by_lines", []),
                "largest_files_by_lines": summary.get("largest_files_by_lines", []),
            },
        ),
        _check_result(
            "repository_knowledge_package_manifests",
            "Repository knowledge package manifests",
            int(summary.get("pyproject_count", 0) or 0) >= 8,
            "index includes root, core, app, and page package manifests",
            evidence=["pyproject.toml", "src/agilab"],
            details={"pyproject_count": summary.get("pyproject_count", 0)},
        ),
        _check_result(
            "repository_knowledge_exclusion_guardrails",
            "Repository knowledge exclusion guardrails",
            {"artifacts", ".venv", "build", "dist"}.issubset(excluded_roots)
            and summary.get("excluded_path_hit_count") == 0,
            "index excludes generated artifacts, virtualenvs, build outputs, and distributions",
            evidence=["src/agilab/repository_knowledge.py"],
            details={
                "excluded_roots": state.get("excluded_roots", []),
                "excluded_existing_roots": state.get("excluded_existing_roots", []),
                "excluded_path_hit_count": summary.get("excluded_path_hit_count", 0),
            },
        ),
        _check_result(
            "repository_knowledge_source_of_truth_boundary",
            "Repository knowledge source-of-truth boundary",
            summary.get("generated_wiki_source_of_truth") is False
            and summary.get("official_docs_source_of_truth") is True
            and all(
                row.get("source_of_truth") is True
                for row in state.get("knowledge_maps", [])
                if row.get("id") == "official_docs"
            ),
            "generated knowledge remains an exploration aid and official docs remain authoritative",
            evidence=["docs/source", "docs/source/roadmap/agilab-future-work.md"],
            details={
                "knowledge_maps": state.get("knowledge_maps", []),
                "summary": summary,
            },
        ),
        _check_result(
            "repository_knowledge_query_seeds",
            "Repository knowledge query seeds",
            int(summary.get("query_seed_count", 0) or 0) >= 4
            and {row.get("id") for row in state.get("query_seeds", [])}
            >= {"evidence_flow", "connector_flow", "dag_flow", "docs_source"},
            "index emits stable onboarding questions and entry points",
            evidence=["src/agilab/repository_knowledge.py"],
            details={"query_seeds": state.get("query_seeds", [])},
        ),
        _check_result(
            "repository_knowledge_no_network",
            "Repository knowledge no-network boundary",
            summary.get("command_execution_count") == 0
            and summary.get("network_probe_count") == 0
            and state.get("provenance", {}).get("executes_commands") is False
            and state.get("provenance", {}).get("queries_network") is False,
            "repository knowledge report reads local files without commands or network probes",
            evidence=["src/agilab/repository_knowledge.py"],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "repository_knowledge_persistence",
            "Repository knowledge persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "repository knowledge index is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Repository knowledge index report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Builds a static repository knowledge index and stats report for code, tests, docs, "
            "runbooks, and package manifests while excluding generated outputs."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "indexed_file_count": summary.get("indexed_file_count"),
            "source_file_count": summary.get("source_file_count"),
            "code_file_count": summary.get("code_file_count"),
            "python_file_count": summary.get("python_file_count"),
            "tool_file_count": summary.get("tool_file_count"),
            "test_file_count": summary.get("test_file_count"),
            "docs_file_count": summary.get("docs_file_count"),
            "pyproject_count": summary.get("pyproject_count"),
            "runbook_count": summary.get("runbook_count"),
            "total_line_count": summary.get("total_line_count"),
            "source_line_count": summary.get("source_line_count"),
            "code_line_count": summary.get("code_line_count"),
            "python_line_count": summary.get("python_line_count"),
            "tool_line_count": summary.get("tool_line_count"),
            "test_line_count": summary.get("test_line_count"),
            "docs_line_count": summary.get("docs_line_count"),
            "pyproject_line_count": summary.get("pyproject_line_count"),
            "runbook_line_count": summary.get("runbook_line_count"),
            "total_size_bytes": summary.get("total_size_bytes"),
            "kind_counts": summary.get("kind_counts"),
            "kind_line_counts": summary.get("kind_line_counts"),
            "suffix_counts": summary.get("suffix_counts"),
            "suffix_line_counts": summary.get("suffix_line_counts"),
            "average_lines_per_indexed_file": summary.get(
                "average_lines_per_indexed_file"
            ),
            "test_to_code_line_ratio": summary.get("test_to_code_line_ratio"),
            "docs_to_code_line_ratio": summary.get("docs_to_code_line_ratio"),
            "manifest_to_code_line_ratio": summary.get("manifest_to_code_line_ratio"),
            "top_kinds_by_lines": summary.get("top_kinds_by_lines"),
            "top_suffixes_by_lines": summary.get("top_suffixes_by_lines"),
            "largest_files_by_lines": summary.get("largest_files_by_lines"),
            "knowledge_map_count": summary.get("knowledge_map_count"),
            "query_seed_count": summary.get("query_seed_count"),
            "excluded_root_count": summary.get("excluded_root_count"),
            "excluded_existing_count": summary.get("excluded_existing_count"),
            "excluded_path_hit_count": summary.get("excluded_path_hit_count"),
            "generated_wiki_source_of_truth": summary.get(
                "generated_wiki_source_of_truth"
            ),
            "official_docs_source_of_truth": summary.get(
                "official_docs_source_of_truth"
            ),
            "private_repository_indexed": summary.get("private_repository_indexed"),
            "network_probe_count": summary.get("network_probe_count"),
            "command_execution_count": summary.get("command_execution_count"),
            "round_trip_ok": proof["round_trip_ok"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB repository knowledge-index evidence."
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=None,
        help="Optional path for the local per-file record cache.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the local per-file record cache.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Explicit public source root; indexes never select another repository.",
    )
    indexes = parser.add_mutually_exclusive_group()
    indexes.add_argument(
        "--build-index",
        type=Path,
        metavar="JSON",
        help="Explicitly build or rebuild the existing static index.",
    )
    indexes.add_argument(
        "--index",
        type=Path,
        metavar="JSON",
        help="Load and verify an index against the selected current source.",
    )
    parser.add_argument(
        "--query", default=None, help="Case-sensitive literal source-line search."
    )
    parser.add_argument(
        "--search-mode", choices=("literal", "tokens"), default="literal"
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Maximum results: 1 to 50."
    )
    parser.add_argument(
        "--context-lines", type=int, default=2, help="Context lines: 0 to 5."
    )
    parser.add_argument(
        "--context-bytes",
        type=int,
        default=1024,
        help="Context UTF-8 bytes: 512 to 2048.",
    )
    parser.add_argument(
        "--output-bytes",
        type=int,
        default=32768,
        help="Search output UTF-8 bytes: 2048 to 65536.",
    )
    return parser


def _explore(args: argparse.Namespace) -> dict[str, Any]:
    if args.query is not None:
        _query_utf8_bytes(args.query)
    root = (args.repo_root or REPO_ROOT).resolve()
    if args.output is not None:
        raise RepositoryKnowledgeError(
            "Use --build-index JSON for index output; --output belongs to the report."
        )
    if args.build_index is not None:
        cache = (
            None
            if args.no_cache
            else args.cache_path or default_record_cache_path(root)
        )
        proof = persist_repository_knowledge_index(
            repo_root=root,
            output_path=args.build_index,
            record_cache_path=cache,
        )
        state = proof["state"]
    elif args.index is not None:
        state = load_repository_knowledge_index(args.index, repo_root=root)
    else:
        raise RepositoryKnowledgeError(
            "Search requires --index JSON or an explicit --build-index JSON."
        )
    if not isinstance(state, dict) or state.get("run_status") != "indexed":
        raise RepositoryKnowledgeError(
            "Repository index run_status is missing or invalid; rebuild explicitly with --build-index."
        )
    if args.query is not None:
        return search_repository_knowledge_index(
            state,
            repo_root=root,
            query=args.query,
            mode=args.search_mode,
            limit=args.limit,
            context_lines=args.context_lines,
            context_bytes=args.context_bytes,
            output_bytes=args.output_bytes,
        )
    return {
        "status": "pass",
        "schema": state["schema"],
        "source_fingerprint": state["source_fingerprint"],
        "indexed_file_count": len(state["records"]),
        "run_status": state["run_status"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    explorer = (
        args.build_index is not None or args.index is not None or args.query is not None
    )
    try:
        if explorer:
            report = _explore(args)
        else:
            options = {
                "output_path": args.output,
                "record_cache_path": args.cache_path,
                "use_record_cache": not args.no_cache,
            }
            if args.repo_root is not None:
                options["repo_root"] = args.repo_root
            report = build_report(**options)
    except (RepositoryKnowledgeError, OSError) as exc:
        report = {"status": "fail", "error": str(exc)[:512]}
        print(json.dumps(report, sort_keys=True, ensure_ascii=False))
        return 2
    if args.compact:
        print(
            json.dumps(
                report, sort_keys=True, separators=(",", ":"), ensure_ascii=not explorer
            )
        )
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=not explorer))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
