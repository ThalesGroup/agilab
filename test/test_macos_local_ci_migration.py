"""Regression contracts for current-host validation and local evidence."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from tools import agilab_dev, workflow_parity as parity
from tools.testing import local_validation_receipt as evidence
from tools.testing.setuptools_native_qualification import validate_native_case


@pytest.mark.parametrize(
    "name",
    [
        "ci.yml",
        "root-test-suite.yml",
        "windows-core-tests.yml",
        "coverage.yml",
        "docs-source-guard.yaml",
        "docs-publish.yaml",
        "ui-robot-matrix.yml",
    ],
)
def test_portable_validation_and_pages_are_explicit(name):
    workflow = yaml.safe_load((Path(".github/workflows") / name).read_text())
    assert set(workflow.get("on", workflow.get(True))) == {"workflow_dispatch"}


def test_current_host_entry_does_not_pull_heavy_qualifiers_into_default():
    args = parity._build_parser().parse_args([])
    assert parity._selected_profiles(args) == ["local"]
    commands = parity._profile_commands(args)["local"]
    assert commands
    argv = [arg for command in commands for arg in command.argv]
    assert "npm" not in argv and "brew" not in argv and "gh" not in argv
    assert (
        "coverage" not in argv
        and "--with" not in argv
        and "--with-editable" not in argv
    )
    assert "tools/sync_docs_source.py" in argv
    assert "--verify-target-integrity" in argv
    assert "--apply" not in argv
    planned = agilab_dev.planned_commands(
        ["ci", "--no-sync", "--receipt", "reports/local.json"]
    )[0]
    assert planned[planned.index("run") + 1] == "--no-sync"
    assert planned[-4:] == ["--profile", "local", "--receipt", "reports/local.json"]


def test_isolated_boundary_profiles_preserve_real_qualification():
    profiles = parity._profile_commands(parity._build_parser().parse_args([]))
    compat = profiles["base-python-compat"]
    assert {c.argv[c.argv.index("--python") + 1] for c in compat} == {"3.12", "3.14"}
    all_args = [arg for c in compat for arg in c.argv]
    assert "pillow==13.0.0" in all_args
    assert {"duckdb==1.4.0", "duckdb==2.0.0"} <= set(all_args)
    assert all("--isolated" in c.argv for c in compat)
    native = profiles["setuptools-native"]
    assert len(native) == 2
    assert {f"setuptools=={v}" for v in ("83.0.0", "84.2.1")} <= {
        a for c in native for a in c.argv
    }
    assert all(
        "tools.testing.setuptools_native_qualification" in c.argv for c in native
    )
    assert all(not any("GITHUB_" in value for value in c.env) for c in native)
    gui = profiles["agi-gui"][-1]
    assert "--rcfile=.coveragerc.agi-core" in gui.argv
    assert "--include=*/agi_node/*,*/agi_cluster/*,*/agi_env/*" in gui.argv
    assert gui.argv[-1] == "coverage-gui-observed-core.xml"
    assert profiles["agi-web"][0].argv[-1] == "src/agilab/lib/agi-web/test"
    assert "pytest==9.1.1" in profiles["agi-web"][0].argv


@pytest.mark.parametrize(
    "profile",
    [
        "agi-env",
        "agi-core-combined",
        "agi-node",
        "agi-cluster",
        "agi-gui",
        "agi-web",
        "coverage",
        "docs",
        "docs-guard",
        "public-install",
        "setuptools-native",
    ],
)
def test_artifact_profiles_never_reuse_success_cache(profile):
    args = SimpleNamespace(result_cache=True, no_result_cache=False, print_only=False)
    assert not parity._result_cache_enabled(args, parity._run_command, [profile])


def test_ui_failure_keeps_strict_diagnostics_manifests_and_aggregate():
    args = parity._build_parser().parse_args(["--profile", "ui-robot-matrix"])
    calls = []

    def runner(spec):
        calls.append(spec)
        return parity.CommandResult(
            spec.label,
            spec.argv,
            1 if len(calls) == 1 else 0,
            0.01,
            str(parity.REPO_ROOT),
            spec.env,
        )

    result = parity.run_profiles(["ui-robot-matrix"], args=args, runner=runner)
    assert not result[0].success
    assert calls[-1].label == "UI robot full matrix aggregate"
    robots = [c for c in calls if c.label.startswith("ui robot matrix (")]
    assert robots
    assert all(c.stdout_path.endswith("/summary.json") for c in robots)
    assert all(c.exit_code_path.endswith("/exit-code.txt") for c in robots)
    assert len(calls) == len(robots) * 3 + 1
    trends = [c for c in calls if c.label.startswith("UI robot strict trend")]
    assert all("--strict" in c.argv and "--strict-budget" in c.argv for c in trends)
    assert "--expected-apps" in calls[-1].argv and "--expected-shards" in calls[-1].argv


def test_timeout_records_failure_for_later_ui_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(parity, "REPO_ROOT", tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    monkeypatch.setattr(parity.subprocess, "run", timeout)
    spec = parity.CommandSpec(
        "timed out shard",
        ["probe"],
        stdout_path="shard/summary.json",
        exit_code_path="shard/exit-code.txt",
    )
    result = parity._run_command(spec)
    assert result.returncode == 124
    assert (tmp_path / "shard/exit-code.txt").read_text().strip() == "124"


@pytest.mark.parametrize("outcome", ["skipped", "failure", "error"])
def test_native_qualification_rejects_unevaluated_or_failed_compile(tmp_path, outcome):
    junit = tmp_path / "native.xml"
    junit.write_text(
        f"<testsuites><testsuite><testcase><{outcome}/></testcase></testsuite></testsuites>"
    )
    with pytest.raises(ValueError, match="executed, passing compilation"):
        validate_native_case(junit, 0)


def test_native_qualification_requires_sdk_selection_and_worker_hash(tmp_path):
    junit = tmp_path / "native.xml"
    junit.write_text(
        "<testsuites><testsuite><testcase><properties>"
        '<property name="sdk_selected_worker_module" value="uav_relay_queue_worker_cy"/>'
        f'<property name="compiled_worker_sha256" value="{"a" * 64}"/>'
        "</properties></testcase></testsuite></testsuites>"
    )
    assert validate_native_case(junit, 0)["compiled_worker_sha256"] == "a" * 64


@pytest.fixture
def local_receipt(tmp_path, monkeypatch):
    source = tmp_path / "input.py"
    source.write_text("print('source')\n")
    verifier = tmp_path / evidence.VERIFIER
    verifier.parent.mkdir(parents=True)
    verifier.write_text("verifier source")

    def snapshot(root):
        files = {
            "input.py": evidence.sha256(source),
            evidence.VERIFIER: evidence.sha256(verifier),
        }
        return {"head": "a" * 40, "files": files, "sha256": evidence.digest(files)}

    monkeypatch.setattr(evidence, "source_snapshot", snapshot)
    specs = [
        asdict(c)
        for c in parity._profile_commands(parity._build_parser().parse_args([]))[
            "docs-guard"
        ]
    ]
    for spec in specs:
        for name in spec["artifact_paths"]:
            artifact = tmp_path / name
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                "<testsuites><testsuite><testcase name='executed'/></testsuite></testsuites>"
            )
    commands = [
        asdict(
            parity.CommandResult(c["label"], c["argv"], 0, 1.0, str(tmp_path), c["env"])
        )
        for c in specs
    ]
    path = tmp_path / "receipt.json"
    evidence.write_receipt(
        path,
        root=tmp_path,
        before=snapshot(tmp_path),
        profiles=["docs-guard"],
        results=[
            {
                "profile": "docs-guard",
                "description": "fixture",
                "success": True,
                "commands": commands,
            }
        ],
        specs={"docs-guard": specs},
        started_at="2026-11-06T00:00:00+00:00",
    )
    return tmp_path, path, source


def test_local_receipt_binds_source_verifier_runtime_and_commands(local_receipt):
    root, path, source = local_receipt
    result = evidence.verify_receipt(path, root=root)
    assert result["status"] == "passed", result
    source.write_text("print('changed source')\n")
    assert evidence.verify_receipt(path, root=root)["status"] == "failed"


@pytest.mark.parametrize(
    "mutation", ["result", "plan", "runtime", "skip", "midrun", "digest"]
)
def test_local_receipt_rejects_stale_or_incomplete_success(local_receipt, mutation):
    root, path, _source = local_receipt
    payload = json.loads(path.read_text())
    expected_digest = evidence.sha256(path)
    if mutation == "result":
        payload["results"][0]["commands"][0]["returncode"] = 1
    elif mutation == "plan":
        payload["commands"]["docs-guard"][0]["argv"] = ["fake"]
        payload["results"][0]["commands"][0]["argv"] = ["fake"]
    elif mutation == "runtime":
        payload["runtime"].pop("executable_sha256")
    elif mutation == "skip":
        payload["profiles"]["docs-guard"] = "skipped"
    elif mutation == "midrun":
        payload["source_unchanged"] = False
    else:
        payload["status"] = "failed"
    path.write_text(json.dumps(payload))
    result = evidence.verify_receipt(
        path,
        root=root,
        expected_sha256=expected_digest if mutation == "digest" else None,
    )
    assert result["status"] == "failed"


def test_plan_only_cannot_produce_local_success_receipt(tmp_path):
    with pytest.raises(SystemExit):
        parity.main(
            [
                "--profile",
                "docs-guard",
                "--print-only",
                "--receipt",
                str(tmp_path / "proof.json"),
            ]
        )
    assert not (tmp_path / "proof.json").exists()


def test_missing_local_receipt_is_explicit(tmp_path):
    result = evidence.verify_receipt(tmp_path / "missing.json", root=tmp_path)
    assert result["status"] == "missing"


def test_release_proof_keeps_incomplete_local_profiles_missing(monkeypatch):
    from tools import release_proof_report as release

    monkeypatch.setattr(
        evidence,
        "verify_receipt",
        lambda *a, **k: {
            "status": "passed",
            "profiles": {"local-guardrails": "passed"},
            "failures": [],
        },
    )
    checks, replaced = release._local_validation_checks(
        [Path("fixture.json")], repo_root=parity.REPO_ROOT
    )
    assert "repo-guardrails" not in replaced
    check = next(row for row in checks if row["id"] == "local_repo-guardrails")
    assert check["status"] == "fail"
    assert "public-install" in check["details"]["missing_profiles"]
    assert "docs-publish" not in replaced


@pytest.mark.parametrize(
    "mutation",
    [
        "removed-artifacts",
        "wrong-size",
        "unknown-profile",
        "zero-tests",
        "all-skipped",
        "dependencies",
    ],
)
def test_receipt_rejects_omitted_artifacts_unknown_profiles_and_unexecuted_tests(
    local_receipt, mutation
):
    root, path, _source = local_receipt
    payload = json.loads(path.read_text())
    if mutation == "removed-artifacts":
        payload["artifacts"] = {}
    elif mutation == "wrong-size":
        next(iter(payload["artifacts"].values()))["size"] += 1
    elif mutation == "unknown-profile":
        payload["profiles"] = {"invented": "passed"}
        payload["results"][0]["profile"] = "invented"
        payload["commands"] = {"invented": payload["commands"]["docs-guard"]}
    elif mutation == "dependencies":
        payload["runtime"]["dependencies"][0][1] += "-changed"
    else:
        name = next(iter(payload["artifacts"]))
        (root / name).write_text(
            "<testsuites><testsuite/></testsuites>"
            if mutation == "zero-tests"
            else "<testsuites><testsuite><testcase><skipped/></testcase></testsuite></testsuites>"
        )
        payload["artifacts"][name] = {
            "sha256": evidence.sha256(root / name),
            "size": (root / name).stat().st_size,
        }
    path.write_text(json.dumps(payload))
    assert evidence.verify_receipt(path, root=root)["status"] == "failed"


def test_receipt_rejects_effective_configuration_drift(local_receipt, monkeypatch):
    root, path, _source = local_receipt
    monkeypatch.setenv("AGILAB_DISABLE_BACKGROUND_SERVICES", "different")
    result = evidence.verify_receipt(path, root=root)
    assert result["status"] == "failed"
    assert any("configuration" in failure for failure in result["failures"])


def test_receipt_rejects_artifact_symlink_before_reading_target(local_receipt):
    root, path, source = local_receipt
    payload = json.loads(path.read_text())
    name = next(iter(payload["artifacts"]))
    artifact = root / name
    artifact.unlink()
    artifact.symlink_to(source)
    assert evidence.verify_receipt(path, root=root)["status"] == "failed"


def test_public_install_environment_blocks_destination_and_interpreter_pollution(
    tmp_path,
):
    from tools.testing.public_install_qualification import public_install_environment

    original = {
        key: "/unrelated/live/environment"
        for key in (
            "PIP_TARGET",
            "PIP_PREFIX",
            "PIP_ROOT",
            "PIP_PYTHON",
            "PIP_USER",
            "PIP_CONFIG_FILE",
            "PIP_EXTRA_INDEX_URL",
            "PYTHONPATH",
            "PYTHONUSERBASE",
        )
    }
    original["PIP_CERT"] = "/trusted/certificate.pem"
    env = public_install_environment(tmp_path, original)
    for key in (
        "PIP_TARGET",
        "PIP_PREFIX",
        "PIP_ROOT",
        "PIP_PYTHON",
        "PIP_USER",
        "PIP_EXTRA_INDEX_URL",
        "PYTHONPATH",
        "PYTHONUSERBASE",
    ):
        assert key not in env
    assert env["PIP_CONFIG_FILE"] == __import__("os").devnull
    assert env["PIP_INDEX_URL"] == "https://pypi.org/simple"
    assert env["PIP_CERT"] == original["PIP_CERT"]
    assert env["HOME"] == str(tmp_path)
    assert original["PIP_TARGET"] == "/unrelated/live/environment"


def test_receipt_rejects_altered_execution_directory(local_receipt):
    root, path, _source = local_receipt
    payload = json.loads(path.read_text())
    payload["results"][0]["commands"][0]["cwd"] = str(root / "another-checkout")
    path.write_text(json.dumps(payload))
    result = evidence.verify_receipt(path, root=root)
    assert result["status"] == "failed"


def test_extended_guardrails_require_their_recovery_install_and_security_reports(
    tmp_path,
):
    specs = [
        asdict(spec)
        for spec in parity._profile_commands(parity._build_parser().parse_args([]))[
            "guardrails-extended"
        ]
    ]
    required = {name for spec in specs for name in spec["artifact_paths"]}
    assert {
        "robustness-matrix.json",
        "first-launch-robot.json",
        "security-hygiene.json",
        "test-results/supply-chain/base/requirements.txt",
        "test-results/supply-chain/base/pip-audit.json",
        "test-results/supply-chain/base/sbom-cyclonedx.json",
    } <= required
    for name in required:
        if any(c in name for c in "*?["):
            continue
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence")
    before = evidence.artifact_inventory({"guardrails-extended": specs}, tmp_path)
    assert all(record.get("status") != "missing" for record in before.values())
    (tmp_path / "security-hygiene.json").unlink()
    after = evidence.artifact_inventory({"guardrails-extended": specs}, tmp_path)
    assert before != after and after["security-hygiene.json"]["status"] == "missing"


@pytest.mark.parametrize(
    "junit",
    [
        "<testsuites><testsuite/></testsuites>",
        "<testsuites><testsuite><testcase><skipped/></testcase></testsuite></testsuites>",
    ],
)
def test_producer_and_cli_do_not_report_unexecuted_tests_as_passed(
    local_receipt, monkeypatch, junit
):
    root, path, _source = local_receipt
    payload = json.loads(path.read_text())
    for name in payload["artifacts"]:
        (root / name).write_text(junit)
    produced = evidence.write_receipt(
        path,
        root=root,
        before=evidence.source_snapshot(root),
        profiles=["docs-guard"],
        results=payload["results"],
        specs=payload["commands"],
        started_at=payload["started_at"],
        options=payload["options"],
    )
    assert produced["status"] == "failed"
    specs = [parity.CommandSpec(**spec) for spec in payload["commands"]["docs-guard"]]
    monkeypatch.setattr(parity, "REPO_ROOT", root)
    monkeypatch.setattr(parity, "_profile_commands", lambda args: {"docs-guard": specs})
    monkeypatch.setattr(
        parity.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0)
    )
    commands = [
        parity.CommandResult(**command) for command in payload["results"][0]["commands"]
    ]
    monkeypatch.setattr(
        parity,
        "run_profiles",
        lambda *a, **k: [parity.ProfileResult("docs-guard", "fixture", True, commands)],
    )
    target = root / "cli-receipt.json"
    assert parity.main(["--profile", "docs-guard", "--receipt", str(target)]) == 1
    assert json.loads(target.read_text())["status"] == "failed"
