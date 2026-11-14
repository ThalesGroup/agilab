from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import sys

import pytest

from agilab.evidence import evaluation, run_manifest


SCORER = """
import argparse, json, math
from pathlib import Path
p = argparse.ArgumentParser()
for flag in ("fixture", "config", "artifact", "run-manifest"):
    p.add_argument("--" + flag, required=True)
a = p.parse_args()
fixture = json.loads(Path(a.fixture).read_text())
config = json.loads(Path(a.config).read_text())
predictions = json.loads(Path(a.artifact).read_text())["predictions"]
expected = [row["expected"] for row in fixture["cases"]]
errors = [abs(actual - target) for actual, target in zip(predictions, expected, strict=True)]
print(json.dumps({
    "schema": "agilab.eval_score.v1", "status": "pass",
    "metric": config["metric"], "unit": config["unit"], "direction": config["direction"],
    "sample_count": len(errors), "value": sum(errors) / len(errors)
}))
"""


def build_public_case(tmp_path: Path, *, candidate=(10, 20, 30), source: str = SCORER):
    root = tmp_path / "minimal_public_project"
    root.mkdir()
    (root / "fixture.json").write_text(
        json.dumps(
            {
                "cases": [
                    {"id": "a", "expected": 10},
                    {"id": "b", "expected": 20},
                    {"id": "c", "expected": 30},
                ]
            }
        )
    )
    metric = {
        "name": "mean_absolute_error",
        "unit": "metres",
        "direction": "minimize",
        "sample_count": 3,
    }
    (root / "config.json").write_text(
        json.dumps(
            {
                "metric": metric["name"],
                "unit": metric["unit"],
                "direction": metric["direction"],
            }
        )
    )
    (root / "scorer.py").write_text(source)
    for name, predictions in (("baseline", (11, 22, 33)), ("candidate", candidate)):
        artifact = root / f"{name}-predictions.json"
        artifact.write_text(json.dumps({"predictions": predictions}))
        manifest = run_manifest.build_run_manifest(
            path_id="app-owned-evaluation",
            label="Public deterministic local fixture",
            status="pass",
            command=run_manifest.RunManifestCommand(
                label="public scorer fixture",
                argv=(sys.executable, "-c", "print('public fixture')"),
                cwd=str(root),
                env_overrides={},
            ),
            environment=run_manifest.RunManifestEnvironment(
                python_version=sys.version,
                python_executable=sys.executable,
                platform="local-test",
                repo_root=str(root),
                active_app=str(root),
                app_name=root.name,
            ),
            timing=run_manifest.RunManifestTiming(
                started_at="2026-11-13T00:00:00Z",
                finished_at="2026-11-13T00:00:01Z",
                duration_seconds=1.0,
                target_seconds=30.0,
            ),
            artifacts=[run_manifest.RunManifestArtifact.from_path(artifact)],
            validations=[
                run_manifest.RunManifestValidation(
                    label="fixture-produced",
                    status="pass",
                    summary="Public local fixture",
                )
            ],
            run_id=f"public-{name}",
            created_at="2026-11-13T00:00:01Z",
        )
        run_manifest.write_run_manifest(manifest, root / f"{name}-run.json")
    plan = evaluation.build_eval_manifest(
        root,
        fixture="fixture.json",
        scorer="scorer.py",
        config="config.json",
        baseline_run="baseline-run.json",
        baseline_artifact="baseline-predictions.json",
        baseline_reference="minimal-public:baseline-v1",
        candidate_run="candidate-run.json",
        candidate_artifact="candidate-predictions.json",
        candidate_reference="minimal-public:candidate-v1",
        metric=metric,
    )
    evaluation.persist_evaluation(root, "public-eval-manifest.json", plan)
    return root, plan


_TRUST_STACK = None


@pytest.fixture(autouse=True)
def trusted_public_execution():
    global _TRUST_STACK
    with ExitStack() as stack:
        previous = _TRUST_STACK
        _TRUST_STACK = stack
        try:
            yield
        finally:
            _TRUST_STACK = previous


