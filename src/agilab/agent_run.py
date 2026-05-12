"""Agent execution trace command for AGILAB."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4


TRACE_KIND = "agilab.agent_run.v1"
DEFAULT_TIMEOUT_SECONDS = 30 * 60
SECRET_NAME_RE = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|KEY|CREDENTIAL|AUTH)", re.IGNORECASE)
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class AgentRunConfig:
    """Resolved configuration for one agent-traced command."""

    agent: str
    label: str
    command: tuple[str, ...]
    cwd: Path
    output_dir: Path
    run_id: str
    timeout_seconds: float
    env_overrides: dict[str, str] = field(default_factory=dict)
    print_only: bool = False
    json_output: bool = False
    allow_failure: bool = False
    include_command_args: bool = False


@dataclass(frozen=True)
class AgentRunResult:
    """Result and manifest for one traced command."""

    manifest: dict[str, object]
    returncode: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str, fallback: str) -> str:
    clean = SAFE_NAME_RE.sub("-", value.strip()).strip(".-_")
    return clean or fallback


def _new_run_id(agent: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"agent-{_slug(agent, 'agent')}-{stamp}-{uuid4().hex[:8]}"


def _default_log_root() -> Path:
    return Path(os.environ.get("AGILAB_LOG_ABS", str(Path.home() / "log"))).expanduser()


def _default_output_dir(agent: str, run_id: str) -> Path:
    return _default_log_root() / "agents" / _slug(agent, "agent") / run_id


def _detect_repo_root(start: Path) -> Path | None:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "agilab").is_dir():
            return candidate
    return None


def _parse_env_overrides(raw_values: Sequence[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in raw_values:
        if "=" not in raw:
            raise ValueError(f"Invalid --env value {raw!r}; expected KEY=VALUE")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid --env value {raw!r}; KEY cannot be empty")
        env[key] = value
    return env


def _redacted_env_payload(env_overrides: dict[str, str]) -> dict[str, object]:
    return {
        "keys": sorted(env_overrides),
        "value_redacted": {key: True for key in sorted(env_overrides)},
        "secret_like": {key: bool(SECRET_NAME_RE.search(key)) for key in sorted(env_overrides)},
    }


def _file_payload(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "size_bytes": 0,
            "line_count": 0,
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "line_count": len(text.splitlines()),
    }


def _argv_hash(command: Sequence[str]) -> str:
    payload = json.dumps(list(command), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _display_argv(config: AgentRunConfig) -> list[str]:
    if config.include_command_args or len(config.command) <= 1:
        return list(config.command)
    return [config.command[0], f"<{len(config.command) - 1} argument(s) redacted>"]


def _command_payload(config: AgentRunConfig) -> dict[str, object]:
    return {
        "label": config.label,
        "argv": _display_argv(config),
        "argv_redacted": not config.include_command_args and len(config.command) > 1,
        "argv_count": len(config.command),
        "argv_sha256": _argv_hash(config.command),
        "cwd": str(config.cwd),
        "env_overrides": _redacted_env_payload(config.env_overrides),
    }


def _environment_payload(cwd: Path) -> dict[str, object]:
    repo_root = _detect_repo_root(cwd)
    return {
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "repo_root": str(repo_root) if repo_root else None,
    }


def build_planned_manifest(config: AgentRunConfig) -> dict[str, object]:
    """Build a trace manifest without executing the command."""
    return {
        "schema_version": 1,
        "kind": TRACE_KIND,
        "run_id": config.run_id,
        "agent": config.agent,
        "label": config.label,
        "status": "planned",
        "returncode": None,
        "command": _command_payload(config),
        "environment": _environment_payload(config.cwd),
        "timing": {
            "started_at": None,
            "finished_at": None,
            "duration_seconds": 0.0,
            "timeout_seconds": config.timeout_seconds,
        },
        "artifacts": {
            "manifest": str(config.output_dir / "agent_run_manifest.json"),
            "stdout": str(config.output_dir / "stdout.txt"),
            "stderr": str(config.output_dir / "stderr.txt"),
        },
        "notes": [
            "Command arguments are redacted by default; argv_sha256 preserves comparison without exposing prompts.",
            "Command output is stored in local artifact files, not embedded in the manifest.",
            "Environment override values are redacted from the manifest.",
        ],
    }


def run_agent_command(
    config: AgentRunConfig,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    perf_counter: Callable[[], float] = time.perf_counter,
) -> AgentRunResult:
    """Execute an agent command and write a local trace manifest."""
    config.output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = config.output_dir / "stdout.txt"
    stderr_path = config.output_dir / "stderr.txt"
    manifest_path = config.output_dir / "agent_run_manifest.json"

    env = os.environ.copy()
    env.update(config.env_overrides)
    started_at = _utc_now()
    started = perf_counter()
    timed_out = False
    try:
        proc = runner(
            list(config.command),
            cwd=str(config.cwd),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=config.timeout_seconds,
            check=False,
        )
        returncode = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        raw_stdout = exc.stdout or ""
        raw_stderr = exc.stderr or ""
        stdout = raw_stdout if isinstance(raw_stdout, str) else raw_stdout.decode("utf-8", "replace")
        stderr = raw_stderr if isinstance(raw_stderr, str) else raw_stderr.decode("utf-8", "replace")
        stderr = (stderr + f"\nTimed out after {config.timeout_seconds:.0f}s").strip()
    duration_seconds = perf_counter() - started
    finished_at = _utc_now()

    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    status = "pass" if returncode == 0 else "timeout" if timed_out else "fail"
    manifest: dict[str, object] = {
        "schema_version": 1,
        "kind": TRACE_KIND,
        "run_id": config.run_id,
        "agent": config.agent,
        "label": config.label,
        "status": status,
        "returncode": returncode,
        "command": _command_payload(config),
        "environment": _environment_payload(config.cwd),
        "timing": {
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "timeout_seconds": config.timeout_seconds,
        },
        "artifacts": {
            "manifest": str(manifest_path),
            "stdout": _file_payload(stdout_path),
            "stderr": _file_payload(stderr_path),
        },
        "notes": [
            "Command arguments are redacted by default; argv_sha256 preserves comparison without exposing prompts.",
            "Command output is stored in local artifact files, not embedded in the manifest.",
            "Environment override values are redacted from the manifest.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return AgentRunResult(manifest=manifest, returncode=returncode)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a local coding-agent command and record an AGILAB trace manifest "
            "with redacted environment metadata and output artifacts."
        )
    )
    parser.add_argument("--agent", default="agent", help="Agent/tool name, for example codex, aider, or opencode.")
    parser.add_argument("--label", default="Agent run", help="Human-readable label for this run.")
    parser.add_argument("--run-id", default="", help="Stable run id. Defaults to an agent/timestamp id.")
    parser.add_argument("--output-dir", default="", help="Directory where the manifest and output files are written.")
    parser.add_argument("--cwd", default="", help="Working directory for the command. Defaults to the current directory.")
    parser.add_argument("--timeout", type=float, default=float(DEFAULT_TIMEOUT_SECONDS), help="Command timeout in seconds.")
    parser.add_argument("--env", action="append", default=[], help="Environment override passed to the command as KEY=VALUE.")
    parser.add_argument("--json", action="store_true", help="Print the trace manifest JSON.")
    parser.add_argument("--print-only", action="store_true", help="Print the planned trace without executing the command.")
    parser.add_argument("--allow-failure", action="store_true", help="Return 0 even if the traced command fails.")
    parser.add_argument(
        "--include-command-args",
        action="store_true",
        help="Store full command arguments in the manifest. By default only the executable and an argv hash are kept.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after --.")
    return parser


def parse_args(argv: Sequence[str]) -> AgentRunConfig:
    parser = _build_parser()
    args = parser.parse_args(list(argv))
    command = tuple(args.command)
    if command[:1] == ("--",):
        command = command[1:]
    if not command:
        parser.error("command is required after --")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")

    cwd = Path(args.cwd).expanduser().resolve() if args.cwd else Path.cwd().resolve()
    if not cwd.is_dir():
        parser.error(f"--cwd is not a directory: {cwd}")
    env_overrides = _parse_env_overrides(args.env)
    run_id = _slug(args.run_id, "agent-run") if args.run_id.strip() else _new_run_id(args.agent)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else _default_output_dir(args.agent, run_id)
    return AgentRunConfig(
        agent=args.agent,
        label=args.label,
        command=command,
        cwd=cwd,
        output_dir=output_dir,
        run_id=run_id,
        timeout_seconds=float(args.timeout),
        env_overrides=env_overrides,
        print_only=bool(args.print_only),
        json_output=bool(args.json),
        allow_failure=bool(args.allow_failure),
        include_command_args=bool(args.include_command_args),
    )


def render_human(manifest: dict[str, object]) -> str:
    status = manifest.get("status")
    artifacts = manifest.get("artifacts", {})
    manifest_path = artifacts.get("manifest") if isinstance(artifacts, dict) else None
    lines = [
        "AGILAB agent run",
        f"agent: {manifest.get('agent')}",
        f"run id: {manifest.get('run_id')}",
        f"status: {status}",
    ]
    if manifest_path:
        lines.append(f"manifest: {manifest_path}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(sys.argv[1:] if argv is None else argv)
    if config.print_only:
        manifest = build_planned_manifest(config)
        print(json.dumps(manifest, indent=2, sort_keys=True) if config.json_output else render_human(manifest))
        return 0

    result = run_agent_command(config)
    print(json.dumps(result.manifest, indent=2, sort_keys=True) if config.json_output else render_human(result.manifest))
    if result.returncode == 0 or config.allow_failure:
        return 0
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
