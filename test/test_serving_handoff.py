from __future__ import annotations

import json
from pathlib import Path

import pytest

from agilab.evidence import evaluation, promotion_dossier, serving_handoff
from test.test_evaluation import (
    build_public_case,
    run_public_case,
    trusted_public_execution as trusted_public_execution,
)


HEALTH = {
    "readiness_path": "/health/ready",
    "timeout_seconds": 5,
    "expected_status": 200,
}
ROLLBACK = {
    "reference": "minimal-public:previous-model",
    "sha256": "a" * 64,
    "trigger": "Readiness probe fails twice",
}


def build_public_handoff(tmp_path: Path, *, candidate=(10, 20, 30)):
    root, _ = build_public_case(tmp_path, candidate=candidate)
    receipt = run_public_case(root)
    (root / "serving-environment.json").write_text(
        json.dumps({"python": "3.13", "dependencies": [], "status": "declared"})
    )
    dossier = promotion_dossier.build_promotion_dossier(
        root / "candidate-run.json",
        root / "promotion",
        evaluation_receipt_path=Path("public-evaluation-receipt.json"),
        evaluation_root=root,
    )
    spec = dict(
        model_artifact="candidate-predictions.json",
        model_reference="minimal-public:candidate-v1",
        environment="serving-environment.json",
        evaluation_receipt="public-evaluation-receipt.json",
        promotion_decision="promotion/promotion_decision.json",
        health=HEALTH,
        rollback=ROLLBACK,
    )
    return root, receipt, dossier, spec


def test_promotion_and_serving_bind_the_exact_evaluated_model(tmp_path):
    root, receipt, dossier, spec = build_public_handoff(tmp_path)
    assert dossier["decision"] == "promote"
    handoff = serving_handoff.build_serving_handoff(root, **spec)
    assert handoff["model"]["sha256"] == receipt["candidate"]["artifact"]["sha256"]
    assert (
        handoff["model"]["reference"] == receipt["candidate"]["identity"]["reference"]
    )
    assert handoff["deployment_status"] == "not_deployed"
    assert handoff["health_status"] == "not_observed"
    assert handoff["rollback_status"] == "not_executed"
    assert handoff["environment_status"] == "declared"
    evaluation.persist_evaluation(root, "public-serving-handoff.json", handoff)
    report = serving_handoff.verify_serving_handoff(root, "public-serving-handoff.json")
    assert report["status"] == "pass"
    assert report["deployment_status"] == "not_deployed"


@pytest.mark.parametrize(
    "filename",
    [
        "candidate-predictions.json",
        "serving-environment.json",
        "public-evaluation-receipt.json",
        "promotion/promotion_decision.json",
        "promotion/policy_results.json",
    ],
)
def test_mutation_rejected_and_restored_contract_recovers(tmp_path, filename):
    root, _, _, spec = build_public_handoff(tmp_path)
    evaluation.persist_evaluation(
        root,
        "public-serving-handoff.json",
        serving_handoff.build_serving_handoff(root, **spec),
    )
    target = root / filename
    original = target.read_bytes()
    target.write_bytes(original + b"\n")
    assert (
        serving_handoff.verify_serving_handoff(root, "public-serving-handoff.json")[
            "status"
        ]
        == "fail"
    )
    target.write_bytes(original)
    assert (
        serving_handoff.verify_serving_handoff(root, "public-serving-handoff.json")[
            "status"
        ]
        == "pass"
    )


def test_regression_blocks_promotion_and_serving(tmp_path):
    root, _, dossier, spec = build_public_handoff(tmp_path, candidate=(14, 24, 34))
    assert dossier["decision"] == "block"
    assert "evaluation_not_passed" in dossier["blockers"]
    with pytest.raises(ValueError, match="passing finite evaluation"):
        serving_handoff.build_serving_handoff(root, **spec)


def test_other_run_receipt_and_cleartext_secret_cannot_be_promoted(tmp_path):
    root, _, _, _ = build_public_handoff(tmp_path)
    mismatch = promotion_dossier.build_promotion_dossier(
        root / "baseline-run.json",
        root / "wrong-promotion",
        evaluation_receipt_path=Path("public-evaluation-receipt.json"),
        evaluation_root=root,
    )
    assert mismatch["decision"] == "block"
    assert "evaluation_candidate_manifest_mismatch" in mismatch["blockers"]
    manifest_path = root / "candidate-run.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["command"]["env_overrides"]["OPENAI_API_KEY"] = "synthetic-cleartext"
    manifest_path.write_text(json.dumps(manifest))
    blocked = promotion_dossier.build_promotion_dossier(
        manifest_path,
        root / "blocked-promotion",
        evaluation_receipt_path=Path("public-evaluation-receipt.json"),
        evaluation_root=root,
    )
    assert blocked["decision"] == "block"
    assert "secret_env_values_redacted" in blocked["blockers"]
    assert "evaluation_verification_failed" in blocked["blockers"]