def run_public_case(root: Path):
    receipt = evaluation.run_evaluation(
        root, "public-eval-manifest.json", operator_requested=True
    )
    evaluation.persist_evaluation(root, "public-evaluation-receipt.json", receipt)
    assert _TRUST_STACK is not None
    _TRUST_STACK.enter_context(
        evaluation.trusted_evaluation_receipt(root, receipt["sha256"])
    )
    return receipt


@pytest.mark.parametrize(
    ("candidate", "expected", "status"),
    [
        ((10, 20, 30), 0.0, "pass"),
        ((11, 22, 33), 2.0, "pass"),
        ((14, 24, 34), 4.0, "fail"),
    ],
)
def test_actual_public_scorer_has_independently_expected_values(
    tmp_path, candidate, expected, status
):
    root, plan = build_public_case(tmp_path, candidate=candidate)
    receipt = run_public_case(root)
    assert receipt["scores"]["baseline"]["score"]["value"] == 2.0
    assert receipt["scores"]["candidate"]["score"]["value"] == expected
    assert receipt["comparison"]["improvement"] == 2.0 - expected
    assert receipt["evaluation_status"] == status
    assert receipt["execution"]["scorer_sha256"] == plan["inputs"]["scorer"]["sha256"]
    assert receipt["execution"]["producer_sha256"]
    assert receipt["execution"]["python_sha256"]
    verified = evaluation.verify_evaluation_receipt(
        root, "public-evaluation-receipt.json"
    )
    assert verified["status"] == "pass"
    assert verified["evaluation_status"] == status


def test_no_scorer_execution_without_explicit_request(tmp_path):
    root, _ = build_public_case(
        tmp_path, source="raise RuntimeError('must not execute')"
    )
    with pytest.raises(ValueError, match="explicit operator request"):
        evaluation.run_evaluation(root, "public-eval-manifest.json")
    assert not (root / "public-evaluation-receipt.json").exists()


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('"sample_count": len(errors)', '"sample_count": 99'),
        ('"unit": config["unit"]', '"unit": "seconds"'),
        ('"direction": config["direction"]', '"direction": "maximize"'),
        ('"status": "pass"', '"status": "fail"'),
        ('"value": sum(errors) / len(errors)', '"value": float("nan")'),
        ('"value": sum(errors) / len(errors)', '"value": float("inf")'),
    ],
)
def test_incomparable_failed_and_nonfinite_scores_stay_unavailable(tmp_path, old, new):
    root, _ = build_public_case(tmp_path, source=SCORER.replace(old, new))
    receipt = run_public_case(root)
    assert receipt["evaluation_status"] == "unavailable"
    assert receipt["comparison"]["improvement"] is None
    assert receipt["comparison"]["delta"] is None
    assert (
        evaluation.verify_evaluation_receipt(root, "public-evaluation-receipt.json")[
            "status"
        ]
        == "pass"
    )


@pytest.mark.parametrize(
    "filename",
    [
        "fixture.json",
        "scorer.py",
        "config.json",
        "baseline-run.json",
        "candidate-run.json",
        "baseline-predictions.json",
        "candidate-predictions.json",
    ],
)
def test_exact_byte_mutations_block_then_restore_success(tmp_path, filename):
    root, _ = build_public_case(tmp_path)
    target = root / filename
    original = target.read_bytes()
    target.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="changed"):
        evaluation.run_evaluation(
            root, "public-eval-manifest.json", operator_requested=True
        )
    target.write_bytes(original)
    run_public_case(root)
    assert (
        evaluation.verify_evaluation_receipt(root, "public-evaluation-receipt.json")[
            "status"
        ]
        == "pass"
    )
    target.write_bytes(original + b"\n")
    assert (
        evaluation.verify_evaluation_receipt(root, "public-evaluation-receipt.json")[
            "status"
        ]
        == "fail"
    )


