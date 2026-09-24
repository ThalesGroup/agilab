"""Durable approvals and real command claims survive worker interruption."""

from concurrent.futures import ThreadPoolExecutor
import json
import shutil
import time

import pytest

from agilab.agent_runtime import experiment, tasks
from agilab.agent_runtime.experiment_demo import demo_source


def prepare(tmp_path, *, code=""):
    source = tmp_path / "source"
    shutil.copytree(demo_source(), source)
    counter = tmp_path / "executions.txt"
    path = source / "candidate.py"
    path.write_text(
        path.read_text()
        + f"\nwith Path({str(counter)!r}).open('a') as f: f.write('x')\n"
        + code
    )
    store = tasks.TaskStore(tmp_path / "store")
    plan = experiment.prepare_experiment(
        source_root=source,
        output_dir=store.root / "experiments/demo",
        files=["candidate.py", "grader.py", "inputs.json"],
        entrypoint="candidate.py",
        grader="grader.py",
        outputs=["result.json"],
        checks=["finite_mean", "missing_values_excluded"],
        timeout_seconds=5,
    )
    store.register("demo", "experiments/demo")
    state = store.submit("demo", "request-1")
    return store, state, plan, counter


def approve(store, state):
    return store.decide(
        state["task_id"],
        plan_sha256=state["plan_sha256"],
        attempt=state["attempt"],
        approve=True,
    )


def wait_finished(store, task_id):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        state = store.status(task_id)
        if state["status"] in tasks.TERMINAL | {"interrupted"}:
            return state
        time.sleep(0.02)
    store.cancel(task_id, attempt=store.status(task_id)["attempt"])
    raise AssertionError("Owned test worker did not finish within its timeout")


def test_idempotency_approval_and_real_worker_claim(tmp_path):
    store, state, plan, counter = prepare(tmp_path)
    assert store.submit("demo", "request-1") == state
    with pytest.raises(PermissionError):
        store.start(state["task_id"], attempt=1)
    assert store.work(state["task_id"], attempt=1)["status"] == "awaiting_approval"
    assert not counter.exists()
    with pytest.raises(ValueError, match="digest"):
        store.decide(state["task_id"], plan_sha256="0" * 64, attempt=1, approve=True)
    approved = approve(store, state)
    assert tasks.TaskStore(store.root).status(state["task_id"]) == approved
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda _: store.work(state["task_id"], attempt=1), range(2))
        )
    assert store.status(state["task_id"])["status"] == "completed"
    assert counter.read_text() == "x"
    assert any(result["status"] == "completed" for result in results)
    assert store.work(state["task_id"], attempt=1)["status"] == "completed"
    assert counter.read_text() == "x"
    assert store.status(state["task_id"])["receipt"]["sha256"]


def test_denial_and_queued_cancellation_are_sticky(tmp_path):
    store, state, _, counter = prepare(tmp_path)
    denied = store.decide(
        state["task_id"],
        plan_sha256=state["plan_sha256"],
        attempt=state["attempt"],
        approve=False,
    )
    assert store.work(state["task_id"], attempt=1) == denied
    pending = store.submit("demo", "request-2")
    cancelled = store.cancel(pending["task_id"], attempt=1)
    assert store.cancel(pending["task_id"], attempt=1) == cancelled
    with pytest.raises(ValueError):
        approve(store, pending)
    assert store.work(pending["task_id"], attempt=1)["status"] == "cancelled"
    assert not counter.exists()


def test_background_cancel_only_owns_its_worker(tmp_path):
    store, state, _, counter = prepare(tmp_path, code="import time\ntime.sleep(4)\n")
    approve(store, state)
    store.start(state["task_id"], attempt=1)
    deadline = time.monotonic() + 8
    while not counter.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert counter.exists()
    assert store.reconcile(state["task_id"])["status"] == "running"
    store.cancel(state["task_id"], attempt=1)
    finished = wait_finished(store, state["task_id"])
    assert finished["status"] == "cancelled"
    assert finished["cancel_requested"]
    assert finished["stopping_evidence"]["manifests"]
    assert counter.read_text() == "x"
    retried = store.continue_attempt(state["task_id"], attempt=1, retry=True)
    assert retried["stopping_evidence"] is None


