"""Execute declared Python experiments from frozen local inputs and grade outputs.

This is a trusted-operator runner, not a sandbox or producer attestation service.
Native agent-run evidence and immutable evaluation publication remain the storage
primitives. The executor binds the bytes it launches, rather than inferring
execution from a plan annotation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import sys
from typing import Any, Callable, Sequence
from uuid import uuid4

from agilab.agent_runtime.agent_run import (
    MANIFEST_FILENAME,
    create_agent_run_config,
    run_agent_command,
    validate_agent_run,
)
from agilab.agent_runtime.agent_trace import utc_now
from agilab.evidence.evidence_contract import sha256_file, sha256_payload
from agilab.evidence.skill_evaluation import persist_evaluation

PLAN_SCHEMA = "agilab.agent_experiment_plan.v1"
RECEIPT_SCHEMA = "agilab.agent_experiment_receipt.v1"
ACCEPTANCE_SCHEMA = "agilab.agent_experiment_acceptance.v1"
MAX_INPUT_BYTES = 50 * 1024 * 1024
CLAIM_SCOPE = (
    "Local executor observations bind declared source/input bytes, interpreter, "
    "command outcomes and a separate grader. Hashes prove content consistency; "
    "they do not attest the producer or isolate untrusted code, network access, "
    "undeclared files, installed dependencies or external side effects."
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise ValueError("Experiment JSON exceeds 1 MiB")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate experiment JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonfinite experiment JSON: {value}")

    value = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("Experiment JSON must be an object")
    return value


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("Expected a nonempty relative path of at most 512 characters")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or path.as_posix() != value
    ):
        raise ValueError("Experiment paths must be normalized relative POSIX paths")
    if any(part.startswith(".") for part in path.parts):
        raise ValueError("Hidden paths are not experiment inputs or outputs")
    return value


def confined(root: Path, relative: str) -> Path:
    relative_path(relative)
    if root.is_symlink():
        raise ValueError("Experiment directories cannot use symlinks")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Experiment path escapes its root")
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("Experiment files cannot use symlinks")
        current = current.parent
    return path


def file_record(root: Path, relative: str) -> dict[str, Any]:
    path = confined(root, relative)
    if not path.is_file():
        raise ValueError(f"Missing experiment file: {relative}")
    return {
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "sha256": sha256_payload(payload)}


def check_seal(payload: dict[str, Any], schema: str) -> None:
    if payload.get("schema") != schema or payload.get("sha256") != sha256_payload(
        {k: v for k, v in payload.items() if k != "sha256"}
    ):
        raise ValueError("Experiment schema or content digest mismatch")


def prepare_experiment(
    *,
    source_root: Path,
    output_dir: Path,
    files: Sequence[str],
    entrypoint: str,
    grader: str,
    outputs: Sequence[str],
    checks: Sequence[str],
    arguments: Sequence[str] = (),
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Freeze only explicitly selected local files into a new evidence directory."""
    source_root, output_dir = source_root.resolve(), output_dir.resolve()
    names = sorted(set(relative_path(name) for name in files))
    if not 1 <= len(names) <= 256 or entrypoint not in names or grader not in names:
        raise ValueError(
            "Select 1-256 files including the entrypoint and separate grader"
        )
    if (
        entrypoint == grader
        or not entrypoint.endswith(".py")
        or not grader.endswith(".py")
    ):
        raise ValueError(
            "Entrypoint and independent grader must be different Python files"
        )
    output_names = sorted(set(relative_path(name) for name in outputs))
    if not output_names or len(output_names) > 64 or set(output_names) & set(names):
        raise ValueError("Declare 1-64 outputs distinct from frozen inputs")
    check_names = list(checks)
    if (
        not 1 <= len(check_names) <= 100
        or len(set(check_names)) != len(check_names)
        or any(
            not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
            for name in check_names
        )
    ):
        raise ValueError("Declare 1-100 unique acceptance check identifiers")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be between 1 and 3600")
    if len(arguments) > 64 or any(
        not isinstance(v, str) or len(v) > 4096 for v in arguments
    ):
        raise ValueError("Experiment arguments exceed their bounds")
    records = [file_record(source_root, name) for name in names]
    if sum(record["size_bytes"] for record in records) > MAX_INPUT_BYTES:
        raise ValueError("Selected experiment files exceed 50 MiB")
    output_dir.mkdir(parents=True, exist_ok=False)
    snapshot = output_dir / "snapshot"
    for record in records:
        destination = confined(snapshot, record["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(confined(source_root, record["path"]), destination)
        if file_record(snapshot, record["path"]) != record:
            raise ValueError("Source changed while freezing the experiment")
    plan = seal(
        {
            "schema": PLAN_SCHEMA,
            "created_at": utc_now(),
            "producer": "python -m agilab.agent_runtime.experiment prepare",
            "source_root": str(source_root),
            "files": records,
            "entrypoint": entrypoint,
            "grader": grader,
            "arguments": list(arguments),
            "outputs": output_names,
            "checks": check_names,
            "timeout_seconds": timeout_seconds,
            "claim_scope": CLAIM_SCOPE,
        }
    )
    persist_evaluation(output_dir, "plan.json", plan)
    return plan


def load_plan(root: Path) -> dict[str, Any]:
    plan = read_json(root / "plan.json")
    check_seal(plan, PLAN_SCHEMA)
    _validate_plan_structure(plan)
    for entry in plan["files"]:
        if file_record(root / "snapshot", entry["path"]) != entry:
            raise ValueError(f"Frozen input changed: {entry['path']}")
    return plan


def _validate_plan_structure(plan):
    """A content digest does not make a malformed plan executable."""
    files = plan.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 256:
        raise ValueError("Plan must select 1-256 files")
    names = []
    for record in files:
        if not isinstance(record, dict) or set(record) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("Malformed frozen file reference")
        names.append(relative_path(record["path"]))
        if type(record["size_bytes"]) is not int or record["size_bytes"] < 0:
            raise ValueError("Invalid frozen file size")
        if not isinstance(record["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", record["sha256"]
        ):
            raise ValueError("Invalid frozen file digest")
    if (
        names != sorted(set(names))
        or sum(r["size_bytes"] for r in files) > MAX_INPUT_BYTES
    ):
        raise ValueError("Frozen file inventory exceeds bounds or contains duplicates")
    entry, grader = plan.get("entrypoint"), plan.get("grader")
    if entry not in names or grader not in names or entry == grader:
        raise ValueError(
            "Entrypoint and grader must be different selected frozen files"
        )
    if not entry.endswith(".py") or not grader.endswith(".py"):
        raise ValueError("Entrypoint and grader must be Python files")
    outputs = plan.get("outputs")
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 64:
        raise ValueError("Plan must declare 1-64 outputs")
    if outputs != sorted(set(relative_path(name) for name in outputs)) or set(
        outputs
    ) & set(names):
        raise ValueError("Outputs must be unique and distinct from frozen inputs")
    checks = plan.get("checks")
    if (
        not isinstance(checks, list)
        or not 1 <= len(checks) <= 100
        or any(
            not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
            for name in checks
        )
        or len(set(checks)) != len(checks)
    ):
        raise ValueError("Plan requires unique acceptance checks")
    arguments = plan.get("arguments")
    if (
        not isinstance(arguments, list)
        or len(arguments) > 64
        or any(not isinstance(value, str) or len(value) > 4096 for value in arguments)
    ):
        raise ValueError("Invalid experiment arguments")
    timeout = plan.get("timeout_seconds")
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ValueError("Invalid experiment timeout")
    if (
        not isinstance(plan.get("source_root"), str)
        or not Path(plan["source_root"]).is_absolute()
    ):
        raise ValueError("Plan source_root must be an absolute local path")


def source_status(plan: dict[str, Any]) -> dict[str, Any]:
    root = Path(plan["source_root"])
    changed = []
    for entry in plan["files"]:
        try:
            matches = file_record(root, entry["path"]) == entry
        except (OSError, ValueError):
            matches = False
        if not matches:
            changed.append(entry["path"])
    return {"status": "changed" if changed else "matched", "changed_files": changed}


def _copy_inputs(plan: dict[str, Any], snapshot: Path, workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=False)
    for entry in plan["files"]:
        target = confined(workspace, entry["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(confined(snapshot, entry["path"]), target)
    _check_inputs(plan, workspace)


def _check_inputs(plan: dict[str, Any], workspace: Path) -> None:
    if [file_record(workspace, entry["path"]) for entry in plan["files"]] != plan[
        "files"
    ]:
        raise ValueError("Executed source/input bytes differ from the frozen plan")


def _native_result(root: Path, run_dir: Path) -> dict[str, Any]:
    """Validate native artifacts at recorded relative locations after relocation."""
    manifest = read_json(run_dir / MANIFEST_FILENAME)
    artifacts = manifest["artifacts"]
    references = {}
    for name, filename in (
        ("stdout", "stdout.txt"),
        ("stderr", "stderr.txt"),
        ("claim", ".agent_run.claim.json"),
    ):
        path = run_dir / filename
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Agent evidence escapes the experiment root")
        # Claims are intentionally dotfiles, owned by the native run contract.
        entry = {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        descriptor = artifacts[name]
        if entry["sha256"] != descriptor.get("sha256") or entry[
            "size_bytes"
        ] != descriptor.get("size_bytes"):
            raise ValueError(f"Native {name} artifact changed")
        references[name] = entry
        descriptor["path"] = str(path)
    artifacts["manifest"] = str(run_dir / MANIFEST_FILENAME)
    trace = artifacts.get("agent_trace", {})
    for key, filename in (
        ("meta", "agent_trace_meta.json"),
        ("events", "agent_events.ndjson"),
        ("tool_output_dir", "tool-output"),
    ):
        path = run_dir / filename
        if path.is_symlink():
            raise ValueError("Trace artifacts cannot use symlinks")
        trace[key] = str(path)
    validation = validate_agent_run(manifest)
    if not validation["ok"]:
        raise ValueError("Native experiment run evidence failed validation")
    return {
        "manifest": file_record(
            root, (run_dir / MANIFEST_FILENAME).relative_to(root).as_posix()
        ),
        "artifacts": references,
        "status": manifest["status"],
        "returncode": manifest["returncode"],
        "argv_sha256": manifest["command"]["argv_sha256"],
        "cwd": manifest["command"]["cwd"],
        "python_executable": manifest["environment"]["python_executable"],
        "duration_seconds": manifest["timing"]["duration_seconds"],
        "metadata": manifest["context"]["metadata"],
    }


def _command(plan, workspace, role, acceptance_path=None):
    command = [sys.executable, "-E", "-s", "-B", str(workspace / plan[role])]
    if role == "entrypoint":
        command += plan["arguments"]
    else:
        command += [str(acceptance_path)]
    return command


def execute_experiment(
    root: Path,
    *,
    attempt_id: str | None = None,
    cancelled: Callable[[], bool] | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Execute and independently grade one attempt; never replay an ambiguous claim.

    A grader receives the candidate workspace path as its only positional argument
    and prints an acceptance JSON object to stdout. Its exit code is checked too.
    """
    root = root.resolve()
    plan = load_plan(root)
    if source_status(plan)["status"] != "matched":
        raise ValueError(
            "Source changed since preparation; prepare and approve a new plan"
        )
    attempt_id = attempt_id or uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", attempt_id):
        raise ValueError("Invalid experiment attempt identifier")
    attempt = confined(root, f"attempts/{attempt_id}")
    receipt_path = attempt / "receipt.json"
    if receipt_path.exists():
        if not resume:
            raise FileExistsError("Experiment attempt already exists")
        verify_experiment(root, receipt_path.relative_to(root).as_posix())
        return read_json(receipt_path)
    if attempt.exists() and not resume:
        raise FileExistsError("Experiment attempt already exists")
    attempt.mkdir(parents=True, exist_ok=True)
    workspace = attempt / "workspace"
    if not workspace.exists():
        _copy_inputs(plan, root / "snapshot", workspace)
    _check_inputs(plan, workspace)
    runtime = {
        "python": platform.python_version(),
        "executable": sys.executable,
        "executable_sha256": sha256_file(Path(sys.executable)),
    }
    launch = {
        "schema": "agilab.agent_experiment_launch.v1",
        "plan_sha256": plan["sha256"],
        "runtime": runtime,
        "execution_root": str(attempt),
    }
    launch_path = attempt / "launch.json"
    if launch_path.exists():
        if read_json(launch_path) != launch:
            raise ValueError(
                "Executor runtime or launch location changed across resume"
            )
    elif any((attempt / role).exists() for role in ("entrypoint", "grader")):
        raise RuntimeError("Interrupted command lacks its launch checkpoint")
    else:
        persist_evaluation(root, launch_path, launch)
    runs = {}
    candidate_outputs = None
    for role in ("entrypoint", "grader"):
        if cancelled is not None and cancelled():
            raise InterruptedError("Experiment cancellation requested")
        execution_dir = workspace
        if role == "grader":
            # The grader executes a separate copy from the immutable snapshot.
            load_plan(root)
            execution_dir = attempt / "grading"
            if not execution_dir.exists():
                _copy_inputs(plan, root / "snapshot", execution_dir)
        _check_inputs(plan, execution_dir)
        run_dir = attempt / role
        command = _command(plan, execution_dir, role, workspace)
        config = create_agent_run_config(
            command,
            cwd=execution_dir,
            output_dir=run_dir,
            run_id=f"{attempt_id}-{role}",
            agent="experiment",
            label=f"Experiment {role}",
            permission_level="standard",
            timeout_seconds=plan["timeout_seconds"],
            trace_enabled=True,
            metadata={
                "experiment_plan_sha256": plan["sha256"],
                "experiment_role": role,
            },
        )
        ran_now = not (run_dir / MANIFEST_FILENAME).exists()
        if not ran_now and resume:
            pass
        elif run_dir.exists():
            raise RuntimeError(
                "Interrupted command has an exclusive claim; reconcile or create an explicit new attempt"
            )
        else:
            if role == "grader":
                expected = {
                    "schema": "agilab.agent_experiment_checkpoint.v1",
                    "plan_sha256": plan["sha256"],
                    "candidate": candidate_outputs,
                }
                checkpoint = attempt / "grader-input.json"
                if checkpoint.exists():
                    if read_json(checkpoint) != expected:
                        raise ValueError(
                            "Grader input checkpoint changed before launch"
                        )
                else:
                    persist_evaluation(root, checkpoint, expected)
            run_agent_command(config, cancelled=cancelled)
        _check_inputs(plan, execution_dir)
        runs[role] = _native_result(root, run_dir)
        from agilab.agent_runtime.agent_run import _argv_hash

        if runs[role]["argv_sha256"] != _argv_hash(command):
            raise ValueError(
                "Completed command does not match this executor's frozen inputs"
            )
        if role == "entrypoint":
            current = _output_records(root, plan, attempt_id)
            checkpoint = attempt / "candidate-output.json"
            expected = {
                "schema": "agilab.agent_experiment_checkpoint.v1",
                "plan_sha256": plan["sha256"],
                "run": runs[role]["manifest"],
                "outputs": current[0],
                "missing": current[1],
            }
            if ran_now:
                persist_evaluation(root, checkpoint, expected)
            elif not checkpoint.exists() or read_json(checkpoint) != expected:
                raise ValueError(
                    "Completed candidate has missing or changed output checkpoint evidence"
                )
            candidate_outputs = expected
        else:
            expected_input = {
                "schema": "agilab.agent_experiment_checkpoint.v1",
                "plan_sha256": plan["sha256"],
                "candidate": candidate_outputs,
            }
            if read_json(attempt / "grader-input.json") != expected_input:
                raise ValueError("Grader input checkpoint changed")
    _check_inputs(plan, workspace)
    outputs, missing_outputs = _output_records(root, plan, attempt_id)
    if (
        outputs != candidate_outputs["outputs"]
        or missing_outputs != candidate_outputs["missing"]
    ):
        raise ValueError("The grader changed candidate outputs")
    acceptance = _acceptance(
        plan, attempt / "grader" / "stdout.txt", runs["grader"]["returncode"]
    )
    passed = (
        runs["entrypoint"]["returncode"] == 0
        and not missing_outputs
        and acceptance["status"] == "passed"
    )
    receipt = seal(
        {
            "schema": RECEIPT_SCHEMA,
            "created_at": utc_now(),
            "producer": "python -m agilab.agent_runtime.experiment run",
            "plan_sha256": plan["sha256"],
            "attempt_id": attempt_id,
            "execution_root": str(attempt),
            "runtime": runtime,
            "runs": runs,
            "outputs": outputs,
            "missing_outputs": missing_outputs,
            "acceptance": acceptance,
            "status": "passed" if passed else "failed",
            "input_binding": {
                "status": "matched_before_and_after",
                "files": plan["files"],
            },
            "checkpoints": {
                name: file_record(root, f"attempts/{attempt_id}/{name}.json")
                for name in ("candidate-output", "grader-input", "launch")
            },
            "usage": {
                "status": "not_observed",
                "input_tokens": None,
                "output_tokens": None,
            },
            "claim_scope": CLAIM_SCOPE,
        }
    )
    persist_evaluation(root, receipt_path, receipt)
    return receipt


def _output_records(root, plan, attempt_id):
    outputs, missing = [], []
    for name in plan["outputs"]:
        try:
            outputs.append(file_record(root, f"attempts/{attempt_id}/workspace/{name}"))
        except (OSError, ValueError):
            missing.append(name)
    return outputs, missing


def _acceptance(plan, path, returncode):
    try:
        payload = read_json(path)
        checks = payload["checks"]
        if payload.get("schema") != ACCEPTANCE_SCHEMA or not isinstance(checks, dict):
            raise ValueError("schema")
        if set(checks) != set(plan["checks"]) or any(
            type(value) is not bool for value in checks.values()
        ):
            raise ValueError("checks")
        return {
            "status": "passed"
            if returncode == 0 and all(checks.values())
            else "failed",
            "checks": checks,
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "status": "insufficient_evidence",
            "checks": {name: None for name in plan["checks"]},
        }


def verify_experiment(root: Path, receipt: str) -> dict[str, Any]:
    root = root.resolve()
    plan = load_plan(root)
    result = read_json(confined(root, receipt))
    check_seal(result, RECEIPT_SCHEMA)
    if result["plan_sha256"] != plan["sha256"] or result["input_binding"] != {
        "status": "matched_before_and_after",
        "files": plan["files"],
    }:
        raise ValueError("Receipt is not bound to this experiment plan")
    attempt = confined(root, f"attempts/{result['attempt_id']}")
    launch_relative = f"attempts/{result['attempt_id']}/launch.json"
    if file_record(root, launch_relative) != result["checkpoints"][
        "launch"
    ] or read_json(confined(root, launch_relative)) != {
        "schema": "agilab.agent_experiment_launch.v1",
        "plan_sha256": plan["sha256"],
        "runtime": result["runtime"],
        "execution_root": result["execution_root"],
    }:
        raise ValueError("Executor launch checkpoint changed")
    for name in ("workspace", "grading"):
        _check_inputs(plan, attempt / name)
    for role, stored in result["runs"].items():
        if (
            role not in ("entrypoint", "grader")
            or _native_result(root, attempt / role) != stored
        ):
            raise ValueError("Native run changed since the receipt was issued")
        if stored["metadata"].get("experiment_plan_sha256") != plan["sha256"]:
            raise ValueError("Native run belongs to a different plan")
        if stored["metadata"].get("experiment_role") != role:
            raise ValueError("Native run belongs to a different experiment role")
        execution_dir = Path(result["execution_root"]) / (
            "workspace" if role == "entrypoint" else "grading"
        )
        argv = [
            result["runtime"]["executable"],
            "-E",
            "-s",
            "-B",
            str(execution_dir / plan[role]),
        ]
        argv += (
            plan["arguments"]
            if role == "entrypoint"
            else [str(Path(result["execution_root"]) / "workspace")]
        )
        from agilab.agent_runtime.agent_run import _argv_hash

        if stored["argv_sha256"] != _argv_hash(argv) or stored["cwd"] != str(
            execution_dir
        ):
            raise ValueError(
                "Native command is not bound to the frozen executor inputs"
            )
        if stored["python_executable"] != result["runtime"]["executable"]:
            raise ValueError("Native command used a different interpreter")
    if set(result["runs"]) != {"entrypoint", "grader"}:
        raise ValueError("Receipt must include execution and independent grading")
    outputs, missing = [], []
    for name in plan["outputs"]:
        relative = f"attempts/{result['attempt_id']}/workspace/{name}"
        try:
            outputs.append(file_record(root, relative))
        except (OSError, ValueError):
            missing.append(name)
    if outputs != result["outputs"] or missing != result["missing_outputs"]:
        raise ValueError("Experiment outputs changed")
    expected_checkpoint = {
        "schema": "agilab.agent_experiment_checkpoint.v1",
        "plan_sha256": plan["sha256"],
        "run": result["runs"]["entrypoint"]["manifest"],
        "outputs": outputs,
        "missing": missing,
    }
    for name in ("candidate-output", "grader-input"):
        path = f"attempts/{result['attempt_id']}/{name}.json"
        if file_record(root, path) != result["checkpoints"][name]:
            raise ValueError("Experiment checkpoint changed")
        expected = (
            expected_checkpoint
            if name == "candidate-output"
            else {
                "schema": "agilab.agent_experiment_checkpoint.v1",
                "plan_sha256": plan["sha256"],
                "candidate": expected_checkpoint,
            }
        )
        if read_json(confined(root, path)) != expected:
            raise ValueError(
                "Experiment checkpoints do not bind candidate outputs to grading"
            )
    acceptance = _acceptance(
        plan, attempt / "grader" / "stdout.txt", result["runs"]["grader"]["returncode"]
    )
    expected = (
        "passed"
        if result["runs"]["entrypoint"]["returncode"] == 0
        and not missing
        and acceptance["status"] == "passed"
        else "failed"
    )
    if result["acceptance"] != acceptance or result["status"] != expected:
        raise ValueError("Receipt outcome contradicts independent acceptance")
    return {
        "schema": "agilab.agent_experiment_verification.v1",
        "verification": "passed",
        "experiment_status": expected,
        "current_source": source_status(plan),
        "receipt_sha256": result["sha256"],
        "claim_scope": CLAIM_SCOPE,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--file", action="append", required=True)
    prepare.add_argument("--entrypoint", required=True)
    prepare.add_argument("--grader", required=True)
    prepare.add_argument("--artifact", action="append", required=True)
    prepare.add_argument("--check", action="append", required=True)
    for name in ("run", "verify"):
        command = sub.add_parser(name)
        command.add_argument("root", type=Path)
        if name == "verify":
            command.add_argument("receipt")
        else:
            command.add_argument("--attempt-id", required=True)
            command.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare_experiment(
            source_root=args.source,
            output_dir=args.output,
            files=args.file,
            entrypoint=args.entrypoint,
            grader=args.grader,
            outputs=args.artifact,
            checks=args.check,
        )
    elif args.command == "run":
        result = execute_experiment(
            args.root, attempt_id=args.attempt_id, resume=args.resume
        )
    else:
        result = verify_experiment(args.root, args.receipt)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
