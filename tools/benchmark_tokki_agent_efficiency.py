#!/usr/bin/env python3
"""Run a paired Tokki-on/Tokki-off Codex benchmark on historical AGILAB tasks."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS_PATH = REPO_ROOT / "tools/tokki_agent_efficiency_tasks.json"
DEFAULT_REPORT_ROOT = REPO_ROOT / "reports/tokki-agent-efficiency"
TASK_KIND = "agilab.tokki_agent_efficiency_tasks.v1"
RESULT_KIND = "agilab.tokki_agent_efficiency_result.v1"
MANIFEST_KIND = "agilab.tokki_agent_efficiency_benchmark.v1"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
TASK_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
CONDITIONS = ("tokki", "control")
CONTROL_ENV_VALUE = "off"


class BenchmarkError(RuntimeError):
    """Raised when benchmark evidence would not be trustworthy."""


@dataclass(frozen=True)
class TaskSpec:
    """One historical AGILAB repair task and its hidden verification contract."""

    task_id: str
    title: str
    base_commit: str
    reference_fix_commit: str
    prompt: str
    hidden_test_paths: tuple[str, ...]
    verification_commands: tuple[tuple[str, ...], ...]
    agent_timeout_seconds: int
    verification_timeout_seconds: int


@dataclass(frozen=True)
class CommandCapture:
    """Bounded result of one subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


def _ensure_repo_on_path(repo_root: Path) -> None:
    src_root = repo_root / "src"
    for entry in (str(src_root), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)


_ensure_repo_on_path(REPO_ROOT)

