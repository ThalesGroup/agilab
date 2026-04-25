#!/usr/bin/env python3
"""Emit AGILAB repository knowledge-index evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence


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
        "generated wiki as an exploration aid",
    ]
    doc_path = repo_root / DOC_RELATIVE_PATH
    try:
        text = doc_path.read_text(encoding="utf-8")
        missing = [needle for needle in required if needle not in text]
        ok = not missing
        details = {"missing": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
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


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-repository-knowledge-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                output_path=Path(tmp_dir) / "repository_knowledge_index.json",
            )
    return _build_report_with_path(repo_root=repo_root, output_path=output_path)


def _build_report_with_path(*, repo_root: Path, output_path: Path) -> dict[str, Any]:
    proof = persist_repository_knowledge_index(
        repo_root=repo_root,
        output_path=output_path,
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
            and int(summary.get("docs_file_count", 0) or 0) > 10
            and int(summary.get("runbook_count", 0) or 0) >= 3,
            "index covers source files, tools, official docs, and root runbooks",
            evidence=["src/agilab", "tools", "docs/source", "README.md", "AGENTS.md"],
            details={"summary": summary},
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
            "Builds a static repository knowledge index for code, docs, "
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
            "python_file_count": summary.get("python_file_count"),
            "tool_file_count": summary.get("tool_file_count"),
            "docs_file_count": summary.get("docs_file_count"),
            "pyproject_count": summary.get("pyproject_count"),
            "runbook_count": summary.get("runbook_count"),
            "knowledge_map_count": summary.get("knowledge_map_count"),
            "query_seed_count": summary.get("query_seed_count"),
            "excluded_root_count": summary.get("excluded_root_count"),
            "excluded_existing_count": summary.get("excluded_existing_count"),
            "excluded_path_hit_count": summary.get("excluded_path_hit_count"),
            "generated_wiki_source_of_truth": summary.get(
                "generated_wiki_source_of_truth"
            ),
            "official_docs_source_of_truth": summary.get("official_docs_source_of_truth"),
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(output_path=args.output)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
