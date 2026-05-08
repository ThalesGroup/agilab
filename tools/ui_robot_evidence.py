#!/usr/bin/env python3
"""Refresh and validate release evidence from the UI robot matrix workflow."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "source" / "data" / "ui_robot_evidence.json"
SCHEMA = "agilab.ui_robot_evidence.v1"
WORKFLOW_NAME = "ui-robot-matrix"
DEFAULT_BRANCH = "main"
DEFAULT_REPO = "ThalesGroup/agilab"
DEFAULT_RUN_LIMIT = 20
GITHUB_RUN_FIELDS = (
    "attempt",
    "conclusion",
    "createdAt",
    "databaseId",
    "event",
    "headBranch",
    "headSha",
    "name",
    "status",
    "updatedAt",
    "url",
    "workflowName",
)
REQUIRED_ARTIFACT_FILES = {
    "matrix_summary": "summary.json",
    "scenario_summary": "isolated-core-pages.json",
    "progress_log": "isolated-core-pages.ndjson",
    "exit_code": "exit-code.txt",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_gh_json(args: Sequence[str], *, repo_root: Path = REPO_ROOT) -> Any:
    completed = subprocess.run(
        ["gh", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"gh {' '.join(args)} failed: {detail}")
    try:
        return json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh {' '.join(args)} returned invalid JSON: {exc}") from exc


def _run_command(args: Sequence[str], *, repo_root: Path = REPO_ROOT) -> None:
    completed = subprocess.run(
        list(args),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"{' '.join(args)} failed: {detail}")


def _github_fields() -> str:
    return ",".join(GITHUB_RUN_FIELDS)


def normalize_run(row: Mapping[str, Any]) -> dict[str, str]:
    return {field: str(row.get(field, "") or "") for field in GITHUB_RUN_FIELDS}


def is_successful_ui_robot_run(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("workflowName", "")) == WORKFLOW_NAME
        and str(row.get("status", "")) == "completed"
        and str(row.get("conclusion", "")) == "success"
        and bool(str(row.get("databaseId", "") or ""))
        and bool(row.get("url"))
    )


def select_latest_successful_run(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    for row in rows:
        if is_successful_ui_robot_run(row):
            return normalize_run(row)
    raise RuntimeError(f"no successful {WORKFLOW_NAME!r} workflow run found")


def fetch_latest_successful_run(
    *,
    repo: str,
    branch: str | None,
    limit: int,
    repo_root: Path = REPO_ROOT,
) -> dict[str, str]:
    args = [
        "run",
        "list",
        "--repo",
        repo,
        "--workflow",
        f"{WORKFLOW_NAME}.yml",
        "--limit",
        str(limit),
        "--json",
        _github_fields(),
    ]
    if branch:
        args.extend(["--branch", branch])
    rows = _run_gh_json(args, repo_root=repo_root)
    if not isinstance(rows, list):
        raise RuntimeError("gh run list did not return a JSON list")
    return select_latest_successful_run([row for row in rows if isinstance(row, Mapping)])


def fetch_run(run_id: str, *, repo: str, repo_root: Path = REPO_ROOT) -> dict[str, str]:
    raw = _run_gh_json(
        [
            "run",
            "view",
            run_id,
            "--repo",
            repo,
            "--json",
            _github_fields(),
        ],
        repo_root=repo_root,
    )
    if not isinstance(raw, Mapping):
        raise RuntimeError("gh run view did not return a JSON object")
    return normalize_run(raw)


def fetch_artifact_metadata(run_id: str, *, repo: str, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    raw = _run_gh_json(
        [
            "api",
            f"repos/{repo}/actions/runs/{run_id}/artifacts",
        ],
        repo_root=repo_root,
    )
    artifacts = raw.get("artifacts") if isinstance(raw, Mapping) else None
    if not isinstance(artifacts, list):
        raise RuntimeError("GitHub artifacts response did not contain an artifacts list")
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            continue
        if str(artifact.get("name", "") or "").startswith(WORKFLOW_NAME):
            return {
                "name": str(artifact.get("name", "") or ""),
                "expired": bool(artifact.get("expired")),
                "size_bytes": int(artifact.get("size_in_bytes") or 0),
                "archive_download_url": str(artifact.get("archive_download_url", "") or ""),
            }
    raise RuntimeError(f"no {WORKFLOW_NAME!r} artifact found for run {run_id}")


def download_artifact(
    run_id: str,
    *,
    repo: str,
    artifact_name: str,
    destination: Path,
    repo_root: Path = REPO_ROOT,
) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    _run_command(
        [
            "gh",
            "run",
            "download",
            run_id,
            "--repo",
            repo,
            "--name",
            artifact_name,
            "--dir",
            str(destination),
        ],
        repo_root=repo_root,
    )
    return destination


def _find_artifact_file(root: Path, filename: str) -> Path | None:
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    return matches[0] if matches else None


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def load_artifact_payloads(artifact_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = {
        key: _find_artifact_file(artifact_dir, filename)
        for key, filename in REQUIRED_ARTIFACT_FILES.items()
    }
    missing = [key for key, path in paths.items() if path is None]
    if missing:
        raise FileNotFoundError(
            f"missing required UI robot artifact file(s): {', '.join(missing)}"
        )

    matrix_summary = _load_json(paths["matrix_summary"])  # type: ignore[arg-type]
    scenario_summary = _load_json(paths["scenario_summary"])  # type: ignore[arg-type]
    exit_code_text = paths["exit_code"].read_text(encoding="utf-8").strip()  # type: ignore[union-attr]
    progress_path = paths["progress_log"]  # type: ignore[assignment]
    screenshot_count = sum(1 for path in artifact_dir.rglob("*.png") if path.is_file())

    def _relative(path: Path | None) -> str:
        if path is None:
            return ""
        try:
            return str(path.relative_to(artifact_dir))
        except ValueError:
            return path.name

    artifact_checks = {
        "required_files_present": True,
        "exit_code": exit_code_text,
        "progress_log_bytes": progress_path.stat().st_size,
        "screenshot_count": screenshot_count,
        "matrix_summary_file": _relative(paths["matrix_summary"]),
        "scenario_summary_file": _relative(paths["scenario_summary"]),
        "progress_log_file": _relative(progress_path),
    }
    return matrix_summary, scenario_summary, artifact_checks


def _int_value(payload: Mapping[str, Any], key: str) -> int:
    return int(payload.get(key) or 0)


def _float_value(payload: Mapping[str, Any], key: str) -> float:
    return float(payload.get(key) or 0.0)


def build_evidence(
    *,
    run: Mapping[str, Any],
    artifact: Mapping[str, Any],
    matrix_summary: Mapping[str, Any],
    scenario_summary: Mapping[str, Any],
    artifact_checks: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    failed_count = _int_value(scenario_summary, "failed_count")
    skipped_count = _int_value(scenario_summary, "skipped_count")
    success = (
        is_successful_ui_robot_run(run)
        and matrix_summary.get("success") is True
        and scenario_summary.get("success") is True
        and failed_count == 0
        and str(artifact_checks.get("exit_code", "")) == "0"
        and not bool(artifact.get("expired"))
    )
    return {
        "schema": SCHEMA,
        "generated_at": generated_at or utc_now_iso(),
        "source": {
            "workflow": WORKFLOW_NAME,
            "run_id": str(run.get("databaseId", "") or ""),
            "run_url": str(run.get("url", "") or ""),
            "run_attempt": str(run.get("attempt", "") or ""),
            "head_branch": str(run.get("headBranch", "") or ""),
            "head_sha": str(run.get("headSha", "") or ""),
            "event": str(run.get("event", "") or ""),
            "created_at": str(run.get("createdAt", "") or ""),
            "updated_at": str(run.get("updatedAt", "") or ""),
            "status": str(run.get("status", "") or ""),
            "conclusion": str(run.get("conclusion", "") or ""),
        },
        "artifact": {
            "name": str(artifact.get("name", "") or ""),
            "expired": bool(artifact.get("expired")),
            "size_bytes": int(artifact.get("size_bytes") or 0),
            "archive_download_url": str(artifact.get("archive_download_url", "") or ""),
            **dict(artifact_checks),
        },
        "result": {
            "status": "pass" if success else "fail",
            "success": success,
            "app_count": _int_value(scenario_summary, "app_count"),
            "page_count": _int_value(scenario_summary, "page_count"),
            "widget_count": _int_value(scenario_summary, "widget_count"),
            "interacted_count": _int_value(scenario_summary, "interacted_count"),
            "probed_count": _int_value(scenario_summary, "probed_count"),
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "total_duration_seconds": _float_value(scenario_summary, "total_duration_seconds"),
            "within_target": bool(scenario_summary.get("within_target")),
            "failed_scenarios": list(matrix_summary.get("failed_scenarios") or []),
            "failure_samples": list(matrix_summary.get("failure_samples") or []),
        },
    }


def load_evidence(path: Path) -> dict[str, Any]:
    return _load_json(path)


def validate_evidence(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = evidence.get("source") if isinstance(evidence.get("source"), Mapping) else {}
    artifact = evidence.get("artifact") if isinstance(evidence.get("artifact"), Mapping) else {}
    result = evidence.get("result") if isinstance(evidence.get("result"), Mapping) else {}
    checks = [
        {
            "id": "schema",
            "status": "pass" if evidence.get("schema") == SCHEMA else "fail",
            "summary": f"evidence schema is {SCHEMA}",
        },
        {
            "id": "workflow_run",
            "status": (
                "pass"
                if source.get("workflow") == WORKFLOW_NAME
                and source.get("run_id")
                and source.get("run_url")
                else "fail"
            ),
            "summary": "evidence references a UI robot matrix GitHub run",
        },
        {
            "id": "run_success",
            "status": (
                "pass"
                if source.get("status") == "completed"
                and source.get("conclusion") == "success"
                else "fail"
            ),
            "summary": "GitHub run completed successfully",
        },
        {
            "id": "artifact",
            "status": (
                "pass"
                if artifact.get("name")
                and artifact.get("required_files_present") is True
                and artifact.get("exit_code") == "0"
                and artifact.get("expired") is False
                else "fail"
            ),
            "summary": "robot artifact includes summary, progress log, and zero exit code",
        },
        {
            "id": "robot_result",
            "status": (
                "pass"
                if result.get("success") is True
                and result.get("failed_count") == 0
                and result.get("within_target") is True
                else "fail"
            ),
            "summary": "robot matrix succeeded with zero failures within target",
        },
    ]
    return checks


def evidence_status(evidence: Mapping[str, Any]) -> str:
    return "pass" if all(check["status"] == "pass" for check in validate_evidence(evidence)) else "fail"


def refresh_evidence(
    *,
    repo: str,
    branch: str | None,
    run_id: str | None,
    run_limit: int,
    artifact_dir: Path | None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    run = fetch_run(run_id, repo=repo, repo_root=repo_root) if run_id else fetch_latest_successful_run(
        repo=repo,
        branch=branch,
        limit=run_limit,
        repo_root=repo_root,
    )
    artifact = fetch_artifact_metadata(str(run["databaseId"]), repo=repo, repo_root=repo_root)
    if bool(artifact.get("expired")):
        raise RuntimeError(f"artifact {artifact.get('name')} for run {run['databaseId']} is expired")

    if artifact_dir is not None:
        work_dir = artifact_dir
        matrix_summary, scenario_summary, artifact_checks = load_artifact_payloads(work_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="agilab-ui-robot-evidence-") as tmp:
            work_dir = download_artifact(
                str(run["databaseId"]),
                repo=repo,
                artifact_name=str(artifact["name"]),
                destination=Path(tmp),
                repo_root=repo_root,
            )
            matrix_summary, scenario_summary, artifact_checks = load_artifact_payloads(work_dir)
    return build_evidence(
        run=run,
        artifact=artifact,
        matrix_summary=matrix_summary,
        scenario_summary=scenario_summary,
        artifact_checks=artifact_checks,
    )


def build_report(evidence: Mapping[str, Any]) -> dict[str, Any]:
    checks = validate_evidence(evidence)
    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "schema": SCHEMA,
        "status": "pass" if not failed else "fail",
        "source": dict(evidence.get("source") or {}),
        "result": dict(evidence.get("result") or {}),
        "summary": {
            "check_count": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "checks": checks,
    }


def write_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--run-id", default=None, help="Use an exact GitHub Actions run ID.")
    parser.add_argument("--run-limit", type=int, default=DEFAULT_RUN_LIMIT)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Use an already downloaded artifact directory instead of downloading from GitHub.",
    )
    parser.add_argument("--check", action="store_true", help="Validate the existing output file.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    if args.check:
        evidence = load_evidence(args.output)
    else:
        evidence = refresh_evidence(
            repo=args.repo,
            branch=args.branch or None,
            run_id=args.run_id,
            run_limit=args.run_limit,
            artifact_dir=args.artifact_dir,
        )
        write_evidence(args.output, evidence)

    report = build_report(evidence)
    if not args.quiet:
        if args.compact:
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
