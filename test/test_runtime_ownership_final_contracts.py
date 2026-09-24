"""Observable task approval, locking and execution ownership failures."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agilab.agent_runtime import tasks, experiment
from test.test_agent_tasks import prepare, approve


@pytest.mark.parametrize("target", ["store", "lock"])
def test_task_store_rejects_linked_ownership_paths(tmp_path, target):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    if target == "store":
        with pytest.raises(ValueError, match="store cannot be a symlink"):
            tasks.TaskStore(link)
    else:
        file = real / "lock"
        file.touch()
        lock = tmp_path / "lock-link"
        lock.symlink_to(file)
        with pytest.raises(ValueError, match="locks cannot be symlinks"):
            with tasks._lease(lock):
                pytest.fail("linked lock acquired")


def test_task_lease_retries_busy_lock_and_unlocks_only_after_acquisition(tmp_path, monkeypatch):
    attempts = iter([False, False, True])
    delays, unlocked = [], []
    monkeypatch.setattr(tasks, "_try_lock_handle", lambda handle:next(attempts))
    monkeypatch.setattr(tasks, "_unlock_handle", lambda handle:unlocked.append(handle.closed))
    monkeypatch.setattr(tasks, "time", SimpleNamespace(monotonic=lambda:0, sleep=delays.append))
    with tasks._lease(tmp_path / "worker.lock", wait=True) as owned:
        assert owned
    assert delays == [0.02, 0.02]
    assert unlocked == [False]


def test_registered_action_cannot_be_rebound_to_another_frozen_experiment(tmp_path):
    store, state, plan, counter = prepare(tmp_path)
    root = store.root / "experiments/other"
    experiment.prepare_experiment(source_root=tmp_path / "source", output_dir=root,
        files=["candidate.py","grader.py","inputs.json"], entrypoint="candidate.py",
        grader="grader.py", outputs=["result.json"], checks=["finite_mean"])
    with pytest.raises(ValueError, match="already bound to another experiment"):
        store.register("demo", "experiments/other")
    assert store.status(state["task_id"]) == state
    assert not counter.exists()


def test_repeated_identical_approval_is_idempotent(tmp_path):
    store, state, plan, counter = prepare(tmp_path)
    approved = approve(store, state)
    assert approve(store, approved) == approved
    assert store.status(state["task_id"])["revision"] == approved["revision"]
    assert not counter.exists()


@pytest.mark.parametrize(("key", "value"), [
    ("plan_sha256", "0"*64), ("attempt_id", "other-attempt"), ("decision", "denied"),
])
def test_worker_rejects_approval_for_another_plan_attempt_or_decision(tmp_path, key, value):
    store, state, plan, counter = prepare(tmp_path)
    approved = approve(store, state)
    approval = dict(approved["approval"])
    approval[key] = value
    queued = store._save(approved, status="queued", approval=approval)
    with pytest.raises(PermissionError, match="exact plan and attempt"):
        store.work(state["task_id"], attempt=queued["attempt"])
    assert not counter.exists()
    assert store.status(state["task_id"]) == queued


def test_resume_refuses_live_worker_lease_without_changing_task(tmp_path):
    store, state, plan, counter = prepare(tmp_path)
    lock = store.path(f"tasks/{state['task_id']}/worker.lock")
    with tasks._lease(lock) as owned:
        assert owned
        with pytest.raises(RuntimeError, match="live worker"):
            store.continue_attempt(state["task_id"], attempt=1, retry=True)
    assert store.status(state["task_id"]) == state
    assert not counter.exists()


def test_reconcile_invalid_receipt_records_interruption_without_executing(tmp_path):
    store, state, plan, counter = prepare(tmp_path)
    approved = approve(store, state)
    running = store._save(approved, status="running", execution_started=True)
    receipt = store.root / "experiments/demo/attempts" / running["attempt_id"] / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text("{")
    result = store.reconcile(state["task_id"])
    assert result["status"] == "interrupted"
    assert result["error"]
    assert not counter.exists()


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "running"])
def test_start_does_not_launch_another_worker_for_terminal_or_running_task(tmp_path, monkeypatch, status):
    store, state, plan, counter = prepare(tmp_path)
    saved = store._save(state, status=status)
    monkeypatch.setattr(tasks.subprocess, "Popen", lambda *a, **k:pytest.fail("must not launch duplicate worker"))
    assert store.start(state["task_id"], attempt=state["attempt"]) == saved
    assert not counter.exists()


@pytest.mark.parametrize("artifact", ["agent_run_manifest.json", "stdout.txt", "stderr.txt", "agent_trace_meta.json", "agent_events.ndjson"])
def test_agent_output_with_existing_evidence_requires_new_directory(tmp_path, artifact):
    from agilab.agent_runtime import agent_run
    path = tmp_path / artifact
    path.write_text("prior evidence")
    config = SimpleNamespace(output_dir=tmp_path, run_id="new-run", agent="test")
    with pytest.raises(FileExistsError, match="contains evidence"):
        agent_run._claim_agent_run_output(config)
    assert path.read_text() == "prior evidence"
    assert not (tmp_path / agent_run.RUN_CLAIM_FILENAME).exists()


@pytest.mark.parametrize("phase", ["write", "fsync"])
def test_failed_claim_publication_closes_descriptor_and_retains_exclusive_claim(tmp_path, monkeypatch, phase):
    from agilab.agent_runtime import agent_run
    implementation = agent_run._claim_agent_run_output.__globals__
    real_os = implementation["os"]
    closed = []
    def fail(*args):
        raise OSError("claim publication failed")
    def close(fd):
        closed.append(fd)
        real_os.close(fd)
    class ClaimOS:
        def __getattr__(self, name):
            if name == phase:
                return fail
            if name == "close":
                return close
            return getattr(real_os, name)
    monkeypatch.setitem(implementation, "os", ClaimOS())
    config = SimpleNamespace(output_dir=tmp_path, run_id="new-run", agent="test")
    with pytest.raises(OSError, match="publication failed"):
        agent_run._claim_agent_run_output(config)
    assert len(closed) == 1
    assert (tmp_path / agent_run.RUN_CLAIM_FILENAME).exists()
    with pytest.raises(FileExistsError, match="already claimed"):
        agent_run._claim_agent_run_output(config)


def test_competing_claim_created_after_precheck_is_never_overwritten(tmp_path, monkeypatch):
    from agilab.agent_runtime import agent_run
    implementation = agent_run._claim_agent_run_output.__globals__
    real_os = implementation["os"]
    path = tmp_path / agent_run.RUN_CLAIM_FILENAME
    def raced_open(target, flags, mode):
        path.write_text("other owner")
        return real_os.open(target, flags, mode)
    class ClaimOS:
        def __getattr__(self, name):
            return raced_open if name == "open" else getattr(real_os, name)
    monkeypatch.setitem(implementation, "os", ClaimOS())
    with pytest.raises(FileExistsError, match="already claimed"):
        agent_run._claim_agent_run_output(SimpleNamespace(output_dir=tmp_path, run_id="run", agent="test"))
    assert path.read_text() == "other owner"


@pytest.mark.parametrize("failure", ["verifier_exit", "verifier_status", "empty_workflow", "workflow_exit"])
def test_notebook_build_never_promotes_failed_independent_verification(tmp_path, monkeypatch, failure):
    from agilab.agent_runtime import notebook_agent as module
    from test.test_notebook_agent import source_fixture
    monkeypatch.setattr(module, "fetch_source", source_fixture)
    monkeypatch.setattr(module.shutil, "which", lambda name:"/fake/tokki")
    def provider(config):
        notebook = {"nbformat":4, "cells":[] if failure == "empty_workflow" else [
            {"cell_type":"code", "source":"print('candidate')"}]}
        (config.cwd / "solution.ipynb").write_text(json.dumps(notebook))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module, "run_agent_command", provider)
    checks = []
    def verify(command, **kwargs):
        checks.append(command)
        if len(checks) == 1:
            return SimpleNamespace(returncode=1 if failure == "verifier_exit" else 0,
                stdout=json.dumps({"status":"failed" if failure == "verifier_status" else "passed",
                                   "result_file":"metrics.json", "result_sha256":"digest"}), stderr="diagnostic")
        return SimpleNamespace(returncode=1, stdout="", stderr="workflow did not agree")
    monkeypatch.setattr(module.subprocess, "run", verify)
    report = module.build(tmp_path)
    assert report["status"] == "failed"
    expected = {"verifier_exit":"Independent verification failed",
                "verifier_status":"Verifier did not report a pass",
                "empty_workflow":"no runnable workflow stages",
                "workflow_exit":"Imported workflow verification failed"}
    assert expected[failure] in report["error"]
    assert json.loads((tmp_path / "result.json").read_text()) == report
    assert module.read_events(tmp_path)[-1]["phase"] == "failed"
    assert len(checks) == (2 if failure == "workflow_exit" else 1)


def test_notebook_download_preserves_successful_stream_bytes(monkeypatch):
    import requests
    from agilab.agent_runtime import notebook_agent
    class Response:
        status_code = 200
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def raise_for_status(self):pass
        def iter_content(self, size):return iter([b"first", b"", b"second"])
    monkeypatch.setattr(requests, "get", lambda *a, **k:Response())
    assert notebook_agent._download_source("https://example.invalid/pinned.ipynb") == b"firstsecond"


@pytest.mark.parametrize("source_args", [["--notebook","local.ipynb"], ["--notebook-url","https://example.invalid/pinned.ipynb"]])
def test_notebook_ui_launcher_forwards_explicit_source_and_request(tmp_path, monkeypatch, source_args):
    from agilab.agent_runtime import notebook_agent
    calls = []
    monkeypatch.setattr(notebook_agent.subprocess, "call", lambda args:calls.append(args) or 0)
    assert notebook_agent.main(["--ui", "--request","inspect this notebook",
        "--output",str(tmp_path), *source_args]) == 0
    command = calls[0]
    assert command[command.index("--request")+1] == "inspect this notebook"
    expected = str(Path("local.ipynb").resolve()) if source_args[0] == "--notebook" else source_args[1]
    assert command[command.index(source_args[0])+1] == expected
    assert "--server.address=127.0.0.1" in command


def _contract_unit(name, *, produces=True):
    return {"id":name, "dispatch_status":"runnable",
            "execution_contract":{"entrypoint":"local.run"},
            "produces":[{"artifact":name + "_metrics", "kind":"summary_metrics", "path":"metrics.json"}] if produces else []}


def test_dag_batch_reports_successful_and_rejected_units_separately(tmp_path):
    from agilab.dag import dag_execution_adapters as module
    calls = []
    def run(**kwargs):
        calls.append(kwargs["idempotency_token"])
        return {"summary_metrics":{"stage_completed":1}, "summary_metrics_path":"metrics.json"}
    state = {"units":[_contract_unit("ready"), _contract_unit("invalid", produces=False)],
             "events":[], "artifacts":[], "summary":{}}
    context = module.DagExecutionContext(repo_root=tmp_path, lab_dir=tmp_path,
        execution_attempt_id="attempt", stage_run_fns={"ready":run},
        persist_execution_claim_fn=lambda state:module._DURABLE_CLAIM_RECEIPT)
    result = module._run_ready_adapter_stages_uncommitted("controlled_contract_dag", state, context)
    assert not result.ok
    assert result.executed_unit_ids == ("ready",)
    assert result.failed_unit_ids == ("invalid",)
    assert calls == ["attempt:ready"]
    assert "Executed" in result.message and "failed" in result.message
    assert state["units"][0]["dispatch_status"] == "runnable"


def test_dag_requires_attempt_identity_before_executing_or_persisting_claim(tmp_path):
    from agilab.dag import dag_execution_adapters as module
    state = {"units":[_contract_unit("ready")], "events":[], "artifacts":[]}
    context = module.DagExecutionContext(repo_root=tmp_path, lab_dir=tmp_path,
        stage_run_fns={"ready":lambda **kwargs:pytest.fail("must not execute")},
        persist_execution_claim_fn=lambda state:pytest.fail("must not claim"))
    with pytest.raises(RuntimeError, match="attempt"):
        module._run_next_adapter_stage_uncommitted("controlled_contract_dag", state, context)


def test_dag_artifact_directory_collision_fails_before_command_execution(tmp_path, monkeypatch):
    from agilab.dag import dag_execution_adapters as module
    unit = _contract_unit("ready")
    unit["execution_contract"] = {"command":"python -c pass"}
    output = module._real_run_root(tmp_path, "ready") / "metrics.json"
    output.mkdir(parents=True)
    sentinel = output / "operator-data"
    sentinel.write_text("keep")
    context = module.DagExecutionContext(repo_root=tmp_path, lab_dir=tmp_path,
        execution_attempt_id="attempt", persist_execution_claim_fn=lambda state:module._DURABLE_CLAIM_RECEIPT)
    monkeypatch.setitem(module._contract_stage_result_once.__globals__, "_run_contract_command",
                        lambda *a, **k:pytest.fail("must not execute"))
    with pytest.raises(RuntimeError, match="artifact path is a directory"):
        module._run_next_adapter_stage_uncommitted("controlled_contract_dag",
            {"units":[unit], "events":[], "artifacts":[]}, context)
    assert sentinel.read_text() == "keep"


def test_agent_context_cli_rejects_negative_limit_before_reading_root(tmp_path, capsys):
    from agilab.agent_runtime import agent_run
    with pytest.raises(SystemExit) as raised:
        agent_run.main(["context", "--root", str(tmp_path / "missing"), "--limit", "-1"])
    assert raised.value.code == 2
    assert "--limit must be >= 0" in capsys.readouterr().err


def test_task_worker_reserves_enough_revision_capacity_before_execution(tmp_path, monkeypatch):
    store, state, plan, counter = prepare(tmp_path)
    approved = approve(store, state)
    queued = store._save(approved, status="queued")
    monkeypatch.setattr(tasks, "MAX_REVISIONS", queued["revision"] + 4)
    with pytest.raises(ValueError, match="revision"):
        store.work(state["task_id"], attempt=state["attempt"])
    assert store.status(state["task_id"]) == queued
    assert not counter.exists()