def test_reconcile_published_receipt_without_reexecution(tmp_path, monkeypatch):
    store, state, _, counter = prepare(tmp_path)
    approve(store, state)
    save = store._save

    def lose_worker(state, **changes):
        if changes.get("status") in {"completed", "interrupted"}:
            raise OSError("worker lost after receipt publication")
        return save(state, **changes)

    monkeypatch.setattr(store, "_save", lose_worker)
    with pytest.raises(OSError):
        store.work(state["task_id"], attempt=1)
    monkeypatch.setattr(store, "_save", save)
    assert store.status(state["task_id"])["status"] == "running"
    recovered = tasks.TaskStore(store.root).reconcile(state["task_id"])
    assert recovered["status"] == "completed"
    assert counter.read_text() == "x"


def test_resume_completed_candidate_before_grader_claim(tmp_path, monkeypatch):
    store, state, _, counter = prepare(tmp_path)
    approve(store, state)
    run = experiment.run_agent_command

    def interrupt(config, **kwargs):
        if config.metadata["experiment_role"] == "grader":
            raise OSError("worker lost before grader claim")
        return run(config, **kwargs)

    monkeypatch.setattr(experiment, "run_agent_command", interrupt)
    assert store.work(state["task_id"], attempt=1)["status"] == "interrupted"
    monkeypatch.setattr(experiment, "run_agent_command", run)
    store.continue_attempt(state["task_id"], attempt=1, retry=False)
    assert store.work(state["task_id"], attempt=1)["status"] == "completed"
    assert counter.read_text() == "x"


def test_ambiguous_claim_requires_fresh_approved_attempt(tmp_path, monkeypatch):
    store, state, _, counter = prepare(tmp_path)
    approve(store, state)
    run = experiment.run_agent_command

    def interrupted_claim(config, **kwargs):
        config.output_dir.mkdir(parents=True)
        (config.output_dir / ".agent_run.claim.json").write_text("{}")
        raise OSError("worker lost after exclusive claim")

    monkeypatch.setattr(experiment, "run_agent_command", interrupted_claim)
    assert store.work(state["task_id"], attempt=1)["status"] == "interrupted"
    monkeypatch.setattr(experiment, "run_agent_command", run)
    store.continue_attempt(state["task_id"], attempt=1, retry=False)
    assert store.work(state["task_id"], attempt=1)["status"] == "interrupted"
    assert not counter.exists()
    retried = store.continue_attempt(state["task_id"], attempt=1, retry=True)
    assert retried["approval"] is None
    assert retried["attempt"] == 2
    with pytest.raises(ValueError, match="Approval attempt changed"):
        approve(store, state)
    assert store.status(state["task_id"])["status"] == "awaiting_approval"
    with pytest.raises(ValueError, match="Attempt changed"):
        store.continue_attempt(state["task_id"], attempt=1, retry=True)
    approve(store, retried)
    for method in (store.cancel, store.start, store.work):
        with pytest.raises(ValueError, match="Attempt changed"):
            method(state["task_id"], attempt=1)
    assert store.status(state["task_id"])["status"] == "queued"
    assert store.work(state["task_id"], attempt=2)["status"] == "completed"
    assert counter.read_text() == "x"
    assert (
        store.root
        / f"experiments/demo/attempts/{state['attempt_id']}/entrypoint/.agent_run.claim.json"
    ).exists()


def test_changed_plan_invalidates_registration_and_approval(tmp_path):
    store, state, plan, counter = prepare(tmp_path)
    approve(store, state)
    root = store.root / "experiments/demo"
    plan.pop("sha256")
    plan["arguments"] = ["different"]
    (root / "plan.json").write_text(json.dumps(experiment.seal(plan)))
    with pytest.raises(ValueError, match="Registered plan changed"):
        store.work(state["task_id"], attempt=1)
    assert not counter.exists()


def test_action_and_idempotency_confinement(tmp_path):
    store, state, _, _ = prepare(tmp_path)
    for action in ("../escape", "missing"):
        with pytest.raises((ValueError, FileNotFoundError)):
            store.submit(action, "other-request")
    with pytest.raises(ValueError):
        store.register("outside", "../source")
    store.register("alias", "experiments/demo")
    with pytest.raises(ValueError, match="already bound"):
        store.submit("alias", "request-1")
    assert store.actions()["actions"][0]["action_id"] == "alias"