from agilab.agent_runtime.agent_run import trace_agent_run  # noqa: E402


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _write_json(path: Path, value: object) -> None:
    _write_text(
        path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def _relative_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkError(f"{field} must be a non-empty repository-relative path")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise BenchmarkError(
            f"{field} must not be absolute or contain traversal: {value!r}"
        )
    return candidate.as_posix()


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BenchmarkError(f"{field} must be a positive integer")
    return value


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkError(f"{field} must be a non-empty list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise BenchmarkError(f"{field} entries must be non-empty strings")
        result.append(item)
    return tuple(result)


def load_tasks(path: Path) -> tuple[TaskSpec, ...]:
    """Load and strictly validate the public benchmark task contract."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"unable to load task file {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != TASK_KIND:
        raise BenchmarkError(f"task file kind must be {TASK_KIND}")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise BenchmarkError("task file must contain a non-empty tasks list")

    tasks: list[TaskSpec] = []
    seen_ids: set[str] = set()
    required_keys = {
        "id",
        "title",
        "base_commit",
        "reference_fix_commit",
        "prompt",
        "hidden_test_paths",
        "verification_commands",
        "agent_timeout_seconds",
        "verification_timeout_seconds",
    }
    for index, raw_task in enumerate(raw_tasks):
        if not isinstance(raw_task, dict):
            raise BenchmarkError(f"tasks[{index}] must be an object")
        missing = sorted(required_keys - raw_task.keys())
        unknown = sorted(raw_task.keys() - required_keys)
        if missing or unknown:
            raise BenchmarkError(
                f"tasks[{index}] fields mismatch: missing={missing} unknown={unknown}"
            )
        task_id = raw_task["id"]
        if not isinstance(task_id, str) or TASK_ID_PATTERN.fullmatch(task_id) is None:
            raise BenchmarkError(f"tasks[{index}].id is invalid: {task_id!r}")
        if task_id in seen_ids:
            raise BenchmarkError(f"duplicate task id: {task_id}")
        seen_ids.add(task_id)

        base_commit = raw_task["base_commit"]
        fix_commit = raw_task["reference_fix_commit"]
        if (
            not isinstance(base_commit, str)
            or SHA_PATTERN.fullmatch(base_commit) is None
        ):
            raise BenchmarkError(f"{task_id}: base_commit must be a full lowercase SHA")
        if not isinstance(fix_commit, str) or SHA_PATTERN.fullmatch(fix_commit) is None:
            raise BenchmarkError(
                f"{task_id}: reference_fix_commit must be a full lowercase SHA"
            )
        title = raw_task["title"]
        prompt = raw_task["prompt"]
        if not isinstance(title, str) or not title.strip():
            raise BenchmarkError(f"{task_id}: title must be non-empty")
        if not isinstance(prompt, str) or len(prompt.strip()) < 40:
            raise BenchmarkError(
                f"{task_id}: prompt is too short to define a fair task"
            )

        hidden_paths = tuple(
            _relative_path(item, field=f"{task_id}.hidden_test_paths")
            for item in _string_tuple(
                raw_task["hidden_test_paths"], field=f"{task_id}.hidden_test_paths"
            )
        )
        raw_commands = raw_task["verification_commands"]
        if not isinstance(raw_commands, list) or not raw_commands:
            raise BenchmarkError(
                f"{task_id}: verification_commands must be a non-empty list"
            )
        commands: list[tuple[str, ...]] = []
        for command_index, raw_command in enumerate(raw_commands):
            command = _string_tuple(
                raw_command,
                field=f"{task_id}.verification_commands[{command_index}]",
            )
            if any("\x00" in part for part in command):
                raise BenchmarkError(f"{task_id}: verification command contains NUL")
            selectors = command[4:]
            if command[:4] != ("{python}", "-m", "pytest", "-q") or not selectors:
                raise BenchmarkError(
                    f"{task_id}: verification must be a focused pytest command"
                )
            if any(
                selector.split("::", 1)[0] not in hidden_paths for selector in selectors
            ):
                raise BenchmarkError(
                    f"{task_id}: verification selector is outside hidden_test_paths"
                )
            commands.append(command)

        tasks.append(
            TaskSpec(
                task_id=task_id,
                title=title.strip(),
                base_commit=base_commit,
                reference_fix_commit=fix_commit,
                prompt=prompt.strip(),
                hidden_test_paths=hidden_paths,
                verification_commands=tuple(commands),
                agent_timeout_seconds=_positive_int(
                    raw_task["agent_timeout_seconds"],
                    field=f"{task_id}.agent_timeout_seconds",
                ),
                verification_timeout_seconds=_positive_int(
                    raw_task["verification_timeout_seconds"],
                    field=f"{task_id}.verification_timeout_seconds",
                ),
            )
        )
    return tuple(tasks)


def _merged_environment(overrides: Mapping[str, str]) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(overrides)
    return environment


def _capture(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int | float | None = None,
    input_bytes: bytes | None = None,
) -> CommandCapture:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=_merged_environment(env) if env is not None else None,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")
        return CommandCapture(
            returncode=int(completed.returncode),
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.perf_counter() - started,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_value = exc.stdout or b""
        stderr_value = exc.stderr or b""
        stdout = (
            stdout_value
            if isinstance(stdout_value, str)
            else stdout_value.decode("utf-8", "replace")
        )
        stderr = (
            stderr_value
            if isinstance(stderr_value, str)
            else stderr_value.decode("utf-8", "replace")
        )
        return CommandCapture(
            returncode=124,
            stdout=stdout,
            stderr=(stderr + f"\nTimed out after {timeout_seconds}s").strip(),
            duration_seconds=time.perf_counter() - started,
            timed_out=True,
        )


def _git_text(repo_root: Path, *arguments: str, check: bool = True) -> str:
    result = _capture(("git", *arguments), cwd=repo_root)
    if check and result.returncode != 0:
        raise BenchmarkError(
            f"git {' '.join(arguments)} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def _git_bytes(repo_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise BenchmarkError(
            f"git {' '.join(arguments)} failed ({completed.returncode}): "
            f"{completed.stderr.decode('utf-8', 'replace').strip()}"
        )
    return completed.stdout


def _require_historical_commit(
    repo_root: Path,
    task: TaskSpec,
    commit: str,
    label: str,
) -> None:
    result = _capture(("git", "cat-file", "-e", f"{commit}^{{commit}}"), cwd=repo_root)
    if result.returncode == 0:
        return
    detail = result.stderr.strip() or "Git object is not present"
    raise BenchmarkError(
        f"{task.task_id}: required {label} commit {commit} is unavailable in this "
        f"checkout; use a full clone or fetch that commit before running the "
        f"benchmark ({detail})"
    )


def validate_task_provenance(repo_root: Path, task: TaskSpec) -> dict[str, object]:
    """Prove that the hidden tests belong to the task's direct reference fix."""

    _require_historical_commit(repo_root, task, task.base_commit, "base")
    _require_historical_commit(
        repo_root,
        task,
        task.reference_fix_commit,
        "reference-fix",
    )
    parent = _git_text(repo_root, "rev-parse", f"{task.reference_fix_commit}^").strip()
    if parent != task.base_commit:
        raise BenchmarkError(
            f"{task.task_id}: reference fix parent {parent} does not equal base {task.base_commit}"
        )
    patch = _git_bytes(
        repo_root,
        "diff",
        "--binary",
        task.base_commit,
        task.reference_fix_commit,
        "--",
        *task.hidden_test_paths,
    )
    if not patch.strip():
        raise BenchmarkError(f"{task.task_id}: hidden regression patch is empty")
    changed_paths = tuple(
        line
        for line in _git_text(
            repo_root,
            "diff",
            "--name-only",
            task.base_commit,
            task.reference_fix_commit,
        ).splitlines()
        if line
    )
    non_test_paths = tuple(
        path for path in changed_paths if path not in task.hidden_test_paths
    )
    if not non_test_paths:
        raise BenchmarkError(
            f"{task.task_id}: reference fix has no product-code change"
        )
    return {
        "task_id": task.task_id,
        "base_commit": task.base_commit,
        "base_tree": _git_text(
            repo_root, "rev-parse", f"{task.base_commit}^{{tree}}"
        ).strip(),
        "reference_fix_commit": task.reference_fix_commit,
        "reference_fix_tree": _git_text(
            repo_root,
            "rev-parse",
            f"{task.reference_fix_commit}^{{tree}}",
        ).strip(),
        "hidden_test_patch_sha256": _sha256_bytes(patch),
        "hidden_test_patch_bytes": len(patch),
        "hidden_test_paths": list(task.hidden_test_paths),
        "reference_changed_paths": list(changed_paths),
        "reference_product_paths": list(non_test_paths),
    }


def _safe_extract_tar(archive_bytes: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    destination_resolved = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
        for member in archive.getmembers():
            candidate = (destination / member.name).resolve()
            if (
                candidate != destination_resolved
                and destination_resolved not in candidate.parents
            ):
                raise BenchmarkError(f"unsafe archive member: {member.name}")
        archive.extractall(destination, filter="data")


def _initialize_isolated_git(workspace: Path) -> str:
    commands = (
        ("init", "--quiet"),
        ("config", "user.name", "AGILAB Benchmark"),
        ("config", "user.email", "benchmark@invalid.example"),
        ("config", "commit.gpgsign", "false"),
        ("add", "--all"),
        ("commit", "--quiet", "-m", "benchmark baseline"),
    )
    for command in commands:
        _git_text(workspace, *command)
    return _git_text(workspace, "rev-parse", "HEAD").strip()


def _overlay_current_tokki_profile(repo_root: Path, workspace: Path) -> None:
    """Use the reviewed benchmark revision's Tokki profile in old task snapshots."""

    source = repo_root / ".tokki" / "profile"
    if not source.is_file():
        raise BenchmarkError("benchmark source is missing .tokki/profile")
    destination = workspace / ".tokki" / "profile"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def prepare_workspace(repo_root: Path, commit: str, destination: Path) -> str:
    """Create a history-free snapshot with the current reviewed Tokki profile."""

    archive = _git_bytes(repo_root, "archive", "--format=tar", commit)
    _safe_extract_tar(archive, destination)
    _overlay_current_tokki_profile(repo_root, destination)
    return _initialize_isolated_git(destination)


def _hidden_test_patch(repo_root: Path, task: TaskSpec) -> bytes:
    return _git_bytes(
        repo_root,
        "diff",
        "--binary",
        task.base_commit,
        task.reference_fix_commit,
        "--",
        *task.hidden_test_paths,
    )


def _apply_hidden_tests(workspace: Path, patch: bytes) -> CommandCapture:
    return _capture(
        ("git", "apply", "--whitespace=nowarn", "-"),
        cwd=workspace,
        input_bytes=patch,
    )


def _expand_verification_command(
    command: Sequence[str],
    *,
    python_executable: Path,
    workspace: Path,
) -> tuple[str, ...]:
    replacements = {
        "{python}": str(python_executable),
        "{workspace}": str(workspace),
    }
    return tuple(replacements.get(part, part) for part in command)


def _run_verification(
    task: TaskSpec,
    *,
    workspace: Path,
    python_executable: Path,
    artifact_dir: Path,
) -> dict[str, object]:
    command_results: list[dict[str, object]] = []
    passed = True
    for index, command_template in enumerate(task.verification_commands, start=1):
        command = _expand_verification_command(
            command_template,
            python_executable=python_executable,
            workspace=workspace,
        )
        result = _capture(
            command,
            cwd=workspace,
            timeout_seconds=task.verification_timeout_seconds,
        )
        stdout_path = artifact_dir / f"verification-{index}.stdout.txt"
        stderr_path = artifact_dir / f"verification-{index}.stderr.txt"
        _write_text(stdout_path, result.stdout)
        _write_text(stderr_path, result.stderr)
        command_passed = result.returncode == 0
        passed = passed and command_passed
        command_results.append(
            {
                "argv": list(command),
                "argv_sha256": _sha256_text(_canonical_json(list(command))),
                "returncode": result.returncode,
                "timed_out": result.timed_out,
                "duration_seconds": result.duration_seconds,
                "passed": command_passed,
                "stdout": {
                    "path": str(stdout_path),
                    "sha256": _sha256_file(stdout_path),
                    "bytes": stdout_path.stat().st_size,
                },
                "stderr": {
                    "path": str(stderr_path),
                    "sha256": _sha256_file(stderr_path),
                    "bytes": stderr_path.stat().st_size,
                },
            }
        )
    return {"passed": passed, "commands": command_results}


def _walk_mappings(value: object) -> Iterable[Mapping[str, object]]:
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _walk_mappings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_mappings(nested)


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _normalize_usage(raw: Mapping[str, object]) -> dict[str, int] | None:
    input_tokens = _integer(raw.get("input_tokens"))
    output_tokens = _integer(raw.get("output_tokens"))
    total_tokens = _integer(raw.get("total_tokens"))
    cached_input_tokens = _integer(raw.get("cached_input_tokens"))
    input_details = raw.get("input_tokens_details")
    if cached_input_tokens is None and isinstance(input_details, Mapping):
        cached_input_tokens = _integer(input_details.get("cached_tokens"))
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    input_tokens = input_tokens or 0
    output_tokens = output_tokens or 0
    cached_input_tokens = min(cached_input_tokens or 0, input_tokens)
    total_tokens = (
        total_tokens if total_tokens is not None else input_tokens + output_tokens
    )
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": input_tokens - cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def parse_codex_jsonl(value: str) -> dict[str, object]:
    """Read the final structured Codex usage event without double-counting nested events."""

    event_count = 0
    invalid_line_count = 0
    usage_candidates: list[dict[str, int]] = []
    reported_models: list[str] = []
    event_types: list[str] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_line_count += 1
            continue
        if not isinstance(event, dict):
            invalid_line_count += 1
            continue
        event_count += 1
        event_type = event.get("type")
        if isinstance(event_type, str):
            event_types.append(event_type)
        for mapping in _walk_mappings(event):
            model = mapping.get("model")
            if isinstance(model, str) and model not in reported_models:
                reported_models.append(model)
            raw_usage = mapping.get("usage")
            if isinstance(raw_usage, Mapping):
                usage = _normalize_usage(raw_usage)
                if usage is not None and (
                    not usage_candidates or usage != usage_candidates[-1]
                ):
                    usage_candidates.append(usage)
    usage = usage_candidates[-1] if usage_candidates else None
    return {
        "status": "available" if usage is not None else "missing",
        "usage": usage,
        "event_count": event_count,
        "invalid_line_count": invalid_line_count,
        "event_types": sorted(set(event_types)),
        "reported_models": reported_models,
    }


def build_agent_prompt(task: TaskSpec, condition: str) -> str:
    """Build the common task prompt with only the treatment instruction varied."""

    if condition not in CONDITIONS:
        raise BenchmarkError(f"unknown benchmark condition: {condition}")
    treatment = {
        "tokki": (
            "Tokki is enabled for this treatment. Use the repository's Tokki-aware workflow "
            "normally, including its map, query, bounded-read, and routed-command surfaces when useful."
        ),
        "control": (
            "Tokki auto-routing is disabled for this control. Do not invoke Tokki or its wrappers; "
            "use ordinary repository and shell tools."
        ),
    }[condition]
    return (
        "You are participating in a controlled AGILAB coding benchmark.\n\n"
        f"Condition instruction: {treatment}\n\n"
        "The workspace is a history-free snapshot. Do not seek a future/reference patch, remote, "
        "benchmark fixture, or hidden regression test. Do not modify tests. Work only in this "
        "workspace, leave the solution uncommitted, and run the focused validation you can see.\n\n"
        f"Task:\n{task.prompt}\n"
    )


def validate_driver_environment(environment: Mapping[str, str]) -> None:
    """Refuse live orchestration from a provider-managed session or disabled outer shell."""

    if environment.get("TOKKI_SESSION_ID"):
        raise BenchmarkError(
            "live benchmark runs must start from an unrelated human shell after all Codex/Claude "
            "provider sessions exit; an active TOKKI_SESSION_ID would contaminate the control and "
            "trip Tokki's serial provider quota"
        )
    auto_run = environment.get("TOKKI_AUTO_RUN", "").strip().lower()
    if auto_run in {"0", "false", "no", "off", "disabled", "none"}:
        raise BenchmarkError(
            "unset TOKKI_AUTO_RUN in the human driver shell; the benchmark applies the supported "
            "off value only to each control provider child"
        )


def _condition_environment(condition: str) -> dict[str, str]:
    environment = os.environ.copy()
    if condition == "control":
        environment["TOKKI_AUTO_RUN"] = CONTROL_ENV_VALUE
    elif condition == "tokki":
        environment.pop("TOKKI_AUTO_RUN", None)
    else:
        raise BenchmarkError(f"unknown condition: {condition}")
    return environment


def _resolve_executable(value: str, *, label: str) -> Path:
    candidate = Path(value).expanduser()
    if len(candidate.parts) == 1:
        discovered = shutil.which(value)
        if not discovered:
            raise BenchmarkError(f"{label} executable is unavailable: {value}")
        executable = Path(discovered)
    else:
        executable = Path(os.path.abspath(candidate))
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise BenchmarkError(f"{label} executable is unavailable: {value}")
    # Keep virtualenv launcher symlinks intact. Resolving them selects the base
    # interpreter and silently drops the virtualenv's installed test tooling.
    return executable


def _codex_command(
    *,
    codex_bin: Path,
    model: str,
    reasoning_effort: str,
    workspace: Path,
    prompt: str,
) -> tuple[str, ...]:
    return (
        str(codex_bin),
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "exec",
        "--json",
        "--ephemeral",
        "--model",
        model,
        "--sandbox",
        "workspace-write",
        "--approve-for-me",
        "--cd",
        str(workspace),
        prompt,
    )


def _changed_paths(workspace: Path, baseline_commit: str) -> tuple[str, ...]:
    tracked = _git_text(workspace, "diff", "--name-only", baseline_commit).splitlines()
    untracked = _git_text(
        workspace,
        "ls-files",
        "--others",
        "--exclude-standard",
    ).splitlines()
    return tuple(sorted({path for path in (*tracked, *untracked) if path}))


def _is_test_or_benchmark_control_path(value: str) -> bool:
    path = PurePosixPath(value)
    if any(part in {"test", "tests"} for part in path.parts):
        return True
    if path.name == "conftest.py" or path.name.startswith("test_"):
        return True
    if path.name in {"pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"}:
        return True
    return bool(path.parts and path.parts[0] in {".codex", ".tokki"}) or value in {
        "AGENTS.md",
        "CLAUDE.md",
    }


def _capture_solution(
    workspace: Path, baseline_commit: str, artifact_dir: Path
) -> dict[str, object]:
    changed_paths = _changed_paths(workspace, baseline_commit)
    add_result = _capture(("git", "add", "--all"), cwd=workspace)
    if add_result.returncode != 0:
        raise BenchmarkError(
            f"unable to stage disposable benchmark solution: {add_result.stderr}"
        )
    patch = _git_bytes(workspace, "diff", "--cached", "--binary", baseline_commit)
    patch_path = artifact_dir / "solution.patch"
    patch_path.write_bytes(patch)
    current_head = _git_text(workspace, "rev-parse", "HEAD").strip()
    return {
        "changed_paths": list(changed_paths),
        "changed_path_count": len(changed_paths),
        "baseline_local_commit": baseline_commit,
        "current_local_commit": current_head,
        "agent_created_commit": current_head != baseline_commit,
        "patch": {
            "path": str(patch_path),
            "sha256": _sha256_file(patch_path),
            "bytes": patch_path.stat().st_size,
        },
    }


def _artifact_payload(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _run_condition(
    task: TaskSpec,
    *,
    condition: str,
    attempt: int,
    order_index: int,
    repo_root: Path,
    output_root: Path,
    codex_bin: Path,
    model: str,
    reasoning_effort: str,
    python_executable: Path,
) -> dict[str, object]:
    artifact_dir = (
        output_root / "runs" / task.task_id / f"attempt-{attempt}" / condition
    )
    workspace = artifact_dir / "workspace"
    artifact_dir.mkdir(parents=True, exist_ok=False)
    baseline_local_commit = prepare_workspace(repo_root, task.base_commit, workspace)
    prompt = build_agent_prompt(task, condition)
    prompt_path = artifact_dir / "prompt.txt"
    _write_text(prompt_path, prompt)
    command = _codex_command(
        codex_bin=codex_bin,
        model=model,
        reasoning_effort=reasoning_effort,
        workspace=workspace,
        prompt=prompt,
    )
    trace_dir = artifact_dir / "agent-run"
    trace_result = trace_agent_run(
        command,
        agent="codex",
        label=f"Tokki A/B: {task.task_id} ({condition})",
        cwd=workspace,
        output_dir=trace_dir,
        timeout_seconds=task.agent_timeout_seconds,
        env_overrides={"TOKKI_AUTO_RUN": CONTROL_ENV_VALUE}
        if condition == "control"
        else {},
        allow_failure=True,
        include_command_args=False,
        tags=("tokki-ab-benchmark", condition),
        metadata={
            "task_id": task.task_id,
            "attempt": str(attempt),
            "condition": condition,
        },
        capabilities=("repository-repair", "evidence"),
        provider="openai",
        model=model,
        permission_level="standard",
        trace_enabled=True,
        redact_output=True,
    )
    stdout_path = trace_dir / "stdout.txt"
    stderr_path = trace_dir / "stderr.txt"
    codex_events = (
        stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
    )
    codex_usage = parse_codex_jsonl(codex_events)
    solution = _capture_solution(workspace, baseline_local_commit, artifact_dir)
    forbidden_changed_paths = sorted(
        path
        for path in solution["changed_paths"]
        if _is_test_or_benchmark_control_path(path)
    )
    solution["forbidden_changed_paths"] = forbidden_changed_paths
    hidden_test_tampered = bool(
        set(solution["changed_paths"]) & set(task.hidden_test_paths)
    )
    hidden_patch = _hidden_test_patch(repo_root, task)
    hidden_patch_path = artifact_dir / "hidden-regression-tests.patch"
    hidden_patch_path.write_bytes(hidden_patch)
    apply_result = _apply_hidden_tests(workspace, hidden_patch)
    apply_stdout_path = artifact_dir / "hidden-tests-apply.stdout.txt"
    apply_stderr_path = artifact_dir / "hidden-tests-apply.stderr.txt"
    _write_text(apply_stdout_path, apply_result.stdout)
    _write_text(apply_stderr_path, apply_result.stderr)
    if apply_result.returncode == 0:
        verification = _run_verification(
            task,
            workspace=workspace,
            python_executable=python_executable,
            artifact_dir=artifact_dir,
        )
    else:
        verification = {
            "passed": False,
            "commands": [],
            "blocked_reason": "hidden regression tests did not apply cleanly",
        }
    agent_completed = trace_result.returncode == 0
    accepted = bool(
        agent_completed
        and apply_result.returncode == 0
        and verification["passed"]
        and not hidden_test_tampered
        and not forbidden_changed_paths
        and not solution["agent_created_commit"]
    )
    result: dict[str, object] = {
        "kind": RESULT_KIND,
        "task_id": task.task_id,
        "task_title": task.title,
        "task_sha256": _sha256_text(_canonical_json(asdict(task))),
        "condition": condition,
        "attempt": attempt,
        "order_index": order_index,
        "source": {
            "base_commit": task.base_commit,
            "reference_fix_commit": task.reference_fix_commit,
        },
        "agent": {
            "provider": "openai",
            "model": model,
            "reasoning_effort": reasoning_effort,
            "returncode": trace_result.returncode,
            "completed": agent_completed,
            "duration_seconds": trace_result.manifest.get("timing", {}).get(
                "duration_seconds"
            ),
            "command_argv_sha256": _sha256_text(_canonical_json(list(command[:-1]))),
            "prompt": _artifact_payload(prompt_path),
            "stdout": _artifact_payload(stdout_path) if stdout_path.exists() else None,
            "stderr": _artifact_payload(stderr_path) if stderr_path.exists() else None,
            "usage": codex_usage,
            "agent_run_manifest": _artifact_payload(
                trace_dir / "agent_run_manifest.json"
            ),
        },
        "solution": solution,
        "hidden_tests": {
            "paths": list(task.hidden_test_paths),
            "tampered_by_agent": hidden_test_tampered,
            "patch": _artifact_payload(hidden_patch_path),
            "apply_returncode": apply_result.returncode,
            "apply_stdout": _artifact_payload(apply_stdout_path),
            "apply_stderr": _artifact_payload(apply_stderr_path),
        },
        "verification": verification,
        "accepted": accepted,
        "limitations": [
            "This is a repository-specific historical repair task, not a general model-capability score.",
            "The control uses the supported provider-wide TOKKI_AUTO_RUN=off recovery setting.",
            "Agent output is redacted and stays under the ignored local reports directory.",
            "The Codex workspace sandbox is not a VM; review traces for any out-of-workspace read.",
        ],
    }
    result_path = artifact_dir / "result.json"
    _write_json(result_path, result)
    print(
        f"[{order_index}] {task.task_id} attempt={attempt} condition={condition} "
        f"agent_rc={trace_result.returncode} verification={verification['passed']} accepted={accepted}",
        flush=True,
    )
    return result


def _metric_total(results: Sequence[Mapping[str, object]], key: str) -> int | None:
    values: list[int] = []
    for result in results:
        agent = result.get("agent")
        if not isinstance(agent, Mapping):
            return None
        usage_payload = agent.get("usage")
        if (
            not isinstance(usage_payload, Mapping)
            or usage_payload.get("status") != "available"
        ):
            return None
        usage = usage_payload.get("usage")
        if not isinstance(usage, Mapping):
            return None
        value = _integer(usage.get(key))
        if value is None:
            return None
        values.append(value)
    return sum(values)


def _relative_reduction(control: object, tokki: object) -> float | None:
    if isinstance(control, bool) or isinstance(tokki, bool):
        return None
    if not isinstance(control, (int, float)) or not isinstance(tokki, (int, float)):
        return None
    if control <= 0:
        return None
    return (float(control) - float(tokki)) / float(control)


def summarize_results(
    results: Sequence[Mapping[str, object]],
    *,
    expected_tasks: int,
    attempts: int,
) -> dict[str, object]:
    """Aggregate paired outcomes and make claim eligibility explicit."""

    by_condition: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    pairs: dict[tuple[str, int], dict[str, Mapping[str, object]]] = defaultdict(dict)
    for result in results:
        condition = result.get("condition")
        task_id = result.get("task_id")
        attempt = result.get("attempt")
        if (
            condition in CONDITIONS
            and isinstance(task_id, str)
            and isinstance(attempt, int)
        ):
            by_condition[str(condition)].append(result)
            pairs[(task_id, attempt)][str(condition)] = result

    condition_summaries: dict[str, object] = {}
    usage_complete = True
    for condition in CONDITIONS:
        condition_results = by_condition.get(condition, [])
        accepted_count = sum(
            bool(result.get("accepted")) for result in condition_results
        )
        attempted_count = len(condition_results)
        metrics: dict[str, int | None] = {}
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "total_tokens",
        ):
            metrics[key] = (
                _metric_total(condition_results, key) if condition_results else None
            )
        if any(value is None for value in metrics.values()):
            usage_complete = False
        duration = sum(
            float(result.get("agent", {}).get("duration_seconds") or 0.0)
            for result in condition_results
            if isinstance(result.get("agent"), Mapping)
        )
        condition_summaries[condition] = {
            "attempted": attempted_count,
            "accepted": accepted_count,
            "acceptance_rate": accepted_count / attempted_count
            if attempted_count
            else None,
            "agent_duration_seconds": duration,
            "usage_totals": metrics,
            "uncached_input_tokens_per_accepted_task": (
                metrics["uncached_input_tokens"] / accepted_count
                if accepted_count and metrics["uncached_input_tokens"] is not None
                else None
            ),
            "total_tokens_per_accepted_task": (
                metrics["total_tokens"] / accepted_count
                if accepted_count and metrics["total_tokens"] is not None
                else None
            ),
        }

    expected_pairs = expected_tasks * attempts
    complete_pairs = sum(set(pair) == set(CONDITIONS) for pair in pairs.values())
    both_conditions_complete = all(
        len(by_condition.get(condition, [])) == expected_pairs
        for condition in CONDITIONS
    )
    complete = (
        complete_pairs == expected_pairs and both_conditions_complete and usage_complete
    )
    claim_status = (
        "eligible"
        if complete and attempts >= 3
        else "pilot_only"
        if complete
        else "incomplete"
    )
    tokki_summary = condition_summaries["tokki"]
    control_summary = condition_summaries["control"]
    assert isinstance(tokki_summary, Mapping)
    assert isinstance(control_summary, Mapping)
    tokki_usage = tokki_summary["usage_totals"]
    control_usage = control_summary["usage_totals"]
    assert isinstance(tokki_usage, Mapping)
    assert isinstance(control_usage, Mapping)
    accepted_delta = int(tokki_summary["accepted"]) - int(control_summary["accepted"])
    total_token_reduction = _relative_reduction(
        control_usage["total_tokens"], tokki_usage["total_tokens"]
    )
    uncached_input_reduction = _relative_reduction(
        control_usage["uncached_input_tokens"],
        tokki_usage["uncached_input_tokens"],
    )
    duration_reduction = _relative_reduction(
        control_summary["agent_duration_seconds"],
        tokki_summary["agent_duration_seconds"],
    )
    if not complete:
        observed_signal = "evidence_incomplete"
    elif accepted_delta < 0:
        observed_signal = "quality_regression"
    elif accepted_delta > 0:
        observed_signal = "quality_improvement"
    elif int(tokki_summary["accepted"]) == 0:
        observed_signal = "no_accepted_repairs"
    elif total_token_reduction is not None and total_token_reduction > 0:
        observed_signal = "efficiency_improvement"
    else:
        observed_signal = "no_measured_efficiency_gain"
    return {
        "expected_pairs": expected_pairs,
        "complete_pairs": complete_pairs,
        "usage_complete": usage_complete,
        "conditions": condition_summaries,
        "comparison": {
            "observed_signal": observed_signal,
            "accepted_task_delta": accepted_delta,
            "total_token_reduction_fraction": total_token_reduction,
            "uncached_input_reduction_fraction": uncached_input_reduction,
            "agent_duration_reduction_fraction": duration_reduction,
        },
        "claim_status": claim_status,
        "claim_rule": (
            "Comparative sales claims require both conditions for every task/attempt, structured token usage, "
            "and at least three attempts per task."
        ),
    }


def _format_number(value: object, *, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _format_percentage(value: object) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "n/a"
    return f"{float(value) * 100:+.1f}%"


def render_report(manifest: Mapping[str, object]) -> str:
    summary = manifest["summary"]
    assert isinstance(summary, Mapping)
    conditions = summary["conditions"]
    assert isinstance(conditions, Mapping)
    comparison = summary["comparison"]
    assert isinstance(comparison, Mapping)
    lines = [
        "# AGILAB Tokki Agent-Efficiency Benchmark",
        "",
        f"- Run ID: `{manifest['run_id']}`",
        f"- Source commit: `{manifest['source_commit']}`",
        f"- Model: `{manifest['model']}`",
        f"- Reasoning effort: `{manifest['reasoning_effort']}`",
        f"- Claim status: **{summary['claim_status']}**",
        "",
        "This benchmark measures end-to-end AGILAB repair work. It does not measure GPU inference throughput.",
        "",
        "| Condition | Accepted / attempted | Acceptance | Uncached input tokens | Total tokens | Agent seconds | Tokens / accepted |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for condition in CONDITIONS:
        condition_summary = conditions[condition]
        assert isinstance(condition_summary, Mapping)
        usage = condition_summary["usage_totals"]
        assert isinstance(usage, Mapping)
        rate = condition_summary["acceptance_rate"]
        lines.append(
            "| "
            + " | ".join(
                (
                    condition,
                    f"{condition_summary['accepted']} / {condition_summary['attempted']}",
                    f"{float(rate) * 100:.1f}%" if rate is not None else "n/a",
                    _format_number(usage["uncached_input_tokens"]),
                    _format_number(usage["total_tokens"]),
                    _format_number(
                        condition_summary["agent_duration_seconds"], digits=1
                    ),
                    _format_number(
                        condition_summary["total_tokens_per_accepted_task"], digits=1
                    ),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Comparative signal",
            "",
            f"- Observed signal: **{comparison['observed_signal']}**",
            f"- Accepted-task delta (Tokki - control): {_format_number(comparison['accepted_task_delta'])}",
            f"- Total-token reduction: {_format_percentage(comparison['total_token_reduction_fraction'])}",
            f"- Uncached-input reduction: {_format_percentage(comparison['uncached_input_reduction_fraction'])}",
            f"- Agent-time reduction: {_format_percentage(comparison['agent_duration_reduction_fraction'])}",
        ]
    )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            f"{summary['claim_rule']} Current evidence is `{summary['claim_status']}`.",
            "Lower tokens are not a win when accepted-task quality falls. Report task success first, then tokens, time, and recovery evidence.",
            "",
            "## Reproducibility",
            "",
            "Each condition starts from a history-free archive of the same base commit. Future Git objects and hidden tests are absent from the task workspace. The driver captures the solution before applying the reference regression tests, records SHA-256 evidence, and runs identical verification commands for both conditions.",
            "",
            "The control is launched with provider-wide `TOKKI_AUTO_RUN=off` from an unrelated human shell. The driver refuses to run inside an active provider session, so inline disablement cannot masquerade as a control.",
            "",
            "## Limitations",
            "",
            "- These are historical AGILAB tasks and may not generalize to other repositories.",
            "- Public historical fixes may be present in model training data.",
            "- This is first-party evidence until an independent operator reproduces it.",
            "- Token fields come from Codex JSONL; missing usage makes the comparison incomplete.",
            "",
        ]
    )
    return "\n".join(lines)


def _selected_tasks(
    tasks: Sequence[TaskSpec], requested: Sequence[str]
) -> tuple[TaskSpec, ...]:
    if not requested:
        return tuple(tasks)
    requested_set = set(requested)
    selected = tuple(task for task in tasks if task.task_id in requested_set)
    missing = sorted(requested_set - {task.task_id for task in selected})
    if missing:
        raise BenchmarkError(f"unknown task ids: {missing}")
    return selected


def _verify_reference_task(
    repo_root: Path,
    task: TaskSpec,
    *,
    python_executable: Path,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(
        prefix=f"agilab-tokki-benchmark-{task.task_id}-"
    ) as temp_value:
        temp_root = Path(temp_value)
        base_workspace = temp_root / "base"
        prepare_workspace(repo_root, task.base_commit, base_workspace)
        apply_result = _apply_hidden_tests(
            base_workspace, _hidden_test_patch(repo_root, task)
        )
        if apply_result.returncode != 0:
            raise BenchmarkError(
                f"{task.task_id}: hidden tests do not apply to the base snapshot"
            )
        base_artifacts = temp_root / "base-artifacts"
        base_artifacts.mkdir()
        base_verification = _run_verification(
            task,
            workspace=base_workspace,
            python_executable=python_executable,
            artifact_dir=base_artifacts,
        )

        fix_workspace = temp_root / "fix"
        prepare_workspace(repo_root, task.reference_fix_commit, fix_workspace)
        fix_artifacts = temp_root / "fix-artifacts"
        fix_artifacts.mkdir()
        fix_verification = _run_verification(
            task,
            workspace=fix_workspace,
            python_executable=python_executable,
            artifact_dir=fix_artifacts,
        )
        base_fails = not bool(base_verification["passed"])
        fix_passes = bool(fix_verification["passed"])
        if not base_fails or not fix_passes:
            diagnostic_parts: list[str] = []
            for label, artifact_root, verification in (
                ("base", base_artifacts, base_verification),
                ("fix", fix_artifacts, fix_verification),
            ):
                for index, command in enumerate(verification["commands"], start=1):
                    if command["passed"]:
                        continue
                    for stream in ("stdout", "stderr"):
                        stream_path = (
                            artifact_root / f"verification-{index}.{stream}.txt"
                        )
                        content = stream_path.read_text(
                            encoding="utf-8", errors="replace"
                        )[-2000:]
                        diagnostic_parts.append(
                            f"{label} verification {index} {stream}:\n{content}"
                        )
            raise BenchmarkError(
                f"{task.task_id}: regression proof invalid "
                f"(base_fails={base_fails}, fix_passes={fix_passes}); "
                + "\n".join(diagnostic_parts)
            )
        return {
            "task_id": task.task_id,
            "base_fails": base_fails,
            "reference_fix_passes": fix_passes,
        }


def check_benchmark(args: argparse.Namespace) -> int:
    tasks = _selected_tasks(load_tasks(args.tasks), args.task)
    python_executable = _resolve_executable(args.python, label="Python")
    checks = [validate_task_provenance(args.repo_root, task) for task in tasks]
    reference_checks: list[dict[str, object]] = []
    if args.verify_reference:
        for task in tasks:
            print(
                f"verifying historical regression boundary: {task.task_id}", flush=True
            )
            reference_checks.append(
                _verify_reference_task(
                    args.repo_root,
                    task,
                    python_executable=python_executable,
                )
            )
    payload = {
        "status": "pass",
        "task_file": str(args.tasks),
        "task_file_sha256": _sha256_file(args.tasks),
        "tasks": checks,
        "reference_checks": reference_checks,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def run_benchmark(args: argparse.Namespace) -> int:
    validate_driver_environment(os.environ)
    tasks = _selected_tasks(load_tasks(args.tasks), args.task)
    python_executable = _resolve_executable(args.python, label="Python")
    codex_bin = _resolve_executable(args.codex_bin, label="Codex")
    tokki_bin = _resolve_executable(args.tokki_bin, label="Tokki")
    for task in tasks:
        validate_task_provenance(args.repo_root, task)

    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_root = args.output_dir or (DEFAULT_REPORT_ROOT / run_id)
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    preflight_dir = output_root / "preflight"
    preflight_dir.mkdir()
    doctor = _capture(
        (
            str(tokki_bin),
            "doctor",
            "--strict",
            "--allow-pending-provider-observation",
        ),
        cwd=args.repo_root,
        timeout_seconds=120,
    )
    _write_text(preflight_dir / "tokki-doctor.stdout.txt", doctor.stdout)
    _write_text(preflight_dir / "tokki-doctor.stderr.txt", doctor.stderr)
    if doctor.returncode != 0:
        raise BenchmarkError(
            "Tokki strict doctor did not pass (apart from the explicitly allowed pending "
            "provider observation); refusing to create comparative evidence"
        )
    versions: dict[str, str] = {}
    for condition in CONDITIONS:
        version = _capture(
            (str(codex_bin), "--version"),
            cwd=args.repo_root,
            env=_condition_environment(condition),
            timeout_seconds=60,
        )
        if version.returncode != 0:
            raise BenchmarkError(
                f"Codex version preflight failed for {condition}: {version.stderr}"
            )
        versions[condition] = version.stdout.strip()
    if len(set(versions.values())) != 1:
        raise BenchmarkError(f"Codex version differs between conditions: {versions}")

    schedule = [
        (task, attempt) for attempt in range(1, args.attempts + 1) for task in tasks
    ]
    rng = random.Random(args.seed)
    results: list[dict[str, object]] = []
    order_index = 0
    for task, attempt in schedule:
        condition_order = list(CONDITIONS)
        rng.shuffle(condition_order)
        for condition in condition_order:
            order_index += 1
            results.append(
                _run_condition(
                    task,
                    condition=condition,
                    attempt=attempt,
                    order_index=order_index,
                    repo_root=args.repo_root,
                    output_root=output_root,
                    codex_bin=codex_bin,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                    python_executable=python_executable,
                )
            )

    summary = summarize_results(
        results, expected_tasks=len(tasks), attempts=args.attempts
    )
    manifest: dict[str, object] = {
        "kind": MANIFEST_KIND,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "source_commit": _git_text(args.repo_root, "rev-parse", "HEAD").strip(),
        "source_tree": _git_text(args.repo_root, "rev-parse", "HEAD^{tree}").strip(),
        "working_tree_clean": not bool(
            _git_text(args.repo_root, "status", "--porcelain=v1")
        ),
        "task_file": str(args.tasks),
        "task_file_sha256": _sha256_file(args.tasks),
        "task_ids": [task.task_id for task in tasks],
        "attempts": args.attempts,
        "seed": args.seed,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "codex_versions": versions,
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "python_executable": str(python_executable),
        },
        "preflight": {
            "tokki_profile": _artifact_payload(args.repo_root / ".tokki" / "profile"),
            "tokki_doctor_stdout": _artifact_payload(
                preflight_dir / "tokki-doctor.stdout.txt"
            ),
            "tokki_doctor_stderr": _artifact_payload(
                preflight_dir / "tokki-doctor.stderr.txt"
            ),
        },
        "results": results,
        "summary": summary,
    }
    manifest_path = output_root / "manifest.json"
    report_path = output_root / "report.md"
    _write_json(manifest_path, manifest)
    _write_text(report_path, render_report(manifest))
    print(f"manifest: {manifest_path}")
    print(f"report: {report_path}")
    print(f"claim_status: {summary['claim_status']}")
    return 0 if summary["claim_status"] != "incomplete" else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Codex on historical AGILAB repairs with Tokki auto-routing enabled and with the "
            "supported provider-wide control disabled."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python tools/benchmark_tokki_agent_efficiency.py check --verify-reference
  python tools/benchmark_tokki_agent_efficiency.py run --model MODEL_ID --task dispatcher-work-size-gate --attempts 1
  python tools/benchmark_tokki_agent_efficiency.py run --model MODEL_ID --reasoning-effort high --attempts 3

Live runs must start from an unrelated human shell after every Codex or Claude
provider exits. Results are claim-eligible only with all task pairs, structured
usage, and at least three attempts. Accepted-task quality always precedes token
or duration reductions; a workspace sandbox is not a VM, so review traces for
out-of-workspace reads before using evidence publicly.
""",
    )
    parser.set_defaults(repo_root=REPO_ROOT, tasks=DEFAULT_TASKS_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check", help="validate task provenance and optional regression bounds"
    )
    check_parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    check_parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    check_parser.add_argument("--task", action="append", default=[])
    check_parser.add_argument("--python", default=sys.executable)
    check_parser.add_argument("--verify-reference", action="store_true")
    check_parser.set_defaults(func=check_benchmark)

    run_parser = subparsers.add_parser(
        "run", help="run both benchmark conditions from an unrelated human shell"
    )
    run_parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    run_parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    run_parser.add_argument("--task", action="append", default=[])
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh"),
        default="high",
    )
    run_parser.add_argument("--attempts", type=int, default=1)
    run_parser.add_argument("--seed", type=int, default=20260827)
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--output-dir", type=Path)
    run_parser.add_argument("--python", default=sys.executable)
    run_parser.add_argument("--codex-bin", default="codex")
    run_parser.add_argument("--tokki-bin", default="tokki")
    run_parser.set_defaults(func=run_benchmark)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "attempts", 1) <= 0:
        parser.error("--attempts must be positive")
    args.repo_root = args.repo_root.resolve()
    args.tasks = args.tasks.resolve()
    try:
        return int(args.func(args))
    except BenchmarkError as exc:
        print(f"benchmark_tokki_agent_efficiency: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
