"""Provider-free recovery uses real native command and notebook/workflow evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import marshal
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest

from agilab.agent_runtime import notebook_agent as agent
from agilab.agent_runtime.agent_run import create_agent_run_config, run_agent_command
from agilab.agent_runtime.notebook_build_checkpoint import build_lock


@pytest.fixture
def builder(tmp_path, monkeypatch):
    original = tmp_path / "analysis.ipynb"
    original.write_text(
        json.dumps(
            {
                "nbformat": 4,
                "cells": [
                    {"cell_type": "code", "source": "answer = 42\n"},
                ],
            }
        )
    )
    root = agent.create_run(tmp_path / "runs")
    deliveries = []

    def deliver(config):
        deliveries.append(config)
        project = config.cwd
        (project / "helpers.py").write_text("ANSWER = 42\n")
        (project / "unused_helper.py").write_text("ORIGINAL = 1\n")
        (project / "solution.ipynb").write_text(
            json.dumps(
                {
                    "nbformat": 4,
                    "cells": [
                        {
                            "cell_type": "code",
                            "source": "import os\nfrom pathlib import Path\nimport json\n"
                            "if os.environ.get('AGILAB_RECOVERY_FIXTURE_FAIL') == '1':\n"
                            "    raise RuntimeError('temporary acceptance environment failure')\n"
                            "from helpers import ANSWER\n",
                        },
                        {
                            "cell_type": "code",
                            "source": "Path('results.json').write_text(json.dumps({'results': {'answer': ANSWER}}))\n",
                        },
                    ],
                }
            )
        )
        (project / "app.py").write_text(
            "import os\nfrom pathlib import Path\nfrom helpers import ANSWER\n"
            "from agi_web import python_ui as st\nst.title('Recovery fixture')\n"
            "if os.environ.get('AGILAB_RECOVERY_FIXTURE_MUTATE') == '1':\n"
            "    Path(__file__).with_name('unused_helper.py').write_text('ORIGINAL = 2\\n')\n"
            "if st.button('Run analysis'):\n    st.metric('Answer', ANSWER)\n"
        )
        (project / "pyproject.toml").write_text(
            '[project]\nname = "recovery-fixture"\nversion = "0.0.0"\n'
        )
        if original.parent.joinpath("poison_bytecode").exists():
            helper = project / "helpers.py"
            poisoned = compile("ANSWER = 99\n", str(helper), "exec")
            header = importlib.util.MAGIC_NUMBER + struct.pack(
                "<III",
                0,
                int(helper.stat().st_mtime),
                helper.stat().st_size,
            )
            bytecode = Path(importlib.util.cache_from_source(str(helper)))
            bytecode.parent.mkdir()
            bytecode.write_bytes(header + marshal.dumps(poisoned))
        # Delivery is deterministic, not a live LLM. Its actual subprocess
        # termination, trace and artifacts use the production evidence owner.
        return run_agent_command(
            create_agent_run_config(
                [sys.executable, "-c", "print('fixture code delivery completed')"],
                agent="notebook-recovery-fixture",
                cwd=project,
                output_dir=config.output_dir,
                timeout_seconds=30,
                permission_level="standard",
                metadata=config.metadata,
            )
        )

    monkeypatch.setattr(agent.shutil, "which", lambda _: sys.executable)
    monkeypatch.setattr(agent, "run_agent_command", deliver)
    return root, original, deliveries


def failed_build(builder, monkeypatch):
    root, original, deliveries = builder
    monkeypatch.setenv("AGILAB_RECOVERY_FIXTURE_FAIL", "1")
    report = agent.build(root, notebook=original)
    assert report["status"] == "failed", report
    assert report["failed_phase"] == "verify"
    assert report["recovery"]["eligible"], report
    assert len(deliveries) == 1
    return report


def test_recovery_runs_real_acceptance_without_regeneration_and_keeps_previous_evidence(
    builder, monkeypatch
):
    root, _, deliveries = builder
    previous = failed_build(builder, monkeypatch)
    previous_bytes = (root / "result.json").read_bytes()
    original_receipt = (root / "completion_receipt.json").read_bytes()
    original_log = (root / "verification.log").read_bytes()
    monkeypatch.delenv("AGILAB_RECOVERY_FIXTURE_FAIL")
    monkeypatch.setattr(
        agent, "run_agent_command", lambda _: pytest.fail("provider restarted")
    )
    monkeypatch.setattr(
        agent, "fetch_source", lambda *a, **k: pytest.fail("source refetched")
    )
    report = agent.recover_build(root)
    assert report["status"] == "passed", report
    assert len(deliveries) == 1
    attempt = root / report["recovery"]["attempt"]
    assert (
        attempt / "notebook_recovery_previous_result.json"
    ).read_bytes() == previous_bytes
    assert (
        attempt / "notebook_recovery_previous_receipt.json"
    ).read_bytes() == original_receipt
    assert (root / "verification.log").read_bytes() == original_log
    assert (attempt / "notebook_verification.log").is_file()
    assert (attempt / "notebook_workflow_verification.log").is_file()
    assert (
        report["verification"]["result_sha256"]
        == report["verification"]["workflow"]["result_sha256"]
    )
    assert (
        report["seconds"] == previous["seconds"] + report["recovery"]["active_seconds"]
    )
    assert agent.read_events(root)[-1]["phase"] == "ready"

    # A completed, sealed result is reused without changing duration or evidence.
    result_bytes = (root / "result.json").read_bytes()
    receipt_bytes = (root / "completion_receipt.json").read_bytes()
    monkeypatch.setattr(
        agent,
        "_verify_and_import",
        lambda *a, **k: pytest.fail("completed run executed again"),
    )
    assert agent.recover_build(root) == report
    assert (root / "result.json").read_bytes() == result_bytes
    assert (root / "completion_receipt.json").read_bytes() == receipt_bytes
    assert len(list((root / "notebook_recovery_attempts").iterdir())) == 1
    (root / "completion_receipt.json").write_text("changed receipt")
    refused = agent.recover_build(root)
    assert (
        refused["status"] == "failed"
        and "completion evidence changed" in refused["error"]
    )


def test_repeated_failed_recoveries_accumulate_active_duration_without_losing_attempts(
    builder, monkeypatch
):
    root, _, _ = builder
    original = failed_build(builder, monkeypatch)
    second = agent.recover_build(root)
    assert second["status"] == "failed" and second["failed_phase"] == "verify"
    assert second["recovery"]["eligible"]
    assert (
        second["seconds"] == original["seconds"] + second["recovery"]["active_seconds"]
    )
    monkeypatch.delenv("AGILAB_RECOVERY_FIXTURE_FAIL")
    third = agent.recover_build(root)
    assert third["status"] == "passed", third
    assert third["recovery"]["previous_active_seconds"] == second["seconds"]
    assert third["seconds"] == second["seconds"] + third["recovery"]["active_seconds"]
    attempts = list((root / "notebook_recovery_attempts").iterdir())
    assert len(attempts) == 2
    assert all((path / "notebook_recovery_result.json").is_file() for path in attempts)


@pytest.mark.parametrize(
    "relative",
    [
        "verify_app",
        "verify_workflow.py",
        "notebook_app_project/helpers.py",
        "notebook_app_project/source/original.ipynb",
        "agent/stdout.txt",
    ],
)
def test_changed_checkpoint_artifacts_refuse_before_code_and_preserve_outcome(
    builder, monkeypatch, relative
):
    root, _, _ = builder
    failed_build(builder, monkeypatch)
    previous = (root / "result.json").read_bytes()
    (root / relative).write_text("changed snapshot")
    monkeypatch.setattr(
        agent,
        "_verify_and_import",
        lambda *a, **k: pytest.fail("changed code executed"),
    )
    report = agent.recover_build(root)
    assert (
        report["status"] == "failed" and report["failed_phase"] == "recovery_preflight"
    )
    assert (root / "result.json").read_bytes() == previous
    assert not (root / "notebook_recovery_attempts").exists()


def test_missing_terminal_controller_result_cannot_infer_verifier_termination(
    builder, monkeypatch
):
    root, _, _ = builder
    failed_build(builder, monkeypatch)
    (root / "result.json").unlink()
    monkeypatch.setattr(
        agent,
        "_verify_and_import",
        lambda *a, **k: pytest.fail("unverified interruption executed"),
    )
    report = agent.recover_build(root)
    assert (
        report["status"] == "failed" and "termination is unverified" in report["error"]
    )
    assert not (root / "result.json").exists()


def test_interrupted_recovery_claim_blocks_another_attempt(builder, monkeypatch):
    root, _, _ = builder
    failed_build(builder, monkeypatch)
    previous = (root / "result.json").read_bytes()

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(agent, "_verify_and_import", interrupt)
    with pytest.raises(KeyboardInterrupt):
        agent.recover_build(root)
    assert (root / "result.json").read_bytes() == previous
    monkeypatch.setattr(
        agent,
        "_verify_and_import",
        lambda *a, **k: pytest.fail("second interrupted command started"),
    )
    refused = agent.recover_build(root)
    assert (
        refused["status"] == "failed"
        and "previous recovery attempt is incomplete" in refused["error"]
    )
    assert len(list((root / "notebook_recovery_attempts").iterdir())) == 1


def test_recovery_publication_gap_preserves_original_and_refuses_ambiguous_timing(
    builder, monkeypatch
):
    root, _, _ = builder
    failed_build(builder, monkeypatch)
    previous = (root / "result.json").read_bytes()
    monkeypatch.delenv("AGILAB_RECOVERY_FIXTURE_FAIL")

    def interrupted_publish(*args, **kwargs):
        raise RuntimeError("publication stopped before replacing original")

    monkeypatch.setattr(agent, "write_result", interrupted_publish)
    assert agent.recover_build(root)["status"] == "failed"
    assert (root / "result.json").read_bytes() == previous
    monkeypatch.setattr(
        agent,
        "_verify_and_import",
        lambda *a, **k: pytest.fail("ambiguous retry executed"),
    )
    refused = agent.recover_build(root)
    assert (
        refused["status"] == "failed"
        and "publication is incomplete" in refused["error"]
    )


def test_initial_build_cannot_publish_hashes_of_code_changed_after_verification(
    builder, monkeypatch
):
    root, original, _ = builder
    monkeypatch.setenv("AGILAB_RECOVERY_FIXTURE_MUTATE", "1")
    report = agent.build(root, notebook=original)
    assert report["status"] == "failed", report
    assert "generated project inventory changed" in report["error"]
    assert not report["recovery"]["eligible"]
    assert "ready" not in [event["phase"] for event in agent.read_events(root)]


def test_poisoned_project_bytecode_does_not_replace_frozen_source_during_recovery(
    builder, monkeypatch
):
    root, original, _ = builder
    (original.parent / "poison_bytecode").touch()
    failed_build(builder, monkeypatch)
    monkeypatch.delenv("AGILAB_RECOVERY_FIXTURE_FAIL")
    report = agent.recover_build(root)
    assert report["status"] == "passed", report
    expected = hashlib.sha256(b'{"results":{"answer":42}}').hexdigest()
    assert report["verification"]["result_sha256"] == expected
    assert report["verification"]["workflow"]["result_sha256"] == expected


def test_competing_build_or_recovery_cannot_replace_existing_outcome(
    builder, monkeypatch
):
    root, original, _ = builder
    failed_build(builder, monkeypatch)
    previous = (root / "result.json").read_bytes()
    with build_lock(root):
        assert agent.recover_build(root)["failed_phase"] == "recovery_preflight"
        assert agent.build(root, notebook=original)["failed_phase"] == "claim"
    assert (root / "result.json").read_bytes() == previous
    assert agent.build(root, notebook=original)["failed_phase"] == "claim"
    assert (root / "result.json").read_bytes() == previous


@pytest.mark.parametrize(
    "options",
    [
        ["--check"],
        ["--notebook", "source.ipynb"],
        ["--notebook-url", "https://example.invalid"],
        ["--request", "different"],
        ["--input-file", "data.csv=input.csv"],
    ],
)
@pytest.mark.parametrize("ui", [False, True])
def test_cli_rejects_changes_to_saved_recovery_context(options, ui, monkeypatch):
    monkeypatch.setattr(
        agent, "recover_build", lambda _: pytest.fail("invalid recovery started")
    )
    with pytest.raises(SystemExit) as error:
        agent.main(["--resume", "run", *(["--ui"] if ui else []), *options])
    assert error.value.code == 2


def test_resume_cli_uses_existing_run_without_create_or_tokki(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(agent, "create_run", lambda _: pytest.fail("new run created"))
    monkeypatch.setattr(agent.shutil, "which", lambda _: pytest.fail("provider lookup"))
    monkeypatch.setattr(
        agent, "recover_build", lambda path: called.append(path) or {"status": "passed"}
    )
    assert agent.main(["--resume", "/local/notebook-run"]) == 0
    assert called == [Path("/local/notebook-run")]
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


@pytest.fixture
def stopped_recovery(builder, monkeypatch):
    """Retain real provider evidence while stopping before generated code runs."""
    root, original, deliveries = builder

    def stop_before_execution(*args, progress, **kwargs):
        progress("verify", "Acceptance stopped before executing generated code")
        raise RuntimeError("acceptance environment unavailable")

    monkeypatch.setattr(agent, "_verify_and_import", stop_before_execution)
    report = agent.build(root, notebook=original)
    assert report["status"] == "failed" and report["failed_phase"] == "verify"
    assert report["recovery"]["eligible"]
    assert len(deliveries) == 1
    original_bytes = original.read_bytes()
    monkeypatch.setattr(
        agent, "run_agent_command", lambda *_: pytest.fail("provider restarted")
    )
    monkeypatch.setattr(
        agent, "fetch_source", lambda *a, **k: pytest.fail("source refetched")
    )
    monkeypatch.setattr(
        agent,
        "_verify_and_import",
        lambda *a, **k: pytest.fail("refused recovery executed generated code"),
    )
    return root, original, original_bytes, report, stop_before_execution


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("not_object", "not bound to this project"),
        ("other_project", "not bound to this project"),
        ("unsealed_success", "no verified completion binding"),
        ("running", "completed failure"),
        ("provider_failure", "completed failure"),
        ("boolean_duration", "duration is invalid"),
        ("string_duration", "duration is invalid"),
        ("nonfinite_duration", "duration is invalid"),
        ("duration_before_checkpoint", "duration is invalid"),
        ("missing_attempt_history", "recovery evidence is missing"),
    ],
)
def test_recovery_rejects_unbound_outcome_without_replacing_it(
    stopped_recovery, change, message
):
    root, original, original_bytes, previous, _ = stopped_recovery
    if change == "not_object":
        previous = []
    elif change == "other_project":
        previous["project"] = str(root / "another_project")
    elif change == "unsealed_success":
        previous["status"] = "passed"
    elif change == "running":
        previous["status"] = "running"
    elif change == "provider_failure":
        previous["failed_phase"] = "build"
    elif change == "boolean_duration":
        previous["seconds"] = True
    elif change == "string_duration":
        previous["seconds"] = "1"
    elif change == "nonfinite_duration":
        previous["seconds"] = float("inf")
    elif change == "duration_before_checkpoint":
        previous["seconds"] = -1
    elif change == "missing_attempt_history":
        previous["recovery"]["attempt"] = "notebook_recovery_attempts/missing"
    outcome = root / "result.json"
    outcome.write_text(json.dumps(previous))
    previous_bytes = outcome.read_bytes()
    receipt_bytes = (root / "completion_receipt.json").read_bytes()

    refused = agent.recover_build(root)

    assert refused["failed_phase"] == "recovery_preflight"
    assert message in refused["error"]
    assert not refused["recovery"]["eligible"]
    assert outcome.read_bytes() == previous_bytes
    assert (root / "completion_receipt.json").read_bytes() == receipt_bytes
    assert original.read_bytes() == original_bytes
    assert not (root / "notebook_recovery_attempts").exists()


@pytest.mark.parametrize(
    "unsafe_path", ["receipt_link", "receipt_directory", "attempts_link"]
)
def test_recovery_refuses_nonregular_evidence_without_following_it(
    stopped_recovery, tmp_path, unsafe_path
):
    root, original, original_bytes, _, _ = stopped_recovery
    previous_bytes = (root / "result.json").read_bytes()
    outside = tmp_path / "unrelated-evidence"
    outside.mkdir()
    sentinel = outside / "must-stay-unchanged.txt"
    sentinel.write_text("unrelated user evidence")
    if unsafe_path.startswith("receipt"):
        receipt = root / "completion_receipt.json"
        receipt.unlink()
        if unsafe_path == "receipt_link":
            receipt.symlink_to(sentinel)
        else:
            receipt.mkdir()
        message = "completion receipt is not a regular file"
    else:
        (root / "notebook_recovery_attempts").symlink_to(
            outside, target_is_directory=True
        )
        message = "directory escapes the run"

    refused = agent.recover_build(root)

    assert refused["failed_phase"] == "recovery_preflight"
    assert message in refused["error"]
    assert (root / "result.json").read_bytes() == previous_bytes
    assert sentinel.read_text() == "unrelated user evidence"
    assert list(outside.iterdir()) == [sentinel]
    assert original.read_bytes() == original_bytes


@pytest.fixture
def completed_failed_recovery(stopped_recovery, monkeypatch):
    root, original, original_bytes, _, stop_before_execution = stopped_recovery
    with monkeypatch.context() as patch:
        patch.setattr(agent, "_verify_and_import", stop_before_execution)
        report = agent.recover_build(root)
    assert report["status"] == "failed" and report["failed_phase"] == "verify"
    assert report["recovery"]["eligible"]
    attempt = root / report["recovery"]["attempt"]
    assert (attempt / "notebook_recovery_result.json").is_file()
    return root, original, original_bytes, attempt


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("unsafe_name", "unsafe attempt directory"),
        ("unexpected_file", "unsafe attempt directory"),
        ("linked_attempt", "unsafe attempt directory"),
        ("missing_claim", "attempt is incomplete"),
        ("linked_terminal", "attempt is incomplete"),
        ("claim_schema", "terminal evidence is inconsistent"),
        ("claim_attempt", "terminal evidence is inconsistent"),
        ("checkpoint_digest", "terminal evidence is inconsistent"),
        ("previous_digest", "terminal evidence is inconsistent"),
        ("terminal_schema", "terminal evidence is inconsistent"),
        ("terminal_status", "terminal evidence is inconsistent"),
        ("terminal_recovery_type", "terminal evidence is inconsistent"),
        ("attempt_binding", "timing or attempt binding is invalid"),
        ("claim_binding", "timing or attempt binding is invalid"),
        ("boolean_prior", "timing or attempt binding is invalid"),
        ("negative_prior", "timing or attempt binding is invalid"),
        ("nonfinite_prior", "timing or attempt binding is invalid"),
        ("boolean_active", "timing or attempt binding is invalid"),
        ("negative_active", "timing or attempt binding is invalid"),
        ("nonfinite_active", "timing or attempt binding is invalid"),
        ("previous_seconds", "timing or attempt binding is invalid"),
        ("total_seconds", "timing or attempt binding is invalid"),
    ],
)
def test_recovery_refuses_corrupt_attempt_history_before_retrying(
    completed_failed_recovery, change, message
):
    root, original, original_bytes, attempt = completed_failed_recovery
    previous_bytes = (root / "result.json").read_bytes()
    receipt_bytes = (root / "completion_receipt.json").read_bytes()
    claim_path = attempt / "notebook_recovery_attempt.json"
    terminal_path = attempt / "notebook_recovery_result.json"
    claim = json.loads(claim_path.read_text())
    terminal = json.loads(terminal_path.read_text())
    if change == "unsafe_name":
        attempt.rename(attempt.with_name(".unsafe-attempt"))
    elif change == "unexpected_file":
        (attempt.parent / "unexpected-file").write_text("not an attempt directory")
    elif change == "linked_attempt":
        (attempt.parent / "linked-attempt").symlink_to(
            attempt, target_is_directory=True
        )
    elif change == "missing_claim":
        claim_path.unlink()
    elif change == "linked_terminal":
        terminal_path.unlink()
        terminal_path.symlink_to(root / "result.json")
    else:
        if change == "claim_schema":
            claim["schema"] = "unrecognized"
        elif change == "claim_attempt":
            claim["attempt"] = "another-attempt"
        elif change == "checkpoint_digest":
            claim["checkpoint_sha256"] = "0" * 64
        elif change == "previous_digest":
            claim["previous_result_sha256"] = "0" * 64
        elif change == "terminal_schema":
            terminal["recovery_schema"] = "unrecognized"
        elif change == "terminal_status":
            terminal["status"] = "running"
        elif change == "terminal_recovery_type":
            terminal["recovery"] = []
        elif change == "attempt_binding":
            terminal["recovery"]["attempt"] = "another-attempt"
        elif change == "claim_binding":
            terminal["recovery"]["claim_sha256"] = "0" * 64
        elif change in {"boolean_prior", "negative_prior", "nonfinite_prior"}:
            claim["previous_active_seconds"] = {
                "boolean_prior": True,
                "negative_prior": -1,
                "nonfinite_prior": float("nan"),
            }[change]
        elif change in {"boolean_active", "negative_active", "nonfinite_active"}:
            terminal["recovery"]["active_seconds"] = {
                "boolean_active": True,
                "negative_active": -1,
                "nonfinite_active": float("inf"),
            }[change]
        elif change == "previous_seconds":
            terminal["recovery"]["previous_active_seconds"] += 1
        elif change == "total_seconds":
            terminal["seconds"] += 1
        claim_path.write_text(json.dumps(claim))
        if change != "claim_binding" and isinstance(terminal["recovery"], dict):
            terminal["recovery"]["claim_sha256"] = agent.digest(claim_path)
        terminal_path.write_text(json.dumps(terminal))

    refused = agent.recover_build(root)

    assert refused["failed_phase"] == "recovery_preflight"
    assert message in refused["error"]
    assert not refused["recovery"]["eligible"]
    assert (root / "result.json").read_bytes() == previous_bytes
    assert (root / "completion_receipt.json").read_bytes() == receipt_bytes
    assert original.read_bytes() == original_bytes


@pytest.mark.parametrize("with_attempt", [False, True])
def test_failed_completion_binding_preserves_success_but_disables_recovery(
    stopped_recovery, monkeypatch, with_attempt
):
    root, original, original_bytes, report, _ = stopped_recovery
    checkpoint = agent.load_checkpoint(root)
    project = Path(report["project"])
    for relative in (
        "lab_stages.toml",
        "notebook_import.json",
        "results.json",
        "metrics.json",
    ):
        (project / relative).write_text("verified fixture evidence")
    for relative in ("verification.log", "workflow_verification.log"):
        (root / relative).write_text("verification completed")
    attempt = root / "publish-attempt" if with_attempt else None
    if attempt is not None:
        attempt.mkdir()
        (attempt / "notebook_recovery_attempt.json").write_text("attempt evidence")
    report.update(
        status="passed",
        recovery={"eligible": True},
        verification_logs={
            "app": "verification.log",
            "workflow": "workflow_verification.log",
        },
    )
    sealed = []

    def unavailable_completion_binding(run, files):
        sealed.append((run, files))
        raise OSError("completion inventory unavailable")

    monkeypatch.setattr(agent, "seal_completion", unavailable_completion_binding)

    agent._publish_result(root, report, checkpoint, attempt)

    assert report["status"] == "passed"
    assert not report["recovery"]["eligible"]
    assert "completion inventory unavailable" in report["recovery"]["reason"]
    assert json.loads((root / "result.json").read_text()) == report
    assert sealed[0][0] == root
    assert {
        "notebook_app_project/results.json",
        "notebook_app_project/metrics.json",
    }.issubset(sealed[0][1])
    if attempt is not None:
        assert (
            json.loads((attempt / "notebook_recovery_result.json").read_text())
            == report
        )
        assert "publish-attempt/notebook_recovery_attempt.json" in sealed[0][1]
    assert original.read_bytes() == original_bytes


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("app_status", "Verifier did not report a pass"),
        ("empty_workflow", "no runnable workflow stages"),
        ("workflow_exit", "Imported workflow verification failed"),
        ("workflow_status", "not bound to the persisted stages"),
        ("workflow_schema", "not bound to the persisted stages"),
        ("workflow_result", "not bound to the persisted stages"),
        ("workflow_stages", "not bound to the persisted stages"),
    ],
)
def test_acceptance_rejects_unbound_verifier_outcomes_before_ready(
    tmp_path, monkeypatch, fault, message
):
    root = tmp_path / "acceptance-run"
    project = root / "notebook_app_project"
    project.mkdir(parents=True)
    original = project / "original-source.ipynb"
    original.write_text("original notebook must stay unchanged")
    (root / "verify_app").write_text("application verifier")
    (root / "verify_workflow.py").write_text("workflow verifier")
    solution = {
        "nbformat": 4,
        "cells": [{"cell_type": "code", "source": "answer = 42\n"}],
    }
    if fault == "empty_workflow":
        solution["cells"] = []
    (project / "solution.ipynb").write_text(json.dumps(solution))
    protected = {
        path.relative_to(root).as_posix(): agent.digest(path)
        for path in (original, root / "verify_app", root / "verify_workflow.py")
    }
    phases = []
    calls = []
    result_digest = hashlib.sha256(b"notebook result").hexdigest()

    def verify(command, selected_project):
        calls.append(command)
        assert selected_project == project
        if len(calls) == 1:
            payload = {
                "status": "failed" if fault == "app_status" else "passed",
                "result_file": "results.json",
                "result_sha256": result_digest,
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        assert len(calls) == 2
        payload = {
            "status": "passed",
            "schema": "agilab.notebook_workflow_verification.v1",
            "result_sha256": result_digest,
            "stages_sha256": agent.digest(project / "lab_stages.toml"),
        }
        if fault == "workflow_status":
            payload["status"] = "failed"
        elif fault == "workflow_schema":
            payload["schema"] = "unrecognized"
        elif fault == "workflow_result":
            payload["result_sha256"] = "0" * 64
        elif fault == "workflow_stages":
            payload["stages_sha256"] = "0" * 64
        return SimpleNamespace(
            returncode=1 if fault == "workflow_exit" else 0,
            stdout=json.dumps(payload),
            stderr="workflow process failed" if fault == "workflow_exit" else "",
        )

    monkeypatch.setattr(agent, "_run_verifier", verify)
    with pytest.raises(RuntimeError, match=message):
        agent._verify_and_import(
            root,
            project,
            provenance={"source_kind": "local"},
            prerequisites=None,
            scope=agent.GENERIC_SCOPE,
            protected=protected,
            progress=lambda phase, _: phases.append(phase),
        )
    assert "ready" not in phases
    assert not (root / "result.json").exists()
    assert original.read_text() == "original notebook must stay unchanged"
    assert all(
        agent.digest(root / relative) == expected
        for relative, expected in protected.items()
    )
    assert len(calls) == (1 if fault in {"app_status", "empty_workflow"} else 2)
