#!/usr/bin/env python3
"""Emit controlled-pilot deployment evidence for AGILAB production readiness."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.controlled_pilot_readiness.v1"
SUPPORTED_SCORE = "3.2 / 5"
MATRIX_ENTRY_ID = "controlled-pilot-readiness-gate"


def _load_tool_module(name: str) -> Any:
    module_path = REPO_ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_for_controlled_pilot", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"unable to load tool module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def _missing_required_tokens(
    repo_root: Path,
    required: Mapping[str, Sequence[str]],
) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for relative_path, tokens in required.items():
        path = repo_root / relative_path
        try:
            text = _read_text(path)
        except Exception as exc:
            missing[relative_path] = [f"<unable to read: {exc}>"]
            continue
        missing_tokens = [token for token in tokens if token not in text]
        if missing_tokens:
            missing[relative_path] = missing_tokens
    return missing


def _service_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "status": "running",
        "app": "controlled_pilot_project",
        "target": "controlled_pilot",
        "workers_running_count": 2,
        "workers_unhealthy_count": 0,
        "workers_restarted_count": 0,
    }
    payload.update(overrides)
    return payload


def _check_service_health_execution(repo_root: Path) -> dict[str, Any]:
    try:
        service_health = _load_tool_module("service_health_check")
        payload = _service_payload()
        exit_code, reason, details = service_health._evaluate_health(
            payload,
            allow_idle=False,
            max_unhealthy=0,
            max_restart_rate=0.25,
        )
        prometheus = service_health._to_prometheus(
            payload,
            details=details,
            exit_code=exit_code,
            allow_idle=False,
            max_unhealthy=0,
            max_restart_rate=0.25,
        )
        required_prometheus = [
            "agilab_service_workers_running_count",
            "agilab_service_health_gate_pass",
            "agilab_service_restart_rate",
            'state="running"} 1',
        ]
        missing_prometheus = [token for token in required_prometheus if token not in prometheus]
        ok = exit_code == 0 and not missing_prometheus
        details_payload = {
            "exit_code": exit_code,
            "reason": reason,
            "health_details": details,
            "missing_prometheus_tokens": missing_prometheus,
        }
    except Exception as exc:
        ok = False
        details_payload = {"error": str(exc)}
    return _check_result(
        "service_health_execution",
        "Service-health execution contract",
        ok,
        (
            "service-health gate accepts a running pilot payload and exposes Prometheus metrics"
            if ok
            else "service-health gate did not prove the running pilot path"
        ),
        evidence=["tools/service_health_check.py", "test/test_service_health_check.py"],
        details=details_payload,
    )


def _check_service_failure_modes(repo_root: Path) -> dict[str, Any]:
    try:
        service_health = _load_tool_module("service_health_check")
        cases = {
            "unhealthy_workers": (
                _service_payload(workers_unhealthy_count=1),
                2,
                "unhealthy workers",
            ),
            "idle_without_ack": (
                _service_payload(status="idle"),
                4,
                "allow-idle",
            ),
            "restart_rate": (
                _service_payload(workers_running_count=4, workers_restarted_count=2),
                5,
                "restart rate",
            ),
        }
        results: dict[str, dict[str, Any]] = {}
        for name, (payload, expected_code, expected_reason) in cases.items():
            exit_code, reason, details = service_health._evaluate_health(
                payload,
                allow_idle=False,
                max_unhealthy=0,
                max_restart_rate=0.25,
            )
            results[name] = {
                "exit_code": exit_code,
                "expected_code": expected_code,
                "reason": reason,
                "expected_reason": expected_reason,
                "details": details,
            }
        ok = all(
            item["exit_code"] == item["expected_code"]
            and item["expected_reason"] in item["reason"]
            for item in results.values()
        )
        details_payload = {"cases": results}
    except Exception as exc:
        ok = False
        details_payload = {"error": str(exc)}
    return _check_result(
        "service_failure_modes",
        "Service-health failure modes",
        ok,
        (
            "pilot service failure modes return explicit non-zero health-gate codes"
            if ok
            else "pilot service failure-mode contract is incomplete"
        ),
        evidence=["tools/service_health_check.py", "test/test_service_health_check.py"],
        details=details_payload,
    )


def _check_persisted_artifact_contract(repo_root: Path) -> dict[str, Any]:
    required = {
        "tools/service_health_check.py": [
            "--health-output-path",
            "health_output_path",
            'choices=("json", "prometheus")',
            "json.dumps",
        ],
        "test/test_service_health_check.py": [
            "test_service_health_check_forwards_output_path",
            "test_service_health_check_prometheus_output",
            "test_service_health_check_fails_when_unhealthy",
        ],
        "tools/agent_workflows.md": [
            "agilab.agent_run.v1",
            "stdout.txt",
            "stderr.txt",
            "argv hash",
            "redacted",
        ],
        "README.md": [
            "agilab.agent_run.v1",
            "stdout/stderr artifacts",
            "argv hash",
            "redacted",
        ],
    }
    missing = _missing_required_tokens(repo_root, required)
    ok = not missing
    return _check_result(
        "persisted_artifact_contract",
        "Persisted artifact contract",
        ok,
        (
            "controlled-pilot health and agent evidence can be persisted with redacted command metadata"
            if ok
            else "controlled-pilot artifact persistence or redaction evidence is incomplete"
        ),
        evidence=list(required),
        details={"missing": missing},
    )


def _check_public_bind_and_secret_boundary(repo_root: Path) -> dict[str, Any]:
    required = {
        "src/agilab/security/ui_public_bind_guard.py": [
            "AGILAB_PUBLIC_BIND_OK",
            "AGILAB_TLS_TERMINATED",
            "PublicBindPolicyError",
            "public_bind_has_controls",
            "enforce_public_bind_policy",
        ],
        "test/test_ui_public_bind_guard.py": [
            "test_public_bind_requires_explicit_ok_and_auth_or_tls_indicator",
            "test_direct_streamlit_public_bind_is_refused_without_controls",
            "test_direct_streamlit_public_bind_is_allowed_with_controls",
        ],
        "test/test_ui_pages.py": [
            "test_env_editor_redacts_sensitive_values_in_widgets_and_preview",
            "test_agilab_main_page_env_editor_does_not_render_secret_values",
        ],
        "SECURITY.md": [
            "Keep the Streamlit UI on loopback by default",
            "AGILAB_PUBLIC_BIND_OK=1",
            "AGILAB_TLS_TERMINATED=1",
            "redact secret-like keys",
        ],
    }
    missing = _missing_required_tokens(repo_root, required)
    ok = not missing
    return _check_result(
        "public_bind_and_secret_boundary",
        "Public-bind and secret boundary",
        ok,
        (
            "controlled pilots fail closed for public UI exposure and redact secret-like values"
            if ok
            else "public-bind or secret-redaction boundary evidence is incomplete"
        ),
        evidence=list(required),
        details={"missing": missing},
    )


def _check_compatibility_matrix_entry(repo_root: Path) -> dict[str, Any]:
    matrix_path = repo_root / "docs" / "source" / "data" / "compatibility_matrix.toml"
    try:
        with matrix_path.open("rb") as stream:
            payload = tomllib.load(stream)
        entries = payload.get("entries", [])
        entry = next(
            (
                item
                for item in entries
                if isinstance(item, dict) and item.get("id") == MATRIX_ENTRY_ID
            ),
            None,
        )
        proof = str(entry.get("primary_proof", "")) if isinstance(entry, dict) else ""
        limits = entry.get("limits", []) if isinstance(entry, dict) else []
        ok = (
            isinstance(entry, dict)
            and entry.get("status") == "validated"
            and "tools/controlled_pilot_readiness_report.py --compact" in proof
            and any("not production mlops certification" in str(item).lower() for item in limits)
        )
        details = {"entry": entry or {}, "proof": proof}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "compatibility_matrix_entry",
        "Compatibility matrix entry",
        ok,
        (
            "compatibility matrix carries a validated controlled-pilot readiness path"
            if ok
            else "compatibility matrix is missing the controlled-pilot readiness path"
        ),
        evidence=["docs/source/data/compatibility_matrix.toml"],
        details=details,
    )


def build_report(*, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    checks = [
        _check_service_health_execution(repo_root),
        _check_service_failure_modes(repo_root),
        _check_persisted_artifact_contract(repo_root),
        _check_public_bind_and_secret_boundary(repo_root),
        _check_compatibility_matrix_entry(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "schema": SCHEMA,
        "kpi": "Production readiness",
        "evidence_scope": "controlled-pilot deployment readiness",
        "supported_score": SUPPORTED_SCORE,
        "status": "pass" if failed == 0 else "fail",
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "score_boundary": (
                "controlled-pilot readiness only; not production MLOps certification"
            ),
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit controlled-pilot production-readiness evidence for AGILAB."
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON artifact path to write in addition to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_report()
    if args.output is not None:
        output = args.output.expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