def test_missing_input_has_actionable_failure(tmp_path):
    root, _ = build_public_case(tmp_path)
    (root / "fixture.json").unlink()
    with pytest.raises(FileNotFoundError):
        evaluation.run_evaluation(
            root, "public-eval-manifest.json", operator_requested=True
        )


def test_scorer_failure_timeout_and_recovery(tmp_path):
    root, _ = build_public_case(
        tmp_path, source="raise RuntimeError('synthetic local failure')"
    )
    failed = run_public_case(root)
    assert failed["evaluation_status"] == "unavailable"
    assert failed["scores"]["candidate"]["reason"] == "scorer_failed"

    other = tmp_path / "timeout"
    other.mkdir()
    root2, _ = build_public_case(other, source="import time; time.sleep(2)")
    timed = evaluation.run_evaluation(
        root2,
        "public-eval-manifest.json",
        operator_requested=True,
        timeout_seconds=0.05,
    )
    assert timed["scores"]["candidate"]["reason"] == "scorer_timeout"
    assert timed["comparison"]["improvement"] is None

    recovered_dir = tmp_path / "recovered"
    recovered_dir.mkdir()
    recovered, _ = build_public_case(recovered_dir)
    assert run_public_case(recovered)["evaluation_status"] == "pass"


def test_frozen_scorer_bytes_execute_even_if_snapshot_source_is_replaced(
    tmp_path, monkeypatch
):
    root, _ = build_public_case(tmp_path)
    original_run = evaluation.subprocess.run

    def replace_disk_copy(argv, **kwargs):
        # This is the source path an ordinary python FILE launcher would reread.
        (Path(kwargs["cwd"]) / "scorer.py").chmod(0o600)
        (Path(kwargs["cwd"]) / "scorer.py").write_text(
            "raise RuntimeError('different source bytes')"
        )
        return original_run(argv, **kwargs)

    monkeypatch.setattr(evaluation.subprocess, "run", replace_disk_copy)
    receipt = run_public_case(root)
    assert receipt["evaluation_status"] == "unavailable"
    assert receipt["scores"]["candidate"]["reason"] == "input_changed_during_execution"


def test_argv_execution_preserves_paths_with_spaces_and_removes_shell_secrets(
    tmp_path, monkeypatch
):
    # A scorer sees only the explicitly constructed environment.
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-not-forwarded")
    tmp_path = tmp_path / "public app inputs with spaces"
    tmp_path.mkdir()
    source = SCORER.replace(
        "p = argparse.ArgumentParser()",
        "import os\nassert 'OPENAI_API_KEY' not in os.environ\np = argparse.ArgumentParser()",
    )
    root, _ = build_public_case(tmp_path, source=source)
    assert run_public_case(root)["evaluation_status"] == "pass"


def test_paths_symlinks_duplicate_keys_and_receipt_tampering_are_rejected(tmp_path):
    root, _ = build_public_case(tmp_path)
    with pytest.raises(ValueError, match="app root"):
        evaluation.file_reference(root, root.parent / "outside.json")
    (root / "alias.json").symlink_to(root / "fixture.json")
    with pytest.raises(ValueError, match="symlink"):
        evaluation.file_reference(root, "alias.json")
    with pytest.raises(ValueError, match="Duplicate"):
        evaluation.read_evidence_json(b'{"value": 1, "value": 2}')
    run_public_case(root)
    path = root / "public-evaluation-receipt.json"
    payload = json.loads(path.read_text())
    payload["comparison"]["improvement"] = 999
    path.write_text(json.dumps(payload))
    assert evaluation.verify_evaluation_receipt(root, path)["status"] == "fail"


