#!/usr/bin/env python3
"""Emit AGILAB bounded public certification-profile evidence."""

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

from agilab.public_certification import (  # noqa: E402
    SCHEMA,
    persist_public_certification_profile,
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
        "public certification profile report",
        "tools/public_certification_profile_report.py --compact",
        "agilab.public_certification_profile.v1",
        "bounded_public_evidence",
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
        "public_certification_profile_docs_reference",
        "Public certification profile docs reference",
        ok,
        (
            "features docs expose the public certification profile command"
            if ok
            else "features docs do not expose the public certification profile command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    matrix_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-public-certification-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                matrix_path=matrix_path,
                output_path=Path(tmp_dir) / "public_certification_profile.json",
            )
    return _build_report_with_path(
        repo_root=repo_root,
        matrix_path=matrix_path,
        output_path=output_path,
    )


def _build_report_with_path(
    *,
    repo_root: Path,
    matrix_path: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    proof = persist_public_certification_profile(
        repo_root=repo_root,
        matrix_path=matrix_path,
        output_path=output_path,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    checks = [
        _check_result(
            "public_certification_profile_schema",
            "Public certification profile schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("execution_mode") == "public_certification_static",
            "public certification profile uses the supported schema",
            evidence=["src/agilab/public_certification.py"],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "public_certification_profile_scope",
            "Public certification profile scope",
            summary.get("certification_profile") == "bounded_public_evidence"
            and summary.get("path_count") == 6
            and summary.get("certified_public_evidence_count") == 4
            and summary.get("documented_not_certified_count") == 2,
            "certification profile covers all public compatibility paths",
            evidence=["docs/source/data/compatibility_matrix.toml"],
            details={"summary": summary},
        ),
        _check_result(
            "public_certification_profile_broader_slices",
            "Public certification profile broader slices",
            summary.get("certified_beyond_newcomer_operator_count") == 2
            and summary.get("certified_beyond_newcomer_operator_paths")
            == ["web-ui-local-first-proof", "agilab-hf-demo"],
            "validated certification rows include public slices beyond newcomer/operator",
            evidence=["docs/source/data/compatibility_matrix.toml"],
            details={
                "certified_beyond_newcomer_operator_paths": summary.get(
                    "certified_beyond_newcomer_operator_paths",
                    [],
                )
            },
        ),
        _check_result(
            "public_certification_profile_boundaries",
            "Public certification profile boundaries",
            summary.get("production_certification_claimed") is False
            and summary.get("formal_third_party_certification") is False,
            "profile explicitly avoids production or third-party certification claims",
            evidence=["docs/source/data/compatibility_matrix.toml"],
            details={"summary": summary},
        ),
        _check_result(
            "public_certification_profile_no_execution",
            "Public certification profile no execution",
            summary.get("command_execution_count") == 0
            and summary.get("network_probe_count") == 0,
            "public certification profile reads static matrix data only",
            evidence=["src/agilab/public_certification.py"],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "public_certification_profile_persistence",
            "Public certification profile persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "public certification profile is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Public certification profile report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Turns compatibility matrix rows into a bounded public certification "
            "profile without claiming production or third-party certification."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "certification_profile": summary.get("certification_profile"),
            "path_count": summary.get("path_count"),
            "certified_public_evidence_count": summary.get(
                "certified_public_evidence_count"
            ),
            "documented_not_certified_count": summary.get("documented_not_certified_count"),
            "certified_beyond_newcomer_operator_count": summary.get(
                "certified_beyond_newcomer_operator_count"
            ),
            "production_certification_claimed": summary.get(
                "production_certification_claimed"
            ),
            "formal_third_party_certification": summary.get(
                "formal_third_party_certification"
            ),
            "command_execution_count": summary.get("command_execution_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "round_trip_ok": proof["round_trip_ok"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB bounded public certification-profile evidence."
    )
    parser.add_argument("--matrix", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(matrix_path=args.matrix, output_path=args.output)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
