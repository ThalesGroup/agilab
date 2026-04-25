#!/usr/bin/env python3
"""Emit AGILAB run-diff and counterfactual evidence."""

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

from agilab.run_diff_evidence import (  # noqa: E402
    SCHEMA,
    persist_run_diff_evidence,
)


EXPECTED_ADDED_CHECK_IDS = ["data_connector_runtime_adapters_report_contract"]
EXPECTED_ADDED_ARTIFACT_IDS = ["forecast_metrics", "runtime_adapter_bindings"]
EXPECTED_COUNTERFACTUAL_IDS = [
    "single_sample_multi_app_dag",
    "without_runtime_adapter_contract",
]


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


def _read_json(path: Path | None) -> Any:
    if path is None:
        return None
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "run-diff evidence report",
        "tools/run_diff_evidence_report.py --compact",
        "run_diff_evidence_only",
        "counterfactual",
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
        "run_diff_evidence_docs_reference",
        "Run-diff evidence docs reference",
        ok,
        (
            "features docs expose the run-diff evidence command"
            if ok
            else "features docs do not expose the run-diff evidence command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    output_path: Path | None = None,
    baseline_bundle_path: Path | None = None,
    candidate_bundle_path: Path | None = None,
    baseline_manifest_path: Path | None = None,
    candidate_manifest_path: Path | None = None,
    baseline_artifacts_path: Path | None = None,
    candidate_artifacts_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-run-diff-evidence-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                output_path=Path(tmp_dir) / "run_diff_evidence.json",
                baseline_bundle_path=baseline_bundle_path,
                candidate_bundle_path=candidate_bundle_path,
                baseline_manifest_path=baseline_manifest_path,
                candidate_manifest_path=candidate_manifest_path,
                baseline_artifacts_path=baseline_artifacts_path,
                candidate_artifacts_path=candidate_artifacts_path,
            )
    return _build_report_with_path(
        repo_root=repo_root,
        output_path=output_path,
        baseline_bundle_path=baseline_bundle_path,
        candidate_bundle_path=candidate_bundle_path,
        baseline_manifest_path=baseline_manifest_path,
        candidate_manifest_path=candidate_manifest_path,
        baseline_artifacts_path=baseline_artifacts_path,
        candidate_artifacts_path=candidate_artifacts_path,
    )