@pytest.mark.parametrize("order", ["cancel-first", "reconcile-first", "resumed-queued"])
def test_dead_worker_does_not_prove_candidate_cancelled(tmp_path, order):
    import subprocess
    import sys

    late = tmp_path / "late-effect.txt"
    store, state, _, counter = prepare(
        tmp_path,
        # Publish the fixture's completion marker atomically: file creation can
        # become visible before write_text has written and closed its payload.
        code=(f"import time\ntime.sleep(0.8)\n"
              f"marker = Path({str(late)!r})\n"
              "pending = marker.with_suffix('.pending')\n"
              "pending.write_text('still ran')\n"
              "pending.replace(marker)\n"),
    )
    approve(store, state)
    command = [
        sys.executable,
        "-c",
        "import sys;sys.path.insert(0,sys.argv.pop(1));from agilab.agent_runtime.tasks import main;raise SystemExit(main())",
        str(tasks.Path(tasks.__file__).resolve().parents[2]),
        "worker",
        str(store.root),
        state["task_id"],
        "--attempt",
        "1",
    ]
    worker = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 8
        while not counter.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert counter.exists()
        worker.kill()  # This test owns this exact Popen process.
        worker.wait(timeout=5)
        if order == "cancel-first":
            store.cancel(state["task_id"], attempt=1)
            result = store.reconcile(state["task_id"])
        else:
            assert store.reconcile(state["task_id"])["status"] == "interrupted"
            if order == "resumed-queued":
                store.continue_attempt(state["task_id"], attempt=1, retry=False)
            result = store.cancel(state["task_id"], attempt=1)
        assert result["status"] == "interrupted"
        assert result["cancel_requested"] is True
        deadline = time.monotonic() + 5
        while not late.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert late.read_text() == "still ran"
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)
        # The owned fixture's candidate exits itself after its bounded delay.
        deadline = time.monotonic() + 5
        while counter.exists() and not late.exists() and time.monotonic() < deadline:
            time.sleep(0.02)

def test_cli_register_submit_approve_execute_and_inspect(tmp_path, capsys):
    store, state, _, counter = prepare(tmp_path)
    root = str(store.root)

    def call(*args):
        assert tasks.main(list(args)) == 0
        return json.loads(capsys.readouterr().out)

    registered = call("register", root, "cli-demo", "experiments/demo")
    assert registered["action_id"] == "cli-demo"
    actions = call("list", root)
    assert {row["action_id"] for row in actions["actions"]} == {"demo", "cli-demo"}
    submitted = call("submit", root, "demo", "request-1")
    assert submitted["task_id"] == state["task_id"]
    approved = call("approve", root, state["task_id"], "--plan-sha256", state["plan_sha256"], "--attempt", "1")
    assert approved["status"] == "queued"
    completed = call("worker", root, state["task_id"], "--attempt", "1")
    assert completed["status"] == "completed"
    assert counter.read_text() == "x"
    for command in ("status", "reconcile"):
        assert call(command, root, state["task_id"])["status"] == "completed"
    assert counter.read_text() == "x"


def test_cli_denial_retry_and_cancellation_require_fresh_attempt(tmp_path, capsys):
    store, state, _, counter = prepare(tmp_path)
    root, task_id = str(store.root), state["task_id"]
    assert tasks.main(["deny", root, task_id, "--plan-sha256", state["plan_sha256"], "--attempt", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "denied"
    assert tasks.main(["retry", root, task_id, "--attempt", "1"]) == 1
    assert "Only interrupted, failed or cancelled" in capsys.readouterr().err
    task_id = store.submit("demo", "cancel-and-retry")["task_id"]
    assert tasks.main(["cancel", root, task_id, "--attempt", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cancelled"
    assert tasks.main(["retry", root, task_id, "--attempt", "1"]) == 0
    retried = json.loads(capsys.readouterr().out)
    assert retried["status"] == "awaiting_approval" and retried["attempt"] == 2
    assert tasks.main(["cancel", root, task_id, "--attempt", "1"]) == 1
    assert capsys.readouterr().err
    assert store.status(task_id)["status"] == "awaiting_approval"
    assert tasks.main(["cancel", root, task_id, "--attempt", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "cancelled"
    assert not counter.exists()


def test_cli_resume_does_not_repeat_a_completed_candidate(tmp_path, monkeypatch, capsys):
    store, state, _, counter = prepare(tmp_path)
    approve(store, state)
    run = experiment.run_agent_command

    def interrupt(config, **kwargs):
        if config.metadata["experiment_role"] == "grader":
            raise OSError("interruption before grading")
        return run(config, **kwargs)

    monkeypatch.setattr(experiment, "run_agent_command", interrupt)
    assert store.work(state["task_id"], attempt=1)["status"] == "interrupted"
    monkeypatch.setattr(experiment, "run_agent_command", run)
    root, task_id = str(store.root), state["task_id"]
    assert tasks.main(["resume", root, task_id, "--attempt", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "queued"
    assert tasks.main(["worker", root, task_id, "--attempt", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
    assert counter.read_text() == "x"