def test_model_environment_health_and_rollback_require_explicit_valid_contracts(
    tmp_path,
):
    root, _, _, spec = build_public_handoff(tmp_path)
    with pytest.raises(ValueError, match="identity"):
        serving_handoff.build_serving_handoff(
            root, **{**spec, "model_reference": "mutable-latest"}
        )
    for health in (
        {},
        {**HEALTH, "timeout_seconds": float("nan")},
        {**HEALTH, "readiness_path": "//outside/health"},
        {**HEALTH, "expected_status": 500},
    ):
        with pytest.raises(ValueError):
            serving_handoff.build_serving_handoff(root, **{**spec, "health": health})
    with pytest.raises(ValueError, match="different immutable"):
        serving_handoff.build_serving_handoff(
            root,
            **{**spec, "rollback": {**ROLLBACK, "reference": spec["model_reference"]}},
        )
    with pytest.raises(ValueError):
        serving_handoff.build_serving_handoff(
            root, **{**spec, "rollback": {**ROLLBACK, "sha256": "invalid"}}
        )


def test_forged_deployment_status_and_fake_pass_cannot_revalidate(tmp_path):
    root, _, _, spec = build_public_handoff(tmp_path)
    payload = serving_handoff.build_serving_handoff(root, **spec)
    payload["deployment_status"] = "deployed"
    evaluation.persist_evaluation(
        root, "public-serving-handoff.json", evaluation.seal_evidence(payload)
    )
    assert (
        serving_handoff.verify_serving_handoff(root, "public-serving-handoff.json")[
            "status"
        ]
        == "fail"
    )
    decision_path = root / "promotion/promotion_decision.json"
    decision = json.loads(decision_path.read_text())
    decision["verification_status"] = "unknown"
    decision_path.write_text(json.dumps(decision))
    with pytest.raises(ValueError, match="verified promotion"):
        serving_handoff.build_serving_handoff(root, **spec)


def test_serving_module_cli_exports_and_verifies_without_deploying(tmp_path, capsys):
    root, _, _, spec = build_public_handoff(tmp_path)
    (root / "public-serving-spec.json").write_text(json.dumps(spec))
    assert (
        serving_handoff.main(
            [
                "export",
                "--app-root",
                str(root),
                "--handoff",
                "public-serving-handoff.json",
                "--spec",
                "public-serving-spec.json",
            ]
        )
        == 0
    )
    assert '"not_deployed"' in capsys.readouterr().out
    assert (
        serving_handoff.main(
            [
                "verify",
                "--app-root",
                str(root),
                "--handoff",
                "public-serving-handoff.json",
            ]
        )
        == 0
    )


def test_fresh_python_module_verifies_the_same_handoff(tmp_path):
    import os
    import subprocess
    import sys

    root, receipt, _, spec = build_public_handoff(tmp_path)
    evaluation.persist_evaluation(
        root,
        "public-serving-handoff.json",
        serving_handoff.build_serving_handoff(root, **spec),
    )
    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agilab.evidence.serving_handoff",
            "verify",
            "--app-root",
            str(root),
            "--handoff",
            "public-serving-handoff.json",
            "--trusted-receipt-sha256",
            receipt["sha256"],
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["deployment_status"] == "not_deployed"


