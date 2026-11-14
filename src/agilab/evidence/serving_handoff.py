"""Verify a declarative serving handoff without deploying a serving engine."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from agilab.evidence import evidence_contract, promotion_dossier, run_manifest
from agilab.evidence.evaluation import (
    _digest,
    _number,
    _text,
    check_evidence_seal,
    check_file_reference,
    confined_path,
    file_reference,
    persist_evaluation,
    read_evidence_file,
    read_evidence_json,
    seal_evidence,
    verify_evaluation_receipt,
    verify_evaluation_run,
)

SCHEMA = "agilab.serving_handoff.v1"
CLAIM_SCOPE = (
    "Verified local handoff contract with declared environment, health and rollback expectations. "
    "No service was deployed and no runtime health, throughput or rollback was observed."
)


def _expectations(health: Any, rollback: Any) -> None:
    if not isinstance(health, dict) or set(health) != {
        "readiness_path",
        "timeout_seconds",
        "expected_status",
    }:
        raise ValueError("Declare readiness_path, timeout_seconds and expected_status")
    path = _text(health["readiness_path"], "Readiness path")
    if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
        raise ValueError("Readiness path must be an absolute service-local path")
    if not 0 < _number(health["timeout_seconds"]) <= 300:
        raise ValueError("Health timeout must be positive and at most 300 seconds")
    if (
        type(health["expected_status"]) is not int
        or not 200 <= health["expected_status"] < 300
    ):
        raise ValueError("Expected readiness status must be a successful HTTP status")
    if not isinstance(rollback, dict) or set(rollback) != {
        "reference",
        "sha256",
        "trigger",
    }:
        raise ValueError("Declare immutable rollback reference, sha256 and trigger")
    _text(rollback["reference"], "Rollback reference")
    _digest(rollback["sha256"])
    _text(rollback["trigger"], "Rollback trigger")


def _policy_definition(root: Path, path: str | Path | None) -> dict[str, Any]:
    if path is None:
        payload = evidence_contract._default_policy()
    else:
        raw = read_evidence_file(root, path)
        if Path(path).suffix.lower() in {".toml", ".tml"}:
            import tomllib

            payload = tomllib.loads(raw.decode("utf-8"))
        elif Path(path).suffix.lower() == ".json":
            payload = read_evidence_json(raw)
        else:
            raise ValueError("Serving policy must be JSON or TOML")
    if not isinstance(payload, dict) or set(payload) != {"schema", "id", "rules"}:
        raise ValueError("Serving policy must declare only schema, id and rules")
    if payload["schema"] != "agilab.policy.v1":
        raise ValueError("Unsupported serving policy schema")
    _text(payload["id"], "Policy ID")
    rules = payload["rules"]
    if not isinstance(rules, list) or not rules:
        raise ValueError("Serving policy must declare a nonempty rules list")
    known = promotion_dossier._REQUIRED_VERIFICATION_CHECKS | {"replay_available"}
    seen = set()
    normalized = []
    for rule in rules:
        if isinstance(rule, str):
            rule = {"id": rule, "required": True}
        if not isinstance(rule, dict) or set(rule) - {"id", "required"}:
            raise ValueError("Invalid serving policy rule")
        rule_id = rule.get("id")
        required = rule.get("required", True)
        if (
            not isinstance(rule_id, str)
            or rule_id not in known
            or rule_id in seen
            or type(required) is not bool
        ):
            raise ValueError("Unknown, duplicate or malformed serving policy rule")
        seen.add(rule_id)
        normalized.append({"id": rule_id, "required": required})
    if not any(rule["required"] for rule in normalized):
        raise ValueError("Serving policy must require at least one known rule")
    return {**payload, "rules": normalized}


def _checked_policy(
    definition: Mapping[str, Any],
    manifest: run_manifest.RunManifest,
    verification: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> None:
    checks = {row["id"]: row for row in verification["checks"]}
    rules = []
    for rule in definition["rules"]:
        if rule["required"]:
            check = checks[rule["id"]]
            rules.append(
                {
                    "id": rule["id"],
                    "status": check["status"],
                    "summary": check["summary"],
                    "details": check.get("details", {}),
                }
            )
    expected = {
        "schema": evidence_contract.POLICY_SCHEMA,
        "policy_id": definition["id"],
        "status": "pass" if all(row["status"] == "pass" for row in rules) else "fail",
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "rules": rules,
        "verification_status": verification["status"],
    }
    if set(observed) != set(expected) | {"manifest_path"} or any(
        observed.get(key) != value for key, value in expected.items()
    ):
        raise ValueError(
            "Promotion policy report disagrees with independently evaluated policy"
        )


def _promotion(
    root: Path,
    path: str | Path,
    receipt: Mapping[str, Any],
    receipt_ref: Mapping[str, Any],
    policy_path: str | Path | None,
    decision_ref: Mapping[str, Any],
) -> dict[str, Any]:
    decision = read_evidence_json(check_file_reference(root, decision_ref))
    candidate = receipt["candidate"]
    if decision.get("schema") != promotion_dossier.DECISION_SCHEMA or any(
        decision.get(key) != value
        for key, value in (
            ("decision", "promote"),
            ("status", "pass"),
            ("manifest_status", "pass"),
            ("policy_status", "pass"),
            ("verification_status", "pass"),
            ("blockers", []),
            ("run_id", candidate["run_id"]),
            ("manifest_sha256", candidate["run_manifest"]["sha256"]),
        )
    ):
        raise ValueError(
            "Serving handoff requires a verified promotion of this evaluated candidate"
        )
    gate = decision.get("evaluation", {})
    if (
        gate.get("verification_status") != "pass"
        or gate.get("evaluation_status") != "pass"
        or gate.get("receipt") != receipt_ref
    ):
        raise ValueError("Promotion does not bind the exact passing evaluation receipt")
    policy_file = (
        confined_path(root, path).parent / promotion_dossier.POLICY_RESULTS_JSON
    )
    policy_ref = file_reference(root, policy_file)
    if decision.get("policy_results_sha256") != policy_ref["sha256"]:
        raise ValueError("Promotion policy result bytes changed")
    policy = read_evidence_json(check_file_reference(root, policy_ref))
    manifest_path = confined_path(root, candidate["run_manifest"]["path"])
    manifest = run_manifest.RunManifest.from_dict(
        read_evidence_json(check_file_reference(root, candidate["run_manifest"]))
    )
    verification = verify_evaluation_run(root, candidate["run_manifest"])
    original_root = Path(manifest.environment.active_app)
    allowed_paths = {
        str(manifest_path),
        str(original_root / candidate["run_manifest"]["path"]),
    }
    if policy.get("manifest_path") not in allowed_paths:
        raise ValueError(
            "Promotion policy manifest path does not match the evaluated run"
        )
    _checked_policy(
        _policy_definition(root, policy_path), manifest, verification, policy
    )
    current = promotion_dossier._decision(manifest, policy, verification)
    if current["decision"] != "promote":
        raise ValueError("Current run verification and policy do not permit promotion")
    # Absolute source-root metadata is retained when a verified bundle moves.
    recorded_verification = {**verification, "manifest_path": policy["manifest_path"]}
    if decision.get("verification_sha256") != evidence_contract.sha256_payload(
        recorded_verification
    ):
        raise ValueError("Promotion verification no longer matches the run")
    return policy_ref


def build_serving_handoff(
    app_root: Path,
    *,
    model_artifact: str | Path,
    model_reference: str,
    environment: str | Path,
    evaluation_receipt: str | Path,
    promotion_decision: str | Path,
    health: Mapping[str, Any],
    rollback: Mapping[str, Any],
    policy: str | Path | None = None,
    trusted_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    root = app_root.resolve(strict=True)
    _expectations(dict(health), dict(rollback))
    environment_ref = file_reference(root, environment)
    environment_payload = read_evidence_json(
        check_file_reference(root, environment_ref)
    )
    if not environment_payload:
        raise ValueError("The declared environment must be a nonempty JSON object")
    report = verify_evaluation_receipt(
        root, evaluation_receipt, trusted_receipt_sha256=trusted_receipt_sha256
    )
    if report["status"] != "pass" or report["evaluation_status"] != "pass":
        raise ValueError("A verified passing finite evaluation is required")
    receipt = report["payload"]
    model = file_reference(root, model_artifact)
    identity = {
        "reference": _text(model_reference, "Immutable model reference"),
        "sha256": model["sha256"],
    }
    if identity != receipt["candidate"]["identity"]:
        raise ValueError("The model identity must match the evaluated candidate")
    if (
        identity["reference"] == rollback["reference"]
        or identity["sha256"] == rollback["sha256"]
    ):
        raise ValueError("Rollback must identify a different immutable model")
    policy_ref = file_reference(root, policy) if policy is not None else None
    definition = _policy_definition(root, policy)
    decision_ref = file_reference(root, promotion_decision)
    policy_results = _promotion(
        root, promotion_decision, receipt, report["receipt"], policy, decision_ref
    )
    for reference in (
        environment_ref,
        model,
        report["receipt"],
        decision_ref,
        policy_results,
    ):
        check_file_reference(root, reference)
    if policy_ref is not None:
        check_file_reference(root, policy_ref)
    return seal_evidence(
        {
            "schema": SCHEMA,
            "producer": "agilab.evidence.serving_handoff",
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "app_name": root.name,
            "export_status": "ready",
            "deployment_status": "not_deployed",
            "model": {**identity, "artifact": model},
            "environment": environment_ref,
            "environment_status": "declared",
            "evaluation": report["receipt"],
            "promotion": decision_ref,
            "policy_results": policy_results,
            "policy": policy_ref,
            "policy_sha256": evidence_contract.sha256_payload(definition),
            "health_expectations": dict(health),
            "health_status": "not_observed",
            "rollback_expectations": dict(rollback),
            "rollback_status": "not_executed",
            "claim_scope": CLAIM_SCOPE,
        }
    )


def verify_serving_handoff(
    app_root: Path,
    handoff_path: str | Path,
    *,
    trusted_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        root = app_root.resolve(strict=True)
        handoff_ref = file_reference(root, handoff_path)
        handoff = read_evidence_json(check_file_reference(root, handoff_ref))
        check_evidence_seal(handoff, SCHEMA)
        for row in (
            handoff["model"]["artifact"],
            handoff["environment"],
            handoff["evaluation"],
            handoff["promotion"],
            handoff["policy_results"],
        ):
            check_file_reference(root, row)
        if handoff.get("policy") is not None:
            check_file_reference(root, handoff["policy"])
        rebuilt = build_serving_handoff(
            root,
            model_artifact=handoff["model"]["artifact"]["path"],
            model_reference=handoff["model"]["reference"],
            environment=handoff["environment"]["path"],
            evaluation_receipt=handoff["evaluation"]["path"],
            promotion_decision=handoff["promotion"]["path"],
            health=handoff["health_expectations"],
            rollback=handoff["rollback_expectations"],
            policy=handoff["policy"]["path"]
            if handoff.get("policy") is not None
            else None,
            trusted_receipt_sha256=trusted_receipt_sha256,
        )
        for key in rebuilt:
            if key not in {"sha256", "created_at"} and handoff.get(key) != rebuilt[key]:
                raise ValueError(
                    f"Serving handoff does not match current evidence: {key}"
                )
        check_file_reference(root, handoff_ref)
        return {
            "status": "pass",
            "export_status": "ready",
            "deployment_status": "not_deployed",
            "handoff": handoff_ref,
            "claim_scope": CLAIM_SCOPE,
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {
            "status": "fail",
            "export_status": "blocked",
            "deployment_status": "not_deployed",
            "reason": str(exc),
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create or verify a declarative serving handoff; does not deploy."
    )
    parser.add_argument("operation", choices=("export", "verify"))
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument(
        "--handoff", required=True, help="Handoff path relative to app root."
    )
    parser.add_argument(
        "--spec",
        help="App-root-relative JSON with model, environment, evaluation, promotion, health and rollback inputs.",
    )
    parser.add_argument(
        "--trusted-receipt-sha256",
        help="External receipt pin from the trusted evaluation controller.",
    )
    args = parser.parse_args(argv)
    try:
        if args.operation == "export":
            if not args.spec:
                parser.error("export requires --spec")
            spec = read_evidence_json(read_evidence_file(args.app_root, args.spec))
            if "trusted_receipt_sha256" in spec:
                raise ValueError(
                    "Execution trust pin must come from the caller, outside the serving spec"
                )
            persist_evaluation(
                args.app_root,
                args.handoff,
                build_serving_handoff(
                    args.app_root,
                    **spec,
                    trusted_receipt_sha256=args.trusted_receipt_sha256,
                ),
            )
        result = verify_serving_handoff(
            args.app_root,
            args.handoff,
            trusted_receipt_sha256=args.trusted_receipt_sha256,
        )
    except (OSError, ValueError, TypeError) as exc:
        result = {
            "status": "fail",
            "export_status": "blocked",
            "deployment_status": "not_deployed",
            "reason": str(exc),
        }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