def _build_report_with_path(
    *,
    repo_root: Path,
    output_path: Path,
    baseline_bundle_path: Path | None,
    candidate_bundle_path: Path | None,
    baseline_manifest_path: Path | None,
    candidate_manifest_path: Path | None,
    baseline_artifacts_path: Path | None,
    candidate_artifacts_path: Path | None,
) -> dict[str, Any]:
    proof = persist_run_diff_evidence(
        output_path=output_path,
        baseline_bundle=_read_json(baseline_bundle_path),
        candidate_bundle=_read_json(candidate_bundle_path),
        baseline_manifest=_read_json(baseline_manifest_path),
        candidate_manifest=_read_json(candidate_manifest_path),
        baseline_artifacts=_read_json(baseline_artifacts_path),
        candidate_artifacts=_read_json(candidate_artifacts_path),
    )
    state = proof["state"]
    summary = state.get("summary", {})
    diff = state.get("diff", {})
    manifest = state.get("manifest", {})
    provenance = state.get("provenance", {})
    added_check_ids = sorted(
        str(check.get("id", "")) for check in diff.get("checks_added", [])
    )
    added_artifact_ids = sorted(
        str(artifact.get("id", artifact.get("artifact_id", "")))
        for artifact in diff.get("artifacts_added", [])
    )
    counterfactual_ids = sorted(
        str(row.get("id", "")) for row in state.get("counterfactuals", [])
    )

    checks = [
        _check_result(
            "run_diff_evidence_schema",
            "Run-diff evidence schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("run_status") == "diff_ready"
            and state.get("execution_mode") == "run_diff_evidence_only",
            "run-diff evidence uses the supported evidence-only schema",
            evidence=["src/agilab/run_diff_evidence.py"],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
            },
        ),
        _check_result(
            "run_diff_evidence_check_delta",
            "Run-diff evidence check delta",
            summary.get("check_added_count") == 1
            and added_check_ids == EXPECTED_ADDED_CHECK_IDS
            and summary.get("check_removed_count") == 0
            and summary.get("check_status_changed_count") == 0
            and summary.get("check_summary_changed_count") == 1,
            "candidate adds the runtime-adapter contract without status regressions",
            evidence=["tools/kpi_evidence_bundle.py"],
            details={
                "added_check_ids": added_check_ids,
                "checks_removed": diff.get("checks_removed", []),
                "check_status_changes": diff.get("check_status_changes", []),
                "check_summary_changes": diff.get("check_summary_changes", []),
            },
        ),
        _check_result(
            "run_diff_evidence_artifact_delta",
            "Run-diff evidence artifact delta",
            summary.get("artifact_added_count") == 2
            and added_artifact_ids == EXPECTED_ADDED_ARTIFACT_IDS
            and summary.get("artifact_removed_count") == 0,
            "candidate adds forecast and runtime-adapter evidence artifacts",
            evidence=["src/agilab/run_diff_evidence.py"],
            details={
                "added_artifact_ids": added_artifact_ids,
                "artifacts_removed": diff.get("artifacts_removed", []),
            },
        ),
        _check_result(
            "run_diff_evidence_manifest_delta",
            "Run-diff evidence manifest delta",
            manifest.get("same_path_id") is True
            and manifest.get("status_changed") is False
            and summary.get("manifest_artifact_delta") == 1
            and summary.get("manifest_validation_added_count") == 1,
            "candidate manifest keeps the same path status and adds evidence",
            evidence=["src/agilab/run_manifest.py"],
            details=manifest,
        ),
        _check_result(
            "run_diff_evidence_counterfactuals",
            "Run-diff evidence counterfactuals",
            summary.get("counterfactual_count") == 2
            and counterfactual_ids == EXPECTED_COUNTERFACTUAL_IDS,
            "report emits counterfactual prompts for material run deltas",
            evidence=["src/agilab/run_diff_evidence.py"],
            details={
                "counterfactual_ids": counterfactual_ids,
                "counterfactuals": state.get("counterfactuals", []),
            },
        ),
        _check_result(
            "run_diff_evidence_no_execution",
            "Run-diff evidence no-execution boundary",
            summary.get("network_probe_count") == 0
            and summary.get("live_execution_count") == 0
            and summary.get("command_execution_count") == 0
            and provenance.get("executes_commands") is False
            and provenance.get("executes_network_probe") is False
            and provenance.get("safe_for_public_evidence") is True,
            "public run-diff evidence does not execute commands or networks",
            evidence=["src/agilab/run_diff_evidence.py"],
            details={"summary": summary, "provenance": provenance},
        ),
        _check_result(
            "run_diff_evidence_persistence",
            "Run-diff evidence persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "run-diff evidence is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Run-diff evidence report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Compares static baseline and candidate evidence bundles, run "
            "manifests, and artifact rows, then emits counterfactual prompts "
            "without executing live work."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "check_added_count": summary.get("check_added_count"),
            "check_removed_count": summary.get("check_removed_count"),
            "check_status_changed_count": summary.get("check_status_changed_count"),
            "check_summary_changed_count": summary.get(
                "check_summary_changed_count"
            ),
            "artifact_added_count": summary.get("artifact_added_count"),
            "artifact_removed_count": summary.get("artifact_removed_count"),
            "manifest_artifact_delta": summary.get("manifest_artifact_delta"),
            "counterfactual_count": summary.get("counterfactual_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "live_execution_count": summary.get("live_execution_count"),
            "command_execution_count": summary.get("command_execution_count"),
            "round_trip_ok": proof["round_trip_ok"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB run-diff and counterfactual evidence."
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--baseline-bundle", type=Path, default=None)
    parser.add_argument("--candidate-bundle", type=Path, default=None)
    parser.add_argument("--baseline-manifest", type=Path, default=None)
    parser.add_argument("--candidate-manifest", type=Path, default=None)
    parser.add_argument("--baseline-artifacts", type=Path, default=None)
    parser.add_argument("--candidate-artifacts", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        output_path=args.output,
        baseline_bundle_path=args.baseline_bundle,
        candidate_bundle_path=args.candidate_bundle,
        baseline_manifest_path=args.baseline_manifest,
        candidate_manifest_path=args.candidate_manifest,
        baseline_artifacts_path=args.baseline_artifacts,
        candidate_artifacts_path=args.candidate_artifacts,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