def test_receipt_is_write_once_and_cli_requires_execution_flag(tmp_path, capsys):
    root, _ = build_public_case(tmp_path)
    assert (
        evaluation.main(
            [
                "run",
                "--app-root",
                str(root),
                "--manifest",
                "public-eval-manifest.json",
                "--receipt",
                "public-evaluation-receipt.json",
            ]
        )
        == 1
    )
    assert "explicit operator request" in capsys.readouterr().out
    assert (
        evaluation.main(
            [
                "run",
                "--app-root",
                str(root),
                "--manifest",
                "public-eval-manifest.json",
                "--receipt",
                "public-evaluation-receipt.json",
                "--execute-scorer",
            ]
        )
        == 0
    )
    observed_pin = json.loads(capsys.readouterr().out)[
        "observed_execution_receipt_sha256"
    ]
    assert (
        evaluation.main(
            [
                "verify",
                "--trusted-receipt-sha256",
                observed_pin,
                "--app-root",
                str(root),
                "--receipt",
                "public-evaluation-receipt.json",
            ]
        )
        == 0
    )
    with pytest.raises(FileExistsError):
        evaluation.persist_evaluation(root, "public-evaluation-receipt.json", {})


def test_overflow_comparison_and_unknown_observation_do_not_invent_gain():
    metric = {
        "name": "metric",
        "unit": "units",
        "direction": "maximize",
        "sample_count": 1,
    }

    def observation(value):
        return {
            "status": "available",
            "returncode": 0,
            "stdout_sha256": "a" * 64,
            "score": {
                "schema": evaluation.SCORE_SCHEMA,
                "status": "pass",
                "metric": "metric",
                "unit": "units",
                "direction": "maximize",
                "sample_count": 1,
                "value": value,
            },
        }

    result = evaluation._comparison(
        {"baseline": observation(-1e308), "candidate": observation(1e308)}, metric
    )
    assert result == {"status": "unavailable", "delta": None, "improvement": None}
    with pytest.raises(ValueError, match="finite"):
        evaluation._number(10**1000)
    with pytest.raises(ValueError, match="Unknown"):
        evaluation._comparison(
            {"baseline": {"status": "unknown"}, "candidate": observation(1)}, metric
        )


def test_evaluation_cannot_substitute_an_artifact_not_declared_by_the_run(tmp_path):
    root, _ = build_public_case(tmp_path)
    (root / "unrelated-predictions.json").write_text('{"predictions": [0, 0, 0]}')
    with pytest.raises(ValueError, match="declared by its exact run"):
        evaluation.build_eval_manifest(
            root,
            fixture="fixture.json",
            scorer="scorer.py",
            config="config.json",
            baseline_run="baseline-run.json",
            baseline_artifact="baseline-predictions.json",
            baseline_reference="baseline-v1",
            candidate_run="candidate-run.json",
            candidate_artifact="unrelated-predictions.json",
            candidate_reference="candidate-v1",
            metric={
                "name": "mean_absolute_error",
                "unit": "metres",
                "direction": "minimize",
                "sample_count": 3,
            },
        )


def test_resealed_fabricated_score_is_not_trusted_execution(tmp_path):
    from agilab.evidence import promotion_dossier

    root, _ = build_public_case(tmp_path)
    observed = run_public_case(root)
    path = root / "public-evaluation-receipt.json"
    fabricated = json.loads(path.read_text())
    fabricated["scores"]["candidate"]["score"]["value"] = -1.0
    fabricated["comparison"] = evaluation._comparison(
        fabricated["scores"], fabricated["metric"]
    )
    fabricated["evaluation_status"] = fabricated["comparison"]["status"]
    path.write_text(json.dumps(evaluation.seal_evidence(fabricated)))
    # All scorer/fixture/config/run bytes are unchanged, and the new checksum is valid.
    report = evaluation.verify_evaluation_receipt(root, path)
    assert report["status"] == "fail"
    assert report["evaluation_status"] == "unavailable"
    dossier = promotion_dossier.build_promotion_dossier(
        root / "candidate-run.json",
        root / "forged-promotion",
        evaluation_receipt_path=path,
        evaluation_root=root,
    )
    assert dossier["decision"] == "block"
    # The pin was captured by the trusted controller from actual execution, before mutation.
    pinned = evaluation.verify_evaluation_receipt(
        root, path, trusted_receipt_sha256=observed["sha256"]
    )
    assert pinned["status"] == "fail"


