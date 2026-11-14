"""Exercise the public CLI against the real, deterministic evidence backends."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from agilab import lab_run
from agilab.evidence import evaluation
from test.test_evaluation import build_public_case
from test.test_serving_handoff import HEALTH, ROLLBACK


ROOT = Path(__file__).resolve().parents[1]
PIN_OPTION = "--evaluation-receipt-sha256"


def cli_json(capsys, argv):
    code = lab_run.main(argv)
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def public_cli_case(tmp_path, capsys):
    root, _ = build_public_case(tmp_path)
    code, report = cli_json(
        capsys,
        [
            "evaluation",
            "run",
            "--app-root",
            str(root),
            "--manifest",
            "public-eval-manifest.json",
            "--receipt",
            "public-evaluation-receipt.json",
            "--execute-scorer",
        ],
    )
    assert code == 0
    assert report["status"] == report["evaluation_status"] == "pass"
    receipt = json.loads((root / "public-evaluation-receipt.json").read_text())
    assert receipt["scores"]["baseline"]["score"]["value"] == 2.0
    assert receipt["scores"]["candidate"]["score"]["value"] == 0.0
    pin = report["observed_execution_receipt_sha256"]
    assert pin == receipt["sha256"]
    assert evaluation._TRUSTED_RECEIPT.get() is None
    return root, pin


def dossier_args(root, output="promotion", command="promotion-dossier"):
    return [
        command,
        str(root / "candidate-run.json"),
        "--output-dir",
        str(root / output),
        "--evaluation-root",
        str(root),
        "--evaluation-receipt",
        "public-evaluation-receipt.json",
        "--json",
        "--strict",
    ]


def test_evaluation_cli_requires_explicit_execution(tmp_path, capsys):
    root, _ = build_public_case(
        tmp_path, source="raise RuntimeError('must not execute')"
    )
    code, report = cli_json(
        capsys,
        [
            "evaluation",
            "run",
            "--app-root",
            str(root),
            "--manifest",
            "public-eval-manifest.json",
            "--receipt",
            "unrequested-receipt.json",
        ],
    )
    assert code == 1
    assert "explicit operator request" in report["reason"]
    assert not (root / "unrequested-receipt.json").exists()


@pytest.mark.parametrize("trust", ["none", "wrong", "external"])
def test_evaluation_cli_verification_requires_external_pin(
    public_cli_case, capsys, trust
):
    root, pin = public_cli_case
    args = [
        "evaluation",
        "verify",
        "--app-root",
        str(root),
        "--receipt",
        "public-evaluation-receipt.json",
    ]
    if trust != "none":
        args += ["--trusted-receipt-sha256", pin if trust == "external" else "0" * 64]
    code, report = cli_json(capsys, args)
    assert code == (0 if trust == "external" else 1)
    assert report["status"] == ("pass" if trust == "external" else "fail")


@pytest.mark.parametrize(
    "command", ["promotion-dossier", "dossier", "promotion_dossier"]
)
@pytest.mark.parametrize("style", ["separate", "equals"])
def test_dossier_cli_external_pin_is_scoped(public_cli_case, capsys, command, style):
    root, pin = public_cli_case
    args = dossier_args(root, command=command)
    args += [PIN_OPTION, pin] if style == "separate" else [f"{PIN_OPTION}={pin}"]
    code, report = cli_json(capsys, args)
    assert code == 0
    assert report["decision"] == "promote"
    assert evaluation._TRUSTED_RECEIPT.get() is None
    code, report = cli_json(capsys, dossier_args(root, "unpinned-after-success"))
    assert code == 1
    assert report["decision"] == "block"
    assert "evaluation_verification_failed" in report["blockers"]


@pytest.mark.parametrize("trust", ["none", "wrong"])
def test_dossier_cli_no_pin_and_tampered_pin_fail_closed(
    public_cli_case, capsys, trust
):
    root, _ = public_cli_case
    args = dossier_args(root)
    if trust == "wrong":
        args += [PIN_OPTION, "0" * 64]
    code, report = cli_json(capsys, args)
    assert code == 1
    assert report["decision"] == "block"
    assert "evaluation_verification_failed" in report["blockers"]
    assert evaluation._TRUSTED_RECEIPT.get() is None


def test_dossier_cli_restores_prior_trust_after_real_backend_failure(public_cli_case):
    root, pin = public_cli_case
    args = dossier_args(root)
    args[1] = str(root / "absent-run-manifest.json")
    with evaluation.trusted_evaluation_receipt(root, "a" * 64):
        previous = evaluation._TRUSTED_RECEIPT.get()
        with pytest.raises(FileNotFoundError):
            lab_run.main([*args, PIN_OPTION, pin])
        assert evaluation._TRUSTED_RECEIPT.get() == previous
    assert evaluation._TRUSTED_RECEIPT.get() is None
    assert (
        evaluation.verify_evaluation_receipt(root, "public-evaluation-receipt.json")[
            "status"
        ]
        == "fail"
    )


@pytest.mark.parametrize(
    "problem",
    [
        "malformed",
        "uppercase",
        "duplicate",
        "no-value",
        "no-root",
        "no-receipt",
        "missing-root",
        "file-root",
    ],
)
def test_dossier_cli_pin_argument_errors_are_bounded(public_cli_case, capsys, problem):
    root, pin = public_cli_case
    args = dossier_args(root)
    pins = [PIN_OPTION, pin]
    if problem in {"malformed", "uppercase"}:
        pins[-1] = "invalid" if problem == "malformed" else "A" * 64
    elif problem == "duplicate":
        pins *= 2
    elif problem == "no-value":
        pins.pop()
    elif problem in {"no-root", "no-receipt"}:
        option = "--evaluation-root" if problem == "no-root" else "--evaluation-receipt"
        index = args.index(option)
        del args[index : index + 2]
    else:
        args[args.index("--evaluation-root") + 1] = str(
            root / ("missing-root" if problem == "missing-root" else "fixture.json")
        )
    with pytest.raises(SystemExit) as stopped:
        lab_run.main([*args, *pins])
    assert stopped.value.code == 2
    error = capsys.readouterr().err
    assert "error:" in error
    assert len(error) < 2500
    assert evaluation._TRUSTED_RECEIPT.get() is None
    assert not (root / "promotion").exists()


def test_dossier_cli_pin_is_bound_to_the_explicit_app_root(
    public_cli_case, tmp_path, capsys
):
    root, pin = public_cli_case
    other_parent = tmp_path / "other-app"
    other_parent.mkdir()
    other_root, _ = build_public_case(other_parent)
    args = dossier_args(root)
    args[args.index("--evaluation-root") + 1] = str(other_root)
    code, report = cli_json(capsys, [*args, PIN_OPTION, pin])
    assert code == 1
    assert report["decision"] == "block"
    assert "evaluation_verification_failed" in report["blockers"]
    assert evaluation._TRUSTED_RECEIPT.get() is None


@pytest.mark.parametrize("trust", ["external", "none", "inline"])
def test_serving_cli_uses_only_external_caller_trust(public_cli_case, capsys, trust):
    root, pin = public_cli_case
    code, _ = cli_json(capsys, [*dossier_args(root), PIN_OPTION, pin])
    assert code == 0
    (root / "serving-environment.json").write_text(
        json.dumps({"python": "3.13", "dependencies": [], "status": "declared"})
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
    if trust == "inline":
        spec["trusted_receipt_sha256"] = pin
    (root / "serving-spec.json").write_text(json.dumps(spec))
    args = [
        "serving-handoff",
        "export",
        "--app-root",
        str(root),
        "--handoff",
        "serving-handoff.json",
        "--spec",
        "serving-spec.json",
    ]
    if trust == "external":
        args += ["--trusted-receipt-sha256", pin]
    code, report = cli_json(capsys, args)
    assert code == (0 if trust == "external" else 1)
    assert report["deployment_status"] == "not_deployed"
    if trust == "external":
        code, report = cli_json(
            capsys,
            [
                "serving-handoff",
                "verify",
                "--app-root",
                str(root),
                "--handoff",
                "serving-handoff.json",
                "--trusted-receipt-sha256",
                pin,
            ],
        )
        assert code == 0
        assert report["status"] == "pass"
        handoff = json.loads((root / "serving-handoff.json").read_text())
        assert handoff["health_status"] == "not_observed"
        assert handoff["rollback_status"] == "not_executed"
    else:
        assert not (root / "serving-handoff.json").exists()
        if trust == "inline":
            assert "outside the serving spec" in report["reason"]


@pytest.mark.parametrize(
    ("command", "option"),
    [
        ("evaluation", "--execute-scorer"),
        ("serving-handoff", "--trusted-receipt-sha256"),
        ("capsule-attestation", "--refresh-trust-root"),
        ("promotion-dossier", PIN_OPTION),
    ],
)
def test_public_evidence_subcommand_help(command, option, capsys):
    with pytest.raises(SystemExit) as stopped:
        lab_run.main([command, "--help"])
    assert stopped.value.code == 0
    assert option in capsys.readouterr().out


def test_top_help_and_missing_extra_work_without_optional_packages(tmp_path):
    existing_paths = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, "-B", "-S", "-m", "agilab.lab_run"]
    help_result = subprocess.run(
        [*command, "--help"], env=env, capture_output=True, text=True, timeout=20
    )
    assert help_result.returncode == 0, help_result.stderr
    for name in (
        "first-proof",
        "promotion-dossier",
        "evaluation",
        "serving-handoff",
        "capsule-attestation",
        "workflow",
    ):
        assert name in help_result.stdout
    missing = subprocess.run(
        [
            *command,
            "capsule-attestation",
            "--app-root",
            str(tmp_path),
            "--artifact",
            "model.bin",
            "--bundle",
            "bundle.json",
            "--issuer",
            "https://issuer.invalid",
            "--identity",
            "observer@example.invalid",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert missing.returncode == 1, missing.stderr
    report = json.loads(missing.stdout)
    assert report["status"] == "unavailable"
    assert "sigstore>=4.5.1,<5" in report["reason"]
    assert {
        path.relative_to(tmp_path) for path in tmp_path.rglob("*")
    } == existing_paths


def test_capsule_extra_preserves_the_public_entrypoint():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["scripts"]["agilab"] == "agilab.lab_run:main"
    assert project["optional-dependencies"]["capsule-attestation"] == [
        "sigstore>=4.5.1,<5"
    ]
    assert all("sigstore" not in item for item in project["dependencies"])
