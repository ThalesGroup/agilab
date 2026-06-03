#!/usr/bin/env python3
"""Emit AGILAB CI artifact harvest evidence."""

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

from agilab.ci_artifact_harvest import (  # noqa: E402
    REQUIRED_ARTIFACT_KINDS,
    SCHEMA,
    DEFAULT_RELEASE_ID,
    persist_ci_artifact_harvest,
)


EXPECTED_ARTIFACT_KINDS = sorted(REQUIRED_ARTIFACT_KINDS)


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


def _read_artifact_index(path: Path | None) -> tuple[list[dict[str, Any]] | None, str]:
    if path is None:
        return None, DEFAULT_RELEASE_ID
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)], DEFAULT_RELEASE_ID
    if isinstance(payload, dict):
        artifacts = payload.get("artifacts", [])
        if not isinstance(artifacts, list):
            raise ValueError("artifact index must contain an artifacts list")
        release_id = str(payload.get("release_id", DEFAULT_RELEASE_ID) or DEFAULT_RELEASE_ID)
        return [row for row in artifacts if isinstance(row, dict)], release_id
    raise ValueError("artifact index must be a JSON list or object")


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "CI artifact harvest report",
        "tools/ci_artifact_harvest_report.py --compact",
        "ci_artifact_contract_only",
        "external-machine",
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
        "ci_artifact_harvest_docs_reference",
        "CI artifact harvest docs reference",
        ok,
        (
            "features docs expose the CI artifact harvest command"
            if ok
            else "features docs do not expose the CI artifact harvest command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    output_path: Path | None = None,
    artifact_index_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    artifacts, release_id = _read_artifact_index(artifact_index_path)
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-ci-artifact-harvest-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                output_path=Path(tmp_dir) / "ci_artifact_harvest.json",
                artifacts=artifacts,
                release_id=release_id,
                artifact_index_path=artifact_index_path,
            )
    return _build_report_with_path(
        repo_root=repo_root,
        output_path=output_path,
        artifacts=artifacts,
        release_id=release_id,
        artifact_index_path=artifact_index_path,
    )


def _build_report_with_path(
    *,
    repo_root: Path,
    output_path: Path,
    artifacts: list[dict[str, Any]] | None,
    release_id: str,
    artifact_index_path: Path | None,
) -> dict[str, Any]:
    proof = persist_ci_artifact_harvest(
        output_path=output_path,
        artifacts=artifacts,
        release_id=release_id,
    )
    state = proof["state"]
    summary = state.get("summary", {})
    release = state.get("release", {})
    provenance = state.get("provenance", {})
    artifact_kinds = summary.get("artifact_kinds", [])
    artifact_statuses = release.get("artifact_statuses", {})

    checks = [
        _check_result(
            "ci_artifact_harvest_schema",
            "CI artifact harvest schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "harvest_ready"
            and state.get("execution_mode") == "ci_artifact_contract_only",
            "CI artifact harvest uses the supported contract-only schema",
            evidence=["src/agilab/ci_artifact_harvest.py"],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "ci_artifact_harvest_required_artifacts",
            "CI artifact harvest required artifacts",
            summary.get("artifact_count") == 4
            and summary.get("required_artifact_count") == 4
            and summary.get("loaded_artifact_count") == 4
            and summary.get("missing_required_count") == 0
            and artifact_kinds == EXPECTED_ARTIFACT_KINDS,
            "harvest includes the required manifest, KPI, compatibility, and decision artifacts",
            evidence=[
                "tools/newcomer_first_proof.py",
                "tools/kpi_evidence_bundle.py",
                "tools/compatibility_report.py",
            ],
            details={
                "artifact_kinds": artifact_kinds,
                "required_artifact_kinds": list(REQUIRED_ARTIFACT_KINDS),
                "artifact_index_path": str(artifact_index_path or ""),
            },
        ),
        _check_result(
            "ci_artifact_harvest_checksums",
            "CI artifact harvest checksums",
            summary.get("checksum_verified_count") == 4
            and summary.get("checksum_mismatch_count") == 0
            and all(
                artifact.get("sha256_verified") is True
                for artifact in state.get("artifacts", [])
            ),
            "all harvested artifact payload checksums are verified",
            evidence=["src/agilab/ci_artifact_harvest.py"],
            details={"artifacts": state.get("artifacts", [])},
        ),
        _check_result(
            "ci_artifact_harvest_release_status",
            "CI artifact harvest release status mapping",
            summary.get("release_status") == "validated"
            and release.get("public_status") == "validated"
            and artifact_statuses
            == {kind: "validated" for kind in REQUIRED_ARTIFACT_KINDS},
            "required external-machine artifacts map to a validated release status",
            evidence=["docs/source/data/compatibility_matrix.toml"],
            details=release,
        ),
        _check_result(
            "ci_artifact_harvest_external_machine_provenance",
            "CI artifact harvest external-machine provenance",
            summary.get("provenance_tagged_count") == 4
            and summary.get("external_machine_evidence_count") == 4
            and all(
                artifact.get("attachment_status") == "provenance_tagged"
                for artifact in state.get("artifacts", [])
            ),
            "harvested artifacts preserve source-machine workflow provenance",
            evidence=["src/agilab/ci_artifact_harvest.py"],
            details={
                "source_machines": release.get("source_machines", []),
                "artifacts": state.get("artifacts", []),
            },
        ),
        _check_result(
            "ci_artifact_harvest_no_live_ci",
            "CI artifact harvest no-live-CI boundary",
            summary.get("live_ci_query_count") == 0
            and summary.get("network_probe_count") == 0
            and summary.get("command_execution_count") == 0
            and provenance.get("queries_ci_provider") is False
            and provenance.get("executes_network_probe") is False
            and provenance.get("executes_commands") is False
            and provenance.get("safe_for_public_evidence") is True,
            "public harvest evidence does not query CI providers or networks",
            evidence=["src/agilab/ci_artifact_harvest.py"],
            details={"summary": summary, "provenance": provenance},
        ),
        _check_result(
            "ci_artifact_harvest_persistence",
            "CI artifact harvest persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "CI artifact harvest evidence is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "CI artifact harvest report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Validates a static external-machine artifact index for run "
            "manifest, KPI, compatibility, and promotion-decision evidence "
            "without querying a live CI provider."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "release_id": release.get("release_id"),
            "release_status": summary.get("release_status"),
            "artifact_count": summary.get("artifact_count"),
            "required_artifact_count": summary.get("required_artifact_count"),
            "loaded_artifact_count": summary.get("loaded_artifact_count"),
            "missing_required_count": summary.get("missing_required_count"),
            "checksum_verified_count": summary.get("checksum_verified_count"),
            "checksum_mismatch_count": summary.get("checksum_mismatch_count"),
            "provenance_tagged_count": summary.get("provenance_tagged_count"),
            "external_machine_evidence_count": summary.get(
                "external_machine_evidence_count"
            ),
            "live_ci_query_count": summary.get("live_ci_query_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "command_execution_count": summary.get("command_execution_count"),
            "artifact_kinds": artifact_kinds,
            "round_trip_ok": proof["round_trip_ok"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB CI artifact harvest evidence."
    )
    parser.add_argument("--artifact-index", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        output_path=args.output,
        artifact_index_path=args.artifact_index,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
