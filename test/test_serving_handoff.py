from __future__ import annotations

import json
from pathlib import Path

import pytest

from agilab.evidence import evaluation, promotion_dossier, serving_handoff
from test.test_evaluation import (
    SCORER,
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


def build_public_handoff(
    tmp_path: Path,
    *,
    candidate=(10, 20, 30),
    candidate_artifacts=(),
    artifact_bytes=None,
    candidate_directory="",
    source=SCORER,
):
    root, _ = build_public_case(
        tmp_path,
        candidate=candidate,
        candidate_artifacts=candidate_artifacts,
        candidate_directory=candidate_directory,
        source=source,
    )
    for path, data in (artifact_bytes or {}).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    receipt = run_public_case(root)
    (root / "serving-environment.json").write_text(
        json.dumps({"python": "3.13", "dependencies": [], "status": "declared"})
    )
    dossier = promotion_dossier.build_promotion_dossier(
        root / receipt["candidate"]["run_manifest"]["path"],
        root / "promotion",
        evaluation_receipt_path=Path("public-evaluation-receipt.json"),
        evaluation_root=root,
    )
    spec = dict(
        model_artifact=receipt["candidate"]["artifact"]["path"],
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


def test_optional_artifact_appearance_invalidates_unchanged_promotion_and_recovers(
    tmp_path,
):
    import hashlib

    marker = tmp_path / "scorer-executions"
    source = SCORER + f"\nPath({str(marker)!r}).open('ab').write(b'executed\\n')\n"
    optional = evaluation.run_manifest.RunManifestArtifact(
        "optional", "optional.json", "file", False
    )
    root, receipt, _, spec = build_public_handoff(
        tmp_path, candidate_artifacts=[optional], source=source
    )
    execution_count = marker.read_bytes()
    assert execution_count == b"executed\nexecuted\n"
    handoff = serving_handoff.build_serving_handoff(root, **spec)
    evaluation.persist_evaluation(root, "optional-handoff.json", handoff)
    bound_paths = [
        "public-eval-manifest.json",
        "public-evaluation-receipt.json",
        "candidate-run.json",
        "candidate-predictions.json",
        "promotion/promotion_decision.json",
        "promotion/policy_results.json",
    ]
    frozen = {
        p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in bound_paths
    }
    pin = receipt["sha256"]

    def verify():
        return serving_handoff.verify_serving_handoff(
            root, "optional-handoff.json", trusted_receipt_sha256=pin
        )

    assert verify()["status"] == "pass"
    optional_path = root / optional.path
    optional_path.write_bytes(b"new current artifact")
    result = verify()
    assert result["status"] == "fail"
    assert "Promotion verification no longer matches" in result["reason"]
    with pytest.raises(ValueError, match="Promotion verification no longer matches"):
        serving_handoff.build_serving_handoff(root, **spec, trusted_receipt_sha256=pin)
    assert frozen == {
        p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in bound_paths
    }
    optional_path.unlink()
    assert verify()["status"] == "pass"
    assert marker.read_bytes() == execution_count


@pytest.mark.parametrize("hashed", [False, True])
@pytest.mark.parametrize("mutation", ["same_size", "different_size", "removed"])
def test_preexisting_declared_absent_artifact_remains_bound_and_restorable(
    tmp_path, hashed, mutation
):
    import hashlib

    original = b"current-sidecar"
    optional = evaluation.run_manifest.RunManifestArtifact(
        "sidecar",
        "support/sidecar.bin",
        "file",
        False,
        sha256=hashlib.sha256(original).hexdigest() if hashed else "",
    )
    root, receipt, _, spec = build_public_handoff(
        tmp_path,
        candidate_artifacts=[optional],
        artifact_bytes={optional.path: original},
    )
    evaluation.persist_evaluation(
        root,
        "sidecar-handoff.json",
        serving_handoff.build_serving_handoff(root, **spec),
    )
    path = root / optional.path
    if mutation == "removed":
        path.unlink()
    else:
        path.write_bytes(
            b"mutated-sidecar" if mutation == "same_size" else b"longer sidecar bytes"
        )
    result = serving_handoff.verify_serving_handoff(
        root, "sidecar-handoff.json", trusted_receipt_sha256=receipt["sha256"]
    )
    assert result["status"] == "fail", result
    path.write_bytes(original)
    assert (
        serving_handoff.verify_serving_handoff(
            root, "sidecar-handoff.json", trusted_receipt_sha256=receipt["sha256"]
        )["status"]
        == "pass"
    )


@pytest.mark.parametrize("directory", ["", "nested/runs"])
def test_multifile_relocated_handoff_restores_only_source_locations(
    tmp_path, directory
):
    import hashlib
    import shutil

    artifacts = [
        evaluation.run_manifest.RunManifestArtifact(
            "hashed-sidecar",
            "hashed.bin",
            "file",
            False,
            sha256=hashlib.sha256(b"hashed").hexdigest(),
        ),
        evaluation.run_manifest.RunManifestArtifact(
            "unhashed-sidecar", "unhashed.bin", "file", False
        ),
    ]
    root, receipt, _, spec = build_public_handoff(
        tmp_path,
        candidate_artifacts=artifacts,
        candidate_directory=directory,
        artifact_bytes={
            (Path(directory) / "hashed.bin").as_posix(): b"hashed",
            (Path(directory) / "unhashed.bin").as_posix(): b"unhashed",
        },
    )
    reference = receipt["candidate"]["run_manifest"]
    manifest_path = root / reference["path"]
    manifest = evaluation.run_manifest.load_run_manifest(manifest_path)
    direct = evaluation.evidence_contract.verify_manifest(manifest_path)
    for _ in range(2):
        current = evaluation.verify_evaluation_run(root, reference)
        assert (
            serving_handoff._source_verification(current, manifest, str(manifest_path))
            == direct
        )
    evaluation.persist_evaluation(
        root, "multi-handoff.json", serving_handoff.build_serving_handoff(root, **spec)
    )
    frozen = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
    moved_parent = tmp_path / "relocated"
    moved_parent.mkdir()
    moved = moved_parent / root.name
    shutil.copytree(root, moved)
    root.rename(tmp_path / "original-unavailable")
    result = serving_handoff.verify_serving_handoff(
        moved, "multi-handoff.json", trusted_receipt_sha256=receipt["sha256"]
    )
    assert result["status"] == "pass", result
    assert (
        serving_handoff.verify_serving_handoff(moved, "multi-handoff.json")["status"]
        == "fail"
    )
    assert (
        serving_handoff.verify_serving_handoff(
            moved, "multi-handoff.json", trusted_receipt_sha256="0" * 64
        )["status"]
        == "fail"
    )
    assert frozen == {p: (moved / p).read_bytes() for p in frozen}


@pytest.mark.parametrize(
    "fault", ["missing", "not_list", "count", "not_dict", "id", "order"]
)
def test_current_artifact_inventory_and_identity_are_checked(tmp_path, fault):
    import copy

    optional = evaluation.run_manifest.RunManifestArtifact(
        "optional", "optional.json", "file", False
    )
    root, _ = build_public_case(tmp_path, candidate_artifacts=[optional])
    manifest_path = root / "candidate-run.json"
    manifest = evaluation.run_manifest.load_run_manifest(manifest_path)
    current = evaluation.verify_evaluation_run(
        root, evaluation.file_reference(root, manifest_path)
    )
    broken = copy.deepcopy(current)
    if fault == "missing":
        del broken["artifacts"]
    elif fault == "not_list":
        broken["artifacts"] = {}
    elif fault == "count":
        broken["artifacts"].pop()
    elif fault == "not_dict":
        broken["artifacts"][0] = None
    elif fault == "id":
        broken["artifacts"][0]["id"] = "another-artifact"
    else:
        broken["artifacts"].reverse()
    with pytest.raises(ValueError, match="artifact (inventory|identity)"):
        serving_handoff._source_verification(broken, manifest, str(manifest_path))


def test_source_location_restoration_preserves_all_nonlocation_fields_and_order(
    tmp_path,
):
    import copy

    artifacts = [
        evaluation.run_manifest.RunManifestArtifact("same-id", "a.bin", "file", False),
        evaluation.run_manifest.RunManifestArtifact("same-id", "b.bin", "file", False),
    ]
    root, _ = build_public_case(tmp_path, candidate_artifacts=artifacts)
    (root / "a.bin").write_bytes(b"first")
    (root / "b.bin").write_bytes(b"other")
    manifest_path = root / "candidate-run.json"
    manifest = evaluation.run_manifest.load_run_manifest(manifest_path)
    current = evaluation.verify_evaluation_run(
        root, evaluation.file_reference(root, manifest_path)
    )

    def normalize(value):
        return serving_handoff._source_verification(value, manifest, str(manifest_path))

    restored = normalize(current)
    assert restored == evaluation.evidence_contract.verify_manifest(manifest_path)
    observed = copy.deepcopy(current)
    observed["future_check"] = {"status": "fail"}
    observed["artifacts"][1]["future_observation"] = {"status": "fail"}
    normalized = normalize(observed)
    assert normalized["future_check"] == {"status": "fail"}
    assert normalized["artifacts"][1]["future_observation"] == {"status": "fail"}
    assert evaluation.evidence_contract.sha256_payload(
        normalized
    ) != evaluation.evidence_contract.sha256_payload(restored)
    swapped = copy.deepcopy(current)
    swapped["artifacts"][1], swapped["artifacts"][2] = (
        swapped["artifacts"][2],
        swapped["artifacts"][1],
    )
    assert evaluation.evidence_contract.sha256_payload(
        normalize(swapped)
    ) != evaluation.evidence_contract.sha256_payload(restored)
    assert current["artifacts"][1]["path"] != restored["artifacts"][1]["path"]


def test_tilde_artifact_keeps_safe_refusal_without_home_path_rebasing(
    tmp_path, monkeypatch
):
    home = tmp_path / "fixture-home"
    home.mkdir()
    outside = home / "sidecar.json"
    outside.write_bytes(b"outside the app root")
    monkeypatch.setenv("HOME", str(home))
    optional = evaluation.run_manifest.RunManifestArtifact(
        "home-sidecar", "~/sidecar.json", "file", False
    )
    root, _, dossier, spec = build_public_handoff(
        tmp_path, candidate_artifacts=[optional]
    )
    assert dossier["decision"] == "promote"
    with pytest.raises(ValueError, match="Promotion verification no longer matches"):
        serving_handoff.build_serving_handoff(root, **spec)
    assert outside.read_bytes() == b"outside the app root"