def _path_race_child(root, relative, outside, attack, output):
    import os

    original = evaluation.confined_path
    fired = False

    def swap_after_check(base, value):
        nonlocal fired
        selected = original(base, value)
        if (
            attack != "fifo"
            and not fired
            and Path(base) == root
            and Path(value) == Path(relative)
        ):
            fired = True
            if attack == "parent_symlink":
                selected.parent.rename(root / "parked-inputs")
                selected.parent.symlink_to(outside.parent, target_is_directory=True)
            else:
                selected.unlink()
                if attack == "fifo":
                    os.mkfifo(selected)
                else:
                    selected.symlink_to(outside)
        return selected

    evaluation.confined_path = swap_after_check
    if attack == "fifo":
        original_path_open = Path.open
        original_os_open = os.open

        def fifo():
            nonlocal fired
            if not fired:
                fired = True
                selected = root / relative
                selected.unlink()
                os.mkfifo(selected)

        def path_open(selected, *args, **kwargs):
            if selected == root / relative:
                fifo()
            return original_path_open(selected, *args, **kwargs)

        def descriptor_open(selected, *args, **kwargs):
            if (
                str(selected) == Path(relative).name
                and kwargs.get("dir_fd") is not None
            ):
                fifo()
            return original_os_open(selected, *args, **kwargs)

        Path.open = path_open
        os.open = descriptor_open
    try:
        value = evaluation.read_evidence_file(root, relative)
        output.send(("accepted", value))
    except (OSError, ValueError) as exc:
        output.send(("rejected", str(exc)))
    finally:
        output.close()


@pytest.mark.parametrize("attack", ["file_symlink", "parent_symlink", "fifo"])
def test_descriptor_path_races_reject_without_hanging_or_leaking(tmp_path, attack):
    import multiprocessing

    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("Deterministic descriptor-race qualification requires POSIX fork")
    root = tmp_path / "root"
    (root / "inputs").mkdir(parents=True)
    (root / "inputs/data.json").write_bytes(b"original")
    outside = tmp_path / "outside/data.json"
    outside.parent.mkdir()
    outside.write_bytes(b"outside-must-not-be-read")
    ctx = multiprocessing.get_context("fork")
    receiver, sender = ctx.Pipe(duplex=False)
    child = ctx.Process(
        target=_path_race_child,
        args=(root, "inputs/data.json", outside, attack, sender),
    )
    child.start()
    sender.close()
    try:
        child.join(2)
        finished = not child.is_alive()
        result = receiver.recv() if finished and receiver.poll() else None
    finally:
        if child.is_alive():
            child.terminate()
        child.join(2)
        receiver.close()
        assert not child.is_alive()
    assert finished, "FIFO substitution blocked the reader"
    assert result and result[0] == "rejected", result
    assert outside.read_bytes() == b"outside-must-not-be-read"


def test_verification_needs_external_execution_trust_and_never_runs_scorer(
    tmp_path, monkeypatch
):
    root, _ = build_public_case(tmp_path)
    observed = run_public_case(root)

    def forbidden(*args, **kwargs):
        raise AssertionError("Verification must never execute an authored scorer")

    monkeypatch.setattr(evaluation, "_execute_score", forbidden)
    with evaluation.trusted_evaluation_receipt(tmp_path, "a" * 64):
        untrusted = evaluation.verify_evaluation_receipt(
            root, "public-evaluation-receipt.json"
        )
        assert untrusted["status"] == "fail"
        assert untrusted["internal_consistency_status"] == "pass"
        assert untrusted["execution_authenticity"] == "untrusted"
        pinned = evaluation.verify_evaluation_receipt(
            root,
            "public-evaluation-receipt.json",
            trusted_receipt_sha256=observed["sha256"],
        )
        assert pinned["status"] == "pass"
        assert pinned["execution_authenticity"] == "caller_pinned_receipt"
    # Pins are confined to the declared app root and leave no ambient trust after exit.
    assert (
        evaluation.verify_evaluation_receipt(root, "public-evaluation-receipt.json")[
            "status"
        ]
        == "pass"
    )


