"""Durable local tasks for operator-registered, source-bound experiments.

This is a trusted local store, not a sandbox or an authentication service. MCP
may select registered actions; only the local API/CLI records approval. Immutable
state revisions, native claims and kernel leases preserve interruption evidence.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from agilab.agent_runtime.agent_trace import _try_lock_handle, _unlock_handle, utc_now
from agilab.agent_runtime.experiment import (
    _native_result,
    check_seal,
    confined,
    execute_experiment,
    file_record,
    load_plan,
    read_json,
    seal,
    verify_experiment,
)
from agilab.evidence.evidence_contract import sha256_payload
from agilab.evidence.skill_evaluation import persist_evaluation
from agilab.security.secret_uri import redact_text

STATE_SCHEMA = "agilab.agent_task.v1"
ACTION_SCHEMA = "agilab.agent_task_action.v1"
TERMINAL = {"completed", "failed", "cancelled", "denied"}
MAX_REVISIONS = 512


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("Expected an ASCII identifier of 1-80 letters, digits, _ or -")
    return value


@contextmanager
def _lease(path: Path, *, wait: bool = False):
    """Lock a stable inode; never unlink a lock or infer ownership from a PID."""
    if path.is_symlink():
        raise ValueError("Task locks cannot be symlinks")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        deadline = time.monotonic() + (5 if wait else 0)
        locked = _try_lock_handle(handle)
        while not locked and time.monotonic() < deadline:
            time.sleep(0.02)
            locked = _try_lock_handle(handle)
        try:
            yield locked
        finally:
            if locked:
                _unlock_handle(handle)


class TaskStore:
    """The store and its registered experiment directories are operator-owned."""

    def __init__(self, root: Path):
        if Path(root).is_symlink():
            raise ValueError("Task store cannot be a symlink")
        self.root = Path(root).resolve()

    def path(self, relative: str) -> Path:
        return confined(self.root, relative)

    @contextmanager
    def locked(self):
        with _lease(self.path("store.lock"), wait=True) as locked:
            if not locked:
                raise TimeoutError("Task store is busy; retry the same operation")
            yield

    def _action(self, action_id):
        action = read_json(self.path(f"actions/{identifier(action_id)}.json"))
        check_seal(action, ACTION_SCHEMA)
        if action["action_id"] != action_id:
            raise ValueError("Registered action identity changed")
        root = self.path(action["experiment"])
        plan = load_plan(root)
        if plan["sha256"] != action["plan_sha256"]:
            raise ValueError("Registered plan changed; register a new action")
        return action, root

    def register(self, action_id: str, experiment: str):
        """Register an already prepared experiment below this store, once."""
        identifier(action_id)
        if not experiment.startswith("experiments/"):
            raise ValueError(
                "Prepare the experiment under this store's experiments/ directory"
            )
        root = self.path(experiment)
        plan = load_plan(root)
        action = seal(
            {
                "schema": ACTION_SCHEMA,
                "action_id": action_id,
                "experiment": experiment,
                "plan_sha256": plan["sha256"],
                "created_at": utc_now(),
                "producer": "agilab.agent_runtime.tasks register",
            }
        )
        with self.locked():
            destination = self.path(f"actions/{action_id}.json")
            if destination.exists():
                existing, _ = self._action(action_id)
                if (
                    existing["experiment"] != experiment
                    or existing["plan_sha256"] != plan["sha256"]
                ):
                    raise ValueError("Action id is already bound to another experiment")
                return existing
            persist_evaluation(self.root, destination, action)
        return action

    def actions(self, *, offset: int = 0, limit: int = 20):
        if (
            type(offset) is not int
            or not 0 <= offset <= 100000
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ValueError("Invalid action page bounds")
        paths = sorted(self.path("actions").glob("*.json"))
        rows = []
        for path in paths[offset : offset + limit]:
            action, _ = self._action(path.stem)
            rows.append(
                {"action_id": action["action_id"], "plan_sha256": action["plan_sha256"]}
            )
        next_offset = offset + len(rows)
        return {
            "schema": "agilab.agent_task_actions.v1",
            "actions": rows,
            "next_offset": next_offset
            if next_offset < min(len(paths), 100000)
            else None,
            "truncated": len(paths) > 100000,
        }

    def _load(self, task_id):
        directory = self.path(f"tasks/{identifier(task_id)}/states")
        paths = sorted(directory.glob("*.json"))
        if not paths:
            raise FileNotFoundError("Unknown task id")
        if len(paths) > MAX_REVISIONS:
            raise ValueError("Task revision limit exceeded")
        state = read_json(confined(directory, paths[-1].name))
        check_seal(state, STATE_SCHEMA)
        if state["task_id"] != task_id or paths[-1].stem != f"{state['revision']:04d}":
            raise ValueError("Task state identity mismatch")
        return state

    def _save(self, state, **changes):
        revision = state["revision"] + 1
        if revision >= MAX_REVISIONS:
            raise ValueError("Task revision limit reached; create a new task")
        payload = {k: v for k, v in state.items() if k != "sha256"}
        payload.update(changes)
        payload.update(
            revision=revision, updated_at=utc_now(), previous_sha256=state.get("sha256")
        )
        result = seal(payload)
        persist_evaluation(
            self.root, f"tasks/{state['task_id']}/states/{revision:04d}.json", result
        )
        return result

    def submit(self, action_id: str, idempotency_key: str):
        """A request key names one task forever; reuse with a different plan fails."""
        identifier(idempotency_key)
        with self.locked():
            action, _ = self._action(action_id)
            task_id = sha256_payload({"request": idempotency_key})[:32]
            try:
                existing = self._load(task_id)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if (
                    existing["action_id"] != action_id
                    or existing["plan_sha256"] != action["plan_sha256"]
                ):
                    raise ValueError(
                        "Idempotency key is already bound to another action"
                    )
                return existing
            return self._save(
                {
                    "schema": STATE_SCHEMA,
                    "task_id": task_id,
                    "revision": -1,
                    "producer": "agilab.agent_runtime.tasks",
                    "created_at": utc_now(),
                    "action_id": action_id,
                    "plan_sha256": action["plan_sha256"],
                    "attempt": 1,
                    "attempt_id": f"task-{task_id}-1",
                    "status": "awaiting_approval",
                    "approval": None,
                    "cancel_requested": False,
                    "execution_started": False,
                    "stopping_evidence": None,
                    "receipt": None,
                    "error": None,
                }
            )

    def decide(self, task_id: str, *, plan_sha256: str, attempt: int, approve: bool):
        """Local operator decision for this exact plan and attempt, never an MCP tool."""
        with self.locked():
            state = self._load(task_id)
            if type(attempt) is not int or attempt != state["attempt"]:
                raise ValueError("Approval attempt changed; inspect the current task")
            action, _ = self._action(state["action_id"])
            if (
                plan_sha256 != state["plan_sha256"]
                or plan_sha256 != action["plan_sha256"]
            ):
                raise ValueError("Approval does not match the selected plan digest")
            decision = "approved" if approve else "denied"
            if state["approval"] and state["approval"]["decision"] == decision:
                return state
            if state["status"] != "awaiting_approval" or state["cancel_requested"]:
                raise ValueError(
                    "Only a pending, uncancelled attempt can receive a decision"
                )
            approval = {
                "decision": decision,
                "plan_sha256": plan_sha256,
                "attempt_id": state["attempt_id"],
                "recorded_at": utc_now(),
                "authority": "local operator API/CLI; identity not attested",
            }
            return self._save(
                state, approval=approval, status="queued" if approve else "denied"
            )

    def cancel(self, task_id, *, attempt: int):
        with self.locked():
            state = self._load(task_id)
            _check_attempt(state, attempt)
            if state["status"] in TERMINAL or state["cancel_requested"]:
                return state
            return self._save(
                state,
                cancel_requested=True,
                status="running"
                if state["status"] == "running"
                else "interrupted"
                if state["execution_started"]
                else "cancelled",
            )

    def status(self, task_id):
        # Read-only: status never resumes, reconciles or executes a command.
        return self._load(task_id)

    def _approved_root(self, state):
        action, root = self._action(state["action_id"])
        approval = state["approval"] or {}
        if (
            action["plan_sha256"] != state["plan_sha256"]
            or approval.get("plan_sha256") != state["plan_sha256"]
            or approval.get("attempt_id") != state["attempt_id"]
            or approval.get("decision") != "approved"
        ):
            raise PermissionError("This exact plan and attempt need local approval")
        return root

    def _finish(self, state, root, receipt):
        relative = f"attempts/{state['attempt_id']}/receipt.json"
        verify_experiment(root, relative)
        return self._save(
            state,
            status="cancelled"
            if state["cancel_requested"]
            else "completed"
            if receipt["status"] == "passed"
            else "failed",
            receipt={
                "experiment": root.relative_to(self.root).as_posix(),
                **file_record(root, relative),
            },
            error=None,
        )

    def reconcile(self, task_id):
        """Resolve a departed worker from evidence, without executing anything."""
        with _lease(self.path(f"tasks/{identifier(task_id)}/worker.lock")) as owner:
            with self.locked():
                state = self._load(task_id)
                if not owner or state["status"] != "running":
                    return state
                try:
                    root = self._approved_root(state)
                    receipt = root / "attempts" / state["attempt_id"] / "receipt.json"
                    if receipt.exists():
                        return self._finish(state, root, read_json(receipt))
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    return self._save(state, status="interrupted", error=_error(exc))
                return self._save(
                    state,
                    status="interrupted",
                    error="Worker lease released without a receipt; command termination is unverified. Inspect side effects before explicit resume or a newly approved retry",
                )

    def continue_attempt(self, task_id, *, attempt: int, retry: bool):
        """Explicit resume or fresh retry. A retry always requires fresh approval."""
        with _lease(self.path(f"tasks/{identifier(task_id)}/worker.lock")) as owner:
            if not owner:
                raise RuntimeError("Task still has a live worker")
            with self.locked():
                state = self._load(task_id)
                if type(attempt) is not int or attempt != state["attempt"]:
                    raise ValueError(
                        "Attempt changed; inspect the task before continuing"
                    )
                if state["status"] not in {"interrupted", "failed", "cancelled"}:
                    raise ValueError(
                        "Only interrupted, failed or cancelled tasks can continue"
                    )
                self._action(state["action_id"])
                if not retry:
                    if state["status"] != "interrupted" or state["cancel_requested"]:
                        raise ValueError(
                            "Only an uncancelled interrupted attempt can resume"
                        )
                    self._approved_root(state)
                    return self._save(state, status="queued", error=None)
                if attempt >= 32:
                    raise ValueError("Task attempt limit reached; create a new task")
                return self._save(
                    state,
                    status="awaiting_approval",
                    attempt=attempt + 1,
                    attempt_id=f"task-{task_id}-{attempt + 1}",
                    approval=None,
                    cancel_requested=False,
                    execution_started=False,
                    stopping_evidence=None,
                    receipt=None,
                    error=None,
                )

    def work(self, task_id, *, attempt: int):
        with _lease(self.path(f"tasks/{identifier(task_id)}/worker.lock")) as owner:
            if not owner:
                return self._load(task_id)
            with self.locked():
                state = self._load(task_id)
                _check_attempt(state, attempt)
                if state["status"] != "queued" or state["cancel_requested"]:
                    return state
                root = self._approved_root(state)
                if state["revision"] >= MAX_REVISIONS - 4:
                    raise ValueError(
                        "Task revision budget exhausted; create a new task"
                    )
                state = self._save(
                    state, status="running", execution_started=True, stopping_evidence=None, error=None
                )
            try:
                receipt = execute_experiment(
                    root,
                    attempt_id=state["attempt_id"],
                    resume=True,
                    cancelled=lambda: bool(self._load(task_id)["cancel_requested"]),
                )
                with self.locked():
                    return self._finish(self._load(task_id), root, receipt)
            except (Exception, KeyboardInterrupt) as exc:
                with self.locked():
                    state = self._load(task_id)
                    stopped = self._stopping_evidence(state, root)
                    return self._save(
                        state,
                        status="cancelled"
                        if state["cancel_requested"] and stopped is not None
                        else "interrupted",
                        stopping_evidence=stopped,
                        error=_error(exc),
                    )

    def _stopping_evidence(self, state, root):
        """Only retained native child exit observations establish cancellation."""
        records = []
        try:
            for role in ("entrypoint", "grader"):
                run_dir = confined(root, f"attempts/{state['attempt_id']}/{role}")
                if not run_dir.exists():
                    continue
                result = _native_result(root, run_dir)
                manifest = read_json(run_dir / "agent_run_manifest.json")
                if (
                    type(manifest.get("capture_outcome", {}).get("process_returncode"))
                    is not int
                ):
                    return None
                records.append(result["manifest"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return {
            "scope": "Observed direct command exits or no command launch; detached descendants and external effects excluded",
            "manifests": records,
        }

    def start(self, task_id, *, attempt: int):
        """Launch an owned background worker; its kernel lease arbitrates races."""
        with self.locked():
            state = self._load(task_id)
            _check_attempt(state, attempt)
            if state["status"] in TERMINAL or state["status"] == "running":
                return state
            if state["status"] != "queued" or state["cancel_requested"]:
                raise PermissionError(
                    "Task must be approved and queued before starting"
                )
            if state["revision"] >= MAX_REVISIONS - 4:
                raise ValueError("Task revision budget exhausted; create a new task")
            self._approved_root(state)
            command = [
                sys.executable,
                "-c",
                "import sys;sys.path.insert(0,sys.argv.pop(1));from agilab.agent_runtime.tasks import main;raise SystemExit(main())",
                str(Path(__file__).resolve().parents[2]),
                "worker",
                str(self.root),
                task_id,
                "--attempt",
                str(attempt),
            ]
            log = self.path(f"tasks/{task_id}/worker.log")
            if log.exists() and log.stat().st_size > 65536:
                log.write_bytes(b"Earlier worker diagnostics omitted\n")
            with log.open("ab") as stream:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stream,
                    stderr=stream,
                    close_fds=True,
                    start_new_session=True,
                )
            threading.Thread(target=process.wait, daemon=True).start()
            return state


def _error(exc):
    return redact_text(f"{type(exc).__name__}: {exc}")[:800]


def _check_attempt(state, attempt):
    if type(attempt) is not int or attempt != state["attempt"]:
        raise ValueError("Attempt changed; inspect the current task before mutation")


def summary(state):
    return {
        key: state[key]
        for key in (
            "schema",
            "task_id",
            "action_id",
            "plan_sha256",
            "attempt",
            "attempt_id",
            "revision",
            "status",
            "cancel_requested",
            "updated_at",
            "error",
            "receipt",
        )
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "register",
        "list",
        "submit",
        "approve",
        "deny",
        "status",
        "start",
        "worker",
        "cancel",
        "reconcile",
        "resume",
        "retry",
    ):
        item = sub.add_parser(name)
        item.add_argument("root", type=Path)
        if name == "register":
            item.add_argument("action_id")
            item.add_argument(
                "experiment", help="Relative prepared directory under experiments/"
            )
        elif name == "submit":
            item.add_argument("action_id")
            item.add_argument("idempotency_key")
        elif name != "list":
            item.add_argument("task_id")
        if name in {"approve", "deny"}:
            item.add_argument("--plan-sha256", required=True)
        if name in {"resume", "retry", "approve", "deny", "start", "worker", "cancel"}:
            item.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args(argv)
    store = TaskStore(args.root)
    try:
        if args.command == "register":
            result = store.register(args.action_id, args.experiment)
        elif args.command == "list":
            result = store.actions()
        elif args.command == "submit":
            result = store.submit(args.action_id, args.idempotency_key)
        elif args.command in {"approve", "deny"}:
            result = store.decide(
                args.task_id,
                plan_sha256=args.plan_sha256,
                attempt=args.attempt,
                approve=args.command == "approve",
            )
        elif args.command in {"retry", "resume"}:
            result = store.continue_attempt(
                args.task_id, attempt=args.attempt, retry=args.command == "retry"
            )
        else:
            method = "work" if args.command == "worker" else args.command
            options = (
                {"attempt": args.attempt}
                if args.command in {"start", "worker", "cancel"}
                else {}
            )
            result = getattr(store, method)(args.task_id, **options)
        print(json.dumps(summary(result) if "task_id" in result else result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(_error(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
