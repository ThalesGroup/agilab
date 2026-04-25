#!/usr/bin/env python3
"""Emit AGILAB revision traceability evidence."""

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

from agilab.revision_traceability import (  # noqa: E402
    SCHEMA,
    persist_revision_traceability,
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
        "revision traceability report",
        "tools/revision_traceability_report.py --compact",
        "agilab.revision_traceability.v1",
        "revision_traceability_static",
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
        "revision_traceability_docs_reference",
        "Revision traceability docs reference",
        ok,
        (
            "features docs expose the revision traceability command"
            if ok
            else "features docs do not expose the revision traceability command"
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
        with tempfile.TemporaryDirectory(prefix="agilab-revision-traceability-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                output_path=Path(tmp_dir) / "revision_traceability.json",
            )
    return _build_report_with_path(repo_root=repo_root, output_path=output_path)


def _build_report_with_path(*, repo_root: Path, output_path: Path) -> dict[str, Any]:
    proof = persist_revision_traceability(repo_root=repo_root, output_path=output_path)
    state = proof["state"]
    summary = state.get("summary", {})
    repository = state.get("repository", {})
    core_components = state.get("core_components", [])
    builtin_apps = state.get("builtin_apps", [])
    checks = [
        _check_result(
            "revision_traceability_schema",
            "Revision traceability schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("execution_mode") == "revision_traceability_static",
            "revision traceability uses the supported schema",
            evidence=["src/agilab/revision_traceability.py"],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "revision_traceability_repository_head",
            "Revision traceability repository head",
            repository.get("status") in {"available", "unresolved_ref"}
            and state.get("provenance", {}).get("uses_git_cli") is False,
            "repository HEAD is captured without invoking git",
            evidence=[".git/HEAD"],
            details={"repository": repository},
        ),
        _check_result(
            "revision_traceability_core_components",
            "Revision traceability core components",
            summary.get("core_component_count") == 5
            and summary.get("missing_core_component_count") == 0
            and all(row.get("sha256") for row in core_components),
            "root AGILAB and bundled AGI core package revisions are fingerprinted",
            evidence=[row.get("path", "") for row in core_components],
            details={"core_components": core_components},
        ),
        _check_result(
            "revision_traceability_builtin_apps",
            "Revision traceability built-in apps",
            summary.get("builtin_app_count") == 7
            and summary.get("app_fingerprint_count") == 7
            and summary.get("missing_app_pyproject_count") == 0
            and summary.get("missing_app_settings_count") == 0,
            "all built-in app manifests and settings are fingerprinted",
            evidence=["src/agilab/apps/builtin"],
            details={
                "builtin_apps": summary.get("builtin_apps", []),
                "app_fingerprints": [
                    {
                        "app": row.get("app", ""),
                        "fingerprint_sha256": row.get("fingerprint_sha256", ""),
                    }
                    for row in builtin_apps
                ],
            },
        ),
        _check_result(
            "revision_traceability_no_execution",
            "Revision traceability no execution",
            summary.get("command_execution_count") == 0
            and summary.get("network_probe_count") == 0
            and state.get("provenance", {}).get("uses_git_cli") is False,
            "revision traceability reads local metadata without commands or network probes",
            evidence=["src/agilab/revision_traceability.py"],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "revision_traceability_persistence",
            "Revision traceability persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "revision traceability state is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Revision traceability report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Fingerprints the repository HEAD, bundled AGI core packages, and "
            "built-in app manifests without executing commands or querying networks."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "repository_commit": summary.get("repository_commit"),
            "core_component_count": summary.get("core_component_count"),
            "builtin_app_count": summary.get("builtin_app_count"),
            "app_fingerprint_count": summary.get("app_fingerprint_count"),
            "pipeline_view_app_count": summary.get("pipeline_view_app_count"),
            "command_execution_count": summary.get("command_execution_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "round_trip_ok": proof["round_trip_ok"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB revision traceability evidence."
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
