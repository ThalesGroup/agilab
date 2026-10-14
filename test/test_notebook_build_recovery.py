"""Provider-free recovery uses real native command and notebook/workflow evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import marshal
from pathlib import Path
import struct
import sys

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
        ["--ui"],
        ["--check"],
        ["--notebook", "source.ipynb"],
        ["--notebook-url", "https://example.invalid"],
        ["--request", "different"],
        ["--input-file", "data.csv=input.csv"],
    ],
)
def test_cli_rejects_changes_to_saved_recovery_context(options, monkeypatch):
    monkeypatch.setattr(
        agent, "recover_build", lambda _: pytest.fail("invalid recovery started")
    )
    with pytest.raises(SystemExit) as error:
        agent.main(["--resume", "run", *options])
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