def test_created_output_parent_race_cannot_write_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "outputs").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    original = evaluation.confined_path
    fired = False

    def swapped(base, value):
        nonlocal fired
        selected = original(base, value)
        if not fired:
            fired = True
            selected.parent.rename(root / "parked")
            selected.parent.symlink_to(outside, target_is_directory=True)
        return selected

    monkeypatch.setattr(evaluation, "confined_path", swapped)
    with pytest.raises((ValueError, OSError)):
        evaluation.persist_evaluation(root, "outputs/receipt.json", {"schema": "test"})
    assert not list(outside.iterdir())


@pytest.mark.parametrize(
    "attack", ["entry_replaced", "in_place_changed", "parent_replaced"]
)
def test_descriptor_identity_changes_refuse_and_close_all_handles(
    tmp_path, monkeypatch, attack
):
    import os

    root = tmp_path / "root"
    (root / "inputs").mkdir(parents=True)
    selected = root / "inputs/data.json"
    selected.write_bytes(b"original")
    original = os.read
    fired = False

    def changed(descriptor, count):
        nonlocal fired
        data = original(descriptor, count)
        if not fired:
            fired = True
            if attack == "entry_replaced":
                selected.unlink()
                selected.write_bytes(b"original")
            elif attack == "in_place_changed":
                selected.write_bytes(b"replaced")
            else:
                selected.parent.rename(root / "parked")
                selected.parent.mkdir()
                selected.write_bytes(b"original")
        return data

    before = len(list(Path("/dev/fd").iterdir()))
    with monkeypatch.context() as scoped:
        scoped.setattr(evaluation.os, "read", changed)
        with pytest.raises(ValueError, match="changed"):
            evaluation.read_evidence_file(root, "inputs/data.json")
    assert len(list(Path("/dev/fd").iterdir())) == before
    assert evaluation.read_evidence_file(root, "inputs/data.json") in (
        b"original",
        b"replaced",
    )


def test_write_parent_rename_cleans_only_its_created_file(tmp_path, monkeypatch):
    import os

    root = tmp_path / "root"
    (root / "outputs").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    original = os.open
    fired = False

    def changed(name, *args, **kwargs):
        nonlocal fired
        descriptor = original(name, *args, **kwargs)
        if str(name) == "receipt.json" and not fired:
            fired = True
            (root / "outputs").rename(root / "parked")
            (root / "outputs").symlink_to(outside, target_is_directory=True)
        return descriptor

    with monkeypatch.context() as scoped:
        scoped.setattr(evaluation.os, "open", changed)
        with pytest.raises(ValueError, match="directory changed"):
            evaluation.persist_evaluation(
                root, "outputs/receipt.json", {"schema": "test"}
            )
    assert not list(outside.iterdir())
    assert not list((root / "parked").iterdir())


def test_receipt_reference_never_reopens_to_different_bytes(tmp_path, monkeypatch):
    root, _ = build_public_case(tmp_path)
    observed = run_public_case(root)
    original = evaluation._comparison
    path = root / "public-evaluation-receipt.json"
    frozen = path.read_bytes()

    def swapped(scores, metric):
        result = original(scores, metric)
        path.write_bytes(frozen + b"\n")
        return result

    monkeypatch.setattr(evaluation, "_comparison", swapped)
    report = evaluation.verify_evaluation_receipt(
        root, path, trusted_receipt_sha256=observed["sha256"]
    )
    assert report["status"] == "fail"
    assert report["execution_authenticity"] == "untrusted"