@pytest.mark.parametrize(
    "mutation", ["unsupported_rule", "unrelated_run", "false_result"]
)
def test_resealed_forged_passing_policy_is_independently_rejected(tmp_path, mutation):
    import hashlib

    root, _, _, spec = build_public_handoff(tmp_path)
    policy_path = root / "promotion/policy_results.json"
    decision_path = root / "promotion/promotion_decision.json"
    original_policy = policy_path.read_bytes()
    original_decision = decision_path.read_bytes()
    forged = json.loads(original_policy)
    if mutation == "unsupported_rule":
        forged["rules"].append({"id": "unsupported-made-up-rule", "status": "pass"})
    elif mutation == "unrelated_run":
        forged["run_id"] = "unrelated-run"
    else:
        forged["rules"][0]["summary"] = "A forged passing observation"
    policy_path.write_text(json.dumps(forged))
    decision = json.loads(original_decision)
    decision["policy_results_sha256"] = hashlib.sha256(
        policy_path.read_bytes()
    ).hexdigest()
    decision_path.write_text(json.dumps(decision))
    with pytest.raises(ValueError, match="policy"):
        serving_handoff.build_serving_handoff(root, **spec)
    policy_path.write_bytes(original_policy)
    decision_path.write_bytes(original_decision)
    handoff = serving_handoff.build_serving_handoff(root, **spec)
    evaluation.persist_evaluation(root, "restored-serving-handoff.json", handoff)
    assert (
        serving_handoff.verify_serving_handoff(root, "restored-serving-handoff.json")[
            "status"
        ]
        == "pass"
    )


def test_custom_original_policy_is_bound_rechecked_and_restorable(tmp_path):
    root, receipt, _, spec = build_public_handoff(tmp_path)
    definition = {
        "schema": "agilab.policy.v1",
        "id": "public.strict.v1",
        "rules": [
            {"id": rule, "required": True}
            for rule in sorted(promotion_dossier._REQUIRED_VERIFICATION_CHECKS)
        ],
    }
    path = root / "original-policy.json"
    path.write_text(json.dumps(definition))
    promotion_dossier.build_promotion_dossier(
        root / "candidate-run.json",
        root / "custom-promotion",
        policy_path=path,
        evaluation_receipt_path=Path("public-evaluation-receipt.json"),
        evaluation_root=root,
    )
    custom = {
        **spec,
        "policy": path.name,
        "promotion_decision": "custom-promotion/promotion_decision.json",
    }
    handoff = serving_handoff.build_serving_handoff(root, **custom)
    assert handoff["policy"] == evaluation.file_reference(root, path)
    assert handoff["policy_sha256"] == evaluation.evidence_contract.sha256_payload(
        definition
    )
    evaluation.persist_evaluation(root, "custom-handoff.json", handoff)
    assert (
        serving_handoff.verify_serving_handoff(root, "custom-handoff.json")["status"]
        == "pass"
    )
    frozen = path.read_bytes()
    path.write_text(
        json.dumps(
            {**definition, "rules": [{"id": "unsupported-rule", "required": False}]}
        )
    )
    assert (
        serving_handoff.verify_serving_handoff(root, "custom-handoff.json")["status"]
        == "fail"
    )
    with pytest.raises(ValueError, match="policy rule"):
        serving_handoff.build_serving_handoff(root, **custom)
    path.write_bytes(frozen)
    assert (
        serving_handoff.verify_serving_handoff(root, "custom-handoff.json")["status"]
        == "pass"
    )


def test_portable_handoff_keeps_original_input_bytes_and_requires_external_pin(
    tmp_path,
):
    import shutil

    root, receipt, _, spec = build_public_handoff(tmp_path)
    evaluation.persist_evaluation(
        root,
        "portable-handoff.json",
        serving_handoff.build_serving_handoff(root, **spec),
    )
    moved_parent = tmp_path / "portable"
    moved_parent.mkdir()
    moved = moved_parent / root.name
    shutil.copytree(root, moved)
    root.rename(tmp_path / "original-unavailable")
    result = serving_handoff.verify_serving_handoff(
        moved, "portable-handoff.json", trusted_receipt_sha256=receipt["sha256"]
    )
    assert result["status"] == "pass", result
    assert result["deployment_status"] == "not_deployed"
    # The old in-process trust scope cannot authorize a different app root.
    untrusted = serving_handoff.verify_serving_handoff(moved, "portable-handoff.json")
    assert untrusted["status"] == "fail"


def test_serving_spec_cannot_supply_its_own_execution_trust(tmp_path, capsys):
    root, receipt, _, spec = build_public_handoff(tmp_path)
    (root / "self-trusting-spec.json").write_text(
        json.dumps({**spec, "trusted_receipt_sha256": receipt["sha256"]})
    )
    result = serving_handoff.main(
        [
            "export",
            "--app-root",
            str(root),
            "--spec",
            "self-trusting-spec.json",
            "--handoff",
            "untrusted-handoff.json",
        ]
    )
    assert result == 1
    assert "outside the serving spec" in capsys.readouterr().out
    assert not (root / "untrusted-handoff.json").exists()
