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
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from agilab.agent_config import load_agent_config, resolve_agent_provider
from agilab.agent_tool_safety import evaluate_tool_permission, normalize_permission_level
from agilab.agent_trace import AgentTraceStore, trace_artifact_payload
from agilab.secret_uri import redact_text


TRACE_KIND = "agilab.agent_run.v1"
MANIFEST_FILENAME = "agent_run_manifest.json"
STDOUT_FILENAME = "stdout.txt"
STDERR_FILENAME = "stderr.txt"
DEFAULT_TIMEOUT_SECONDS = 30 * 60
SECRET_NAME_RE = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|KEY|CREDENTIAL|AUTH)", re.IGNORECASE)
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
SHELL_EXECUTABLES = frozenset({"bash", "cmd", "fish", "powershell", "powershell.exe", "pwsh", "sh", "zsh"})
PYTHON_EXECUTABLE_RE = re.compile(r"^python(?:\d+(?:\.\d+)?)?(?:\.exe)?$", re.IGNORECASE)
DESTRUCTIVE_SHELL_RE = re.compile(
    r"(?i)(?:^|[\s;&|()])(?:"
    r"rm(?:\s|$)"
    r"|del(?:\s|$)"
    r"|erase(?:\s|$)"
    r"|rmdir(?:\s|$)"
    r"|remove-item(?:\s|$)"
    r"|pkill(?:\s|$)"
    r"|killall(?:\s|$)"
    r"|git\s+(?:reset\s+--hard|clean(?:\s|$)|branch\s+-D|push\s+--force(?:-with-lease)?)"
    r"|docker\s+(?:rm|rmi|system\s+prune|volume\s+rm)(?:\s|$)"
    r"|kubectl\s+delete(?:\s|$)"
    r"|pip\s+uninstall(?:\s|$)"
    r"|uv\s+pip\s+uninstall(?:\s|$)"
    r"|npm\s+uninstall(?:\s|$)"
    r")"
)
DESTRUCTIVE_PYTHON_RE = re.compile(
    r"(?i)(?:"
    r"\bshutil\.rmtree\b"
    r"|\bos\.(?:remove|unlink|rmdir)\b"
    r"|\bPath\([^)]*\)\.(?:unlink|rmdir)\b"
    r"|\bsubprocess\.(?:run|call|Popen)\s*\([^)]*(?:rm|git\s+reset|git\s+clean|kubectl\s+delete)"
    r")"
)


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
    tags: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
    protocol_adapters: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    provider: str = ""
    model: str = ""
    permission_level: str = "safe"
    confirmation: str = ""
    trace_enabled: bool = True
    redact_output: bool = True
    provider_capability: dict[str, object] = field(default_factory=dict)
    config_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentRunResult:
    """Result and manifest for one traced command."""

    manifest: dict[str, object]
    returncode: int


@dataclass(frozen=True)
class AgentRunSummary:
    """Compact read-side view of an agent-run manifest."""

    run_id: str
    agent: str
    label: str
    status: str
    returncode: int | None
    manifest_path: Path
    stdout_path: Path | None
    stderr_path: Path | None
    trace_events_path: Path | None
    duration_seconds: float
    tags: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


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


def _parse_key_values(raw_values: Sequence[str], *, option_name: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in raw_values:
        if "=" not in raw:
            raise ValueError(f"Invalid {option_name} value {raw!r}; expected KEY=VALUE")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid {option_name} value {raw!r}; KEY cannot be empty")
        env[key] = value
    return env


def _parse_env_overrides(raw_values: Sequence[str]) -> dict[str, str]:
    return _parse_key_values(raw_values, option_name="--env")


def _parse_metadata(raw_values: Sequence[str]) -> dict[str, str]:
    return _parse_key_values(raw_values, option_name="--metadata")


def _normalize_tags(raw_values: Sequence[str]) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        clean = _slug(raw, "")
        key = clean.casefold()
        if clean and key not in seen:
            tags.append(clean)
            seen.add(key)
    return tuple(tags)


def _normalize_slug_values(raw_values: Sequence[str]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        clean = _slug(raw, "").casefold()
        if clean and clean not in seen:
            values.append(clean)
            seen.add(clean)
    return tuple(values)


def _redacted_env_payload(env_overrides: dict[str, str]) -> dict[str, object]:
    return {
        "keys": sorted(env_overrides),
        "value_redacted": {key: True for key in sorted(env_overrides)},
        "secret_like": {key: bool(SECRET_NAME_RE.search(key)) for key in sorted(env_overrides)},
    }


def _context_payload(config: AgentRunConfig) -> dict[str, object]:
    keys = sorted(config.metadata)
    metadata: dict[str, str] = {}
    metadata_redacted: dict[str, bool] = {}
    for key in keys:
        value = config.metadata[key]
        if SECRET_NAME_RE.search(key):
            metadata[key] = "<redacted>"
            metadata_redacted[key] = True
            continue
        redacted_value = redact_text(value)
        metadata[key] = redacted_value
        metadata_redacted[key] = redacted_value != value
    payload: dict[str, object] = {
        "tags": list(config.tags),
        "metadata": metadata,
        "metadata_redacted": metadata_redacted,
        "agent_config": {
            "permission_level": config.permission_level,
            "trace_enabled": config.trace_enabled,
            "config_paths": list(config.config_paths),
        },
    }
    if config.provider or config.model or config.provider_capability:
        payload["provider"] = {
            "provider": config.provider,
            "model": config.model,
            "capability": config.provider_capability,
        }
    return payload


def _protocol_payload(config: AgentRunConfig) -> dict[str, object]:
    return {
        "adapters": list(config.protocol_adapters),
        "capabilities": list(config.capabilities),
        "mode": "metadata-only" if config.protocol_adapters or config.capabilities else "none",
        "dependency_boundary": (
            "Protocol bridges are recorded as manifest metadata here; concrete MCP, A2A, "
            "AG-UI, FastAPI, or similar adapters must stay behind optional integrations."
        ),
    }


def _event_payload(
    sequence: int,
    event_type: str,
    *,
    timestamp: str,
    status: str,
    **fields: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "sequence": sequence,
        "timestamp": timestamp,
        "type": event_type,
        "status": status,
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    return payload


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


def create_agent_run_config(
    command: Sequence[str],
    *,
    agent: str = "agent",
    label: str = "Agent run",
    cwd: Path | str | None = None,
    output_dir: Path | str | None = None,
    run_id: str | None = None,
    timeout_seconds: float = float(DEFAULT_TIMEOUT_SECONDS),
    env_overrides: Mapping[str, str] | None = None,
    print_only: bool = False,
    json_output: bool = False,
    allow_failure: bool = False,
    include_command_args: bool = False,
    tags: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
    protocol_adapters: Sequence[str] = (),
    capabilities: Sequence[str] = (),
    provider: str | None = None,
    model: str | None = None,
    permission_level: str | None = None,
    confirmation: str | None = None,
    trace_enabled: bool | None = None,
    redact_output: bool = True,
) -> AgentRunConfig:
    """Build a validated agent-run config with CLI-compatible defaults.

    This is the Python API equivalent of ``agilab agent-run`` argument
    resolution. It intentionally accepts an argv sequence, not a shell string,
    so callers do not accidentally depend on shell parsing or quoting.
    """

    if isinstance(command, str):
        raise ValueError("command must be an argv sequence, not a shell string")
    command_tuple = tuple(str(part) for part in command)
    if not command_tuple:
        raise ValueError("command cannot be empty")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    resolved_cwd = Path(cwd).expanduser().resolve() if cwd is not None else Path.cwd().resolve()
    if not resolved_cwd.is_dir():
        raise ValueError(f"cwd is not a directory: {resolved_cwd}")

    agent_config = load_agent_config(resolved_cwd)
    provider_name = ""
    model_name = ""
    provider_capability: dict[str, object] = {}
    has_provider_context = any(
        str(value or "").strip()
        for value in (provider, model, agent_config.default_provider, agent_config.default_model)
    )
    if has_provider_context:
        resolved_provider = resolve_agent_provider(agent_config, provider=provider, model=model)
        provider_name = resolved_provider.provider
        model_name = resolved_provider.model
        provider_capability = resolved_provider.capability.as_dict()

    clean_run_id = _slug(run_id or "", "agent-run") if run_id and run_id.strip() else _new_run_id(agent)
    resolved_output_dir = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else _default_output_dir(agent, clean_run_id)
    )

    return AgentRunConfig(
        agent=agent,
        label=label,
        command=command_tuple,
        cwd=resolved_cwd,
        output_dir=resolved_output_dir,
        run_id=clean_run_id,
        timeout_seconds=float(timeout_seconds),
        env_overrides=dict(env_overrides or {}),
        print_only=bool(print_only),
        json_output=bool(json_output),
        allow_failure=bool(allow_failure),
        include_command_args=bool(include_command_args),
        tags=_normalize_tags(tags),
        metadata=dict(metadata or {}),
        protocol_adapters=_normalize_slug_values(protocol_adapters),
        capabilities=_normalize_slug_values(capabilities),
        provider=provider_name,
        model=model_name,
        permission_level=normalize_permission_level(permission_level or agent_config.permission_level),
        confirmation=str(confirmation or ""),
        trace_enabled=agent_config.trace_enabled if trace_enabled is None else bool(trace_enabled),
        redact_output=bool(redact_output),
        provider_capability=provider_capability,
        config_paths=tuple(str(path) for path in agent_config.config_paths),
    )


def _environment_payload(cwd: Path) -> dict[str, object]:
    repo_root = _detect_repo_root(cwd)
    return {
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "repo_root": str(repo_root) if repo_root else None,
    }


def _artifact_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "manifest": output_dir / MANIFEST_FILENAME,
        "stdout": output_dir / STDOUT_FILENAME,
        "stderr": output_dir / STDERR_FILENAME,
    }


def _command_permission_action(config: AgentRunConfig) -> str:
    command_name = Path(config.command[0]).name if config.command else "command"
    return " ".join(("run", "agent", command_name))


def _is_destructive_git_args(args: Sequence[str]) -> bool:
    if not args:
        return False
    subcommand = args[0].lower()
    if subcommand == "reset" and "--hard" in args:
        return True
    if subcommand == "clean":
        return True
    if subcommand == "branch" and any(arg in {"-D", "--delete", "--force"} for arg in args[1:]):
        return True
    if subcommand == "push" and any(arg.startswith("--force") for arg in args[1:]):
        return True
    return subcommand in {"rm", "gc"} and any(arg in {"--prune=now", "--force"} for arg in args[1:])


def _is_destructive_docker_args(args: Sequence[str]) -> bool:
    if not args:
        return False
    if args[0].lower() in {"rm", "rmi"}:
        return True
    if len(args) >= 2 and args[0].lower() == "system" and args[1].lower() == "prune":
        return True
    return len(args) >= 2 and args[0].lower() == "volume" and args[1].lower() == "rm"


def _is_destructive_uv_args(args: Sequence[str]) -> bool:
    lowered = [arg.lower() for arg in args]
    return ("pip" in lowered and "uninstall" in lowered) or lowered[:2] == ["cache", "clean"]


def _inline_python_snippets(args: Sequence[str]) -> list[str]:
    snippets: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-c" and index + 1 < len(args):
            snippets.append(args[index + 1])
            index += 2
            continue
        if arg.startswith("-c") and len(arg) > 2:
            snippets.append(arg[2:])
        index += 1
    return snippets


def _command_content_requires_operator(command: Sequence[str]) -> bool:
    if not command:
        return False
    executable = Path(command[0]).name.lower()
    args = tuple(str(arg) for arg in command[1:])
    if executable == "git":
        return _is_destructive_git_args(args)
    if executable == "docker":
        return _is_destructive_docker_args(args)
    if executable == "kubectl":
        return bool(args and args[0].lower() == "delete")
    if executable in {"pip", "pip3"}:
        return bool(args and args[0].lower() == "uninstall")
    if executable == "uv":
        return _is_destructive_uv_args(args)
    if executable == "npm":
        return bool(args and args[0].lower() == "uninstall")
    if executable in SHELL_EXECUTABLES:
        return bool(DESTRUCTIVE_SHELL_RE.search(" ".join(args)))
    if PYTHON_EXECUTABLE_RE.fullmatch(executable):
        return any(
            DESTRUCTIVE_PYTHON_RE.search(snippet) or DESTRUCTIVE_SHELL_RE.search(snippet)
            for snippet in _inline_python_snippets(args)
        )
    return False


def _permission_payload(config: AgentRunConfig) -> dict[str, object]:
    command_requires_operator = _command_content_requires_operator(config.command)
    decision = evaluate_tool_permission(
        _command_permission_action(config),
        {"argv_sha256": _argv_hash(config.command), "cwd": str(config.cwd)},
        level=config.permission_level,
        confirmation=config.confirmation or None,
        metadata={"permission_tier": "operator"} if command_requires_operator else None,
    )
    payload: dict[str, object] = {
        "action": decision.action,
        "allowed": decision.allowed,
        "tier": decision.tier,
        "level": decision.level,
        "reason": decision.reason,
    }
    if command_requires_operator:
        payload["command_policy"] = "operator-gated"
        payload["command_policy_reason"] = "destructive command content detected"
    if decision.confirmation_token:
        payload["confirmation_token"] = decision.confirmation_token
    return payload


def build_planned_manifest(config: AgentRunConfig) -> dict[str, object]:
    """Build a trace manifest without executing the command."""
    artifacts = _artifact_paths(config.output_dir)
    planned_at = _utc_now()
    permission = _permission_payload(config)
    return {
        "schema_version": 1,
        "kind": TRACE_KIND,
        "run_id": config.run_id,
        "agent": config.agent,
        "label": config.label,
        "status": "planned",
        "returncode": None,
        "command": _command_payload(config),
        "context": _context_payload(config),
        "protocols": _protocol_payload(config),
        "permission": permission,
        "environment": _environment_payload(config.cwd),
        "timing": {
            "started_at": None,
            "finished_at": None,
            "duration_seconds": 0.0,
            "timeout_seconds": config.timeout_seconds,
        },
        "artifacts": {
            "manifest": str(artifacts["manifest"]),
            "stdout": str(artifacts["stdout"]),
            "stderr": str(artifacts["stderr"]),
            "agent_trace": trace_artifact_payload(config.output_dir),
        },
        "events": [
            _event_payload(
                1,
                "agent.run.planned",
                timestamp=planned_at,
                status="planned",
                protocol_adapters=list(config.protocol_adapters),
                capabilities=list(config.capabilities),
                permission=permission,
            )
        ],
        "notes": [
            "Command arguments are redacted by default; argv_sha256 preserves comparison without exposing prompts.",
            "Command output is stored in local artifact files, not embedded in the manifest.",
            "Command output artifacts are redacted by default; pass --include-raw-output only for safe local diagnostics.",
            "Environment override values are redacted from the manifest.",
            "Agent trace events are stored as append-only NDJSON when trace_enabled is true.",
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
    artifacts = _artifact_paths(config.output_dir)
    stdout_path = artifacts["stdout"]
    stderr_path = artifacts["stderr"]
    manifest_path = artifacts["manifest"]
    trace_store = AgentTraceStore(
        config.output_dir,
        run_id=config.run_id,
        agent=config.agent,
        label=config.label,
        provider=config.provider,
        model=config.model,
    )
    if config.trace_enabled:
        trace_store.initialize(
            {
                "tags": list(config.tags),
                "permission_level": config.permission_level,
                "provider": config.provider,
                "model": config.model,
            }
        )

    env = os.environ.copy()
    env.update(config.env_overrides)
    started_at = _utc_now()
    started = perf_counter()
    permission = _permission_payload(config)
    events: list[dict[str, object]] = [
        _event_payload(
            1,
            "agent.run.started",
            timestamp=started_at,
            status="running",
            protocol_adapters=list(config.protocol_adapters),
            capabilities=list(config.capabilities),
        )
    ]
    timed_out = False
    if config.trace_enabled:
        trace_store.append(
            "session_start",
            message=config.label,
            metadata={
                "agent": config.agent,
                "tags": list(config.tags),
                "permission_level": config.permission_level,
            },
        )
        trace_store.append(
            "command_start",
            message=config.label,
            metadata=_command_payload(config),
        )
        trace_store.append(
            "permission_request",
            message="agent command permission check",
            metadata=permission,
        )
        trace_store.append(
            "permission_resolved",
            status="pass" if permission["allowed"] else "denied",
            message=str(permission["reason"]),
            metadata=permission,
        )

    if not permission["allowed"]:
        returncode = 126
        stdout = ""
        stderr = str(permission["reason"])
        if permission.get("confirmation_token"):
            stderr += f"\nconfirmation_token={permission['confirmation_token']}"
        duration_seconds = perf_counter() - started
        finished_at = _utc_now()
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        events.append(
            _event_payload(
                2,
                "agent.permission.denied",
                timestamp=finished_at,
                status="denied",
                permission=permission,
            )
        )
        events.append(
            _event_payload(
                3,
                "agent.artifacts.written",
                timestamp=finished_at,
                status="denied",
                artifacts=["stdout", "stderr"],
            )
        )
        if config.trace_enabled:
            trace_store.append(
                "session_end",
                status="denied",
                message="agent run denied by permission policy",
                metadata={"returncode": returncode},
            )
        manifest: dict[str, object] = {
            "schema_version": 1,
            "kind": TRACE_KIND,
            "run_id": config.run_id,
            "agent": config.agent,
            "label": config.label,
            "status": "denied",
            "returncode": returncode,
            "command": _command_payload(config),
            "context": _context_payload(config),
            "protocols": _protocol_payload(config),
            "permission": permission,
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
                "agent_trace": trace_artifact_payload(config.output_dir),
            },
            "events": events,
            "notes": [
                "Command execution was denied by the configured agent permission policy.",
                "Command arguments are redacted by default; argv_sha256 preserves comparison without exposing prompts.",
                "Command output artifacts are redacted by default; pass --include-raw-output only for safe local diagnostics.",
                "Environment override values are redacted from the manifest.",
                "Agent trace events are stored as append-only NDJSON when trace_enabled is true.",
            ],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return AgentRunResult(manifest=manifest, returncode=returncode)

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
    events.append(
        _event_payload(
            2,
            "agent.command.timeout" if timed_out else "agent.command.completed",
            timestamp=finished_at,
            status="timeout" if timed_out else "completed",
            returncode=returncode,
            duration_seconds=duration_seconds,
        )
    )

    output_stdout = redact_text(stdout) if config.redact_output else stdout
    output_stderr = redact_text(stderr) if config.redact_output else stderr
    stdout_path.write_text(output_stdout, encoding="utf-8")
    stderr_path.write_text(output_stderr, encoding="utf-8")
    status = "pass" if returncode == 0 else "timeout" if timed_out else "fail"
    events.append(
        _event_payload(
            3,
            "agent.artifacts.written",
            timestamp=finished_at,
            status=status,
            artifacts=["stdout", "stderr"],
        )
    )
    if config.trace_enabled:
        trace_store.append(
            "command_done",
            status=status,
            message=f"command finished with returncode {returncode}",
            metadata={
                "returncode": returncode,
                "stdout": _file_payload(stdout_path),
                "stderr": _file_payload(stderr_path),
            },
        )
        trace_store.append(
            "session_end",
            status=status,
            message=f"agent run {status}",
            metadata={"returncode": returncode},
        )
    manifest: dict[str, object] = {
        "schema_version": 1,
        "kind": TRACE_KIND,
        "run_id": config.run_id,
        "agent": config.agent,
        "label": config.label,
        "status": status,
        "returncode": returncode,
        "command": _command_payload(config),
        "context": _context_payload(config),
        "protocols": _protocol_payload(config),
        "permission": permission,
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
            "agent_trace": trace_artifact_payload(config.output_dir),
        },
        "events": events,
        "notes": [
            "Command arguments are redacted by default; argv_sha256 preserves comparison without exposing prompts.",
            "Command output is stored in local artifact files, not embedded in the manifest.",
            "Command output artifacts are redacted by default; pass --include-raw-output only for safe local diagnostics.",
            "Environment override values are redacted from the manifest.",
            "Agent trace events are stored as append-only NDJSON when trace_enabled is true.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return AgentRunResult(manifest=manifest, returncode=returncode)


def trace_agent_run(
    command: Sequence[str],
    *,
    agent: str = "agent",
    label: str = "Agent run",
    cwd: Path | str | None = None,
    output_dir: Path | str | None = None,
    run_id: str | None = None,
    timeout_seconds: float = float(DEFAULT_TIMEOUT_SECONDS),
    env_overrides: Mapping[str, str] | None = None,
    allow_failure: bool = False,
    include_command_args: bool = False,
    tags: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
    protocol_adapters: Sequence[str] = (),
    capabilities: Sequence[str] = (),
    provider: str | None = None,
    model: str | None = None,
    permission_level: str | None = None,
    confirmation: str | None = None,
    trace_enabled: bool | None = None,
    redact_output: bool = True,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    perf_counter: Callable[[], float] = time.perf_counter,
) -> AgentRunResult:
    """Trace an agent command directly from Python and write AGILAB evidence."""

    config = create_agent_run_config(
        command,
        agent=agent,
        label=label,
        cwd=cwd,
        output_dir=output_dir,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
        env_overrides=env_overrides,
        allow_failure=allow_failure,
        include_command_args=include_command_args,
        tags=tags,
        metadata=metadata,
        protocol_adapters=protocol_adapters,
        capabilities=capabilities,
        provider=provider,
        model=model,
        permission_level=permission_level,
        confirmation=confirmation,
        trace_enabled=trace_enabled,
        redact_output=redact_output,
    )
    return run_agent_command(config, runner=runner, perf_counter=perf_counter)


def load_agent_run_manifest(path: Path | str) -> dict[str, object]:
    """Load an agent-run manifest from a manifest file or run directory."""

    candidate = Path(path).expanduser()
    manifest_path = candidate / MANIFEST_FILENAME if candidate.is_dir() else candidate
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Agent run manifest must be a JSON object: {manifest_path}")
    if payload.get("kind") != TRACE_KIND:
        raise ValueError(f"Unsupported agent run manifest kind in {manifest_path}: {payload.get('kind')!r}")
    return payload


def _path_from_artifact(value: object) -> Path | None:
    if isinstance(value, str) and value:
        return Path(value)
    if isinstance(value, dict):
        raw_path = value.get("path")
        if isinstance(raw_path, str) and raw_path:
            return Path(raw_path)
    return None


def summarize_agent_run(manifest_or_path: dict[str, object] | Path | str) -> AgentRunSummary:
    """Return a compact, typed summary for an agent-run manifest."""

    if isinstance(manifest_or_path, dict):
        manifest = manifest_or_path
    else:
        manifest = load_agent_run_manifest(manifest_or_path)

    artifacts = manifest.get("artifacts", {})
    artifact_map = artifacts if isinstance(artifacts, dict) else {}
    context = manifest.get("context", {})
    context_map = context if isinstance(context, dict) else {}
    timing = manifest.get("timing", {})
    timing_map = timing if isinstance(timing, dict) else {}
    raw_tags = context_map.get("tags", [])
    raw_metadata = context_map.get("metadata", {})

    manifest_path = _path_from_artifact(artifact_map.get("manifest")) or Path("")
    trace_payload = artifact_map.get("agent_trace")
    trace_events_path = None
    if isinstance(trace_payload, dict):
        raw_events_path = trace_payload.get("events")
        if isinstance(raw_events_path, str) and raw_events_path:
            trace_events_path = Path(raw_events_path)
    return AgentRunSummary(
        run_id=str(manifest.get("run_id") or ""),
        agent=str(manifest.get("agent") or ""),
        label=str(manifest.get("label") or ""),
        status=str(manifest.get("status") or ""),
        returncode=manifest.get("returncode") if isinstance(manifest.get("returncode"), int) else None,
        manifest_path=manifest_path,
        stdout_path=_path_from_artifact(artifact_map.get("stdout")),
        stderr_path=_path_from_artifact(artifact_map.get("stderr")),
        trace_events_path=trace_events_path,
        duration_seconds=float(timing_map.get("duration_seconds") or 0.0),
        tags=tuple(str(tag) for tag in raw_tags) if isinstance(raw_tags, list) else (),
        metadata=dict(raw_metadata) if isinstance(raw_metadata, dict) else {},
    )


def find_agent_run_manifests(
    root: Path | str | None = None,
    *,
    agent: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> list[Path]:
    """Find agent-run manifest files, newest first."""

    explicit_root = root is not None
    search_root = Path(root).expanduser() if explicit_root else _default_log_root() / "agents"
    if agent and not explicit_root:
        search_root = search_root / _slug(agent, "agent")
    if not search_root.exists():
        return []
    candidates = [
        path
        for path in search_root.rglob(MANIFEST_FILENAME)
        if path.is_file()
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if agent or status:
        filtered: list[Path] = []
        for path in candidates:
            try:
                manifest = load_agent_run_manifest(path)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if agent and manifest.get("agent") != agent:
                continue
            if manifest.get("status") == status:
                filtered.append(path)
            elif not status:
                filtered.append(path)
        candidates = filtered
    return candidates[:limit] if limit is not None else candidates


def list_agent_runs(
    root: Path | str | None = None,
    *,
    agent: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> list[AgentRunSummary]:
    """Return compact summaries for agent-run manifests, newest first."""

    summaries: list[AgentRunSummary] = []
    for path in find_agent_run_manifests(root, agent=agent, status=status, limit=limit):
        try:
            summaries.append(summarize_agent_run(load_agent_run_manifest(path)))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return summaries


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
    parser.add_argument("--metadata", action="append", default=[], help="Structured manifest context as KEY=VALUE.")
    parser.add_argument("--tag", action="append", default=[], help="Tag stored in the manifest context. May be repeated.")
    parser.add_argument(
        "--protocol-adapter",
        action="append",
        default=[],
        help="Protocol bridge observed or intended for this run, for example mcp, a2a, ag-ui, or fastapi.",
    )
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        help="Capability exercised by this run, for example app-as-tool, notebook-export, or evidence-review.",
    )
    parser.add_argument("--provider", default="", help="Optional agent provider alias or type to stamp in evidence.")
    parser.add_argument("--model", default="", help="Optional agent model id to stamp in evidence.")
    parser.add_argument(
        "--permission-level",
        default="",
        help=(
            "Agent permission level: readonly, safe, standard, or operator. "
            "Actual command execution requires standard or higher."
        ),
    )
    parser.add_argument(
        "--confirmation",
        default="",
        help="Explicit confirmation token required when the command is classified as operator-gated.",
    )
    parser.add_argument("--no-trace", action="store_true", help="Do not write the append-only agent_events.ndjson trace.")
    parser.add_argument("--json", action="store_true", help="Print the trace manifest JSON.")
    parser.add_argument("--print-only", action="store_true", help="Print the planned trace without executing the command.")
    parser.add_argument("--allow-failure", action="store_true", help="Return 0 even if the traced command fails.")
    parser.add_argument(
        "--include-command-args",
        action="store_true",
        help="Store full command arguments in the manifest. By default only the executable and an argv hash are kept.",
    )
    parser.add_argument(
        "--include-raw-output",
        action="store_true",
        help="Write raw stdout/stderr artifacts. By default output artifacts are redacted.",
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

    try:
        return create_agent_run_config(
            command,
            agent=args.agent,
            label=args.label,
            cwd=Path(args.cwd).expanduser().resolve() if args.cwd else None,
            output_dir=Path(args.output_dir).expanduser().resolve() if args.output_dir else None,
            run_id=args.run_id,
            timeout_seconds=float(args.timeout),
            env_overrides=_parse_env_overrides(args.env),
            print_only=bool(args.print_only),
            json_output=bool(args.json),
            allow_failure=bool(args.allow_failure),
            include_command_args=bool(args.include_command_args),
            tags=args.tag,
            metadata=_parse_metadata(args.metadata),
            protocol_adapters=args.protocol_adapter,
            capabilities=args.capability,
            provider=args.provider or None,
            model=args.model or None,
            permission_level=args.permission_level or None,
            confirmation=args.confirmation or None,
            trace_enabled=False if args.no_trace else None,
            redact_output=not bool(args.include_raw_output),
        )
    except ValueError as exc:
        parser.error(str(exc))


def _build_list_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List AGILAB agent-run evidence manifests.")
    parser.add_argument("--root", default="", help="Root directory to scan. Defaults to ~/log/agents.")
    parser.add_argument("--agent", default="", help="Only list runs for this agent.")
    parser.add_argument("--status", default="", choices=["", "planned", "pass", "fail", "timeout", "denied"], help="Only list runs with this status.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of runs to list.")
    parser.add_argument("--json", action="store_true", help="Print summaries as JSON.")
    return parser


def _summary_payload(summary: AgentRunSummary) -> dict[str, object]:
    return {
        "run_id": summary.run_id,
        "agent": summary.agent,
        "label": summary.label,
        "status": summary.status,
        "returncode": summary.returncode,
        "manifest": str(summary.manifest_path),
        "stdout": str(summary.stdout_path) if summary.stdout_path else None,
        "stderr": str(summary.stderr_path) if summary.stderr_path else None,
        "trace_events": str(summary.trace_events_path) if summary.trace_events_path else None,
        "duration_seconds": summary.duration_seconds,
        "tags": list(summary.tags),
        "metadata": summary.metadata,
    }


def _render_summary_table(summaries: Sequence[AgentRunSummary]) -> str:
    if not summaries:
        return "No AGILAB agent runs found."
    lines = ["status  agent  run_id  label"]
    for summary in summaries:
        lines.append(
            f"{summary.status or '-':<7} {summary.agent or '-':<6} {summary.run_id or '-'}  {summary.label}"
        )
    return "\n".join(lines)


def _main_list(argv: Sequence[str]) -> int:
    parser = _build_list_parser()
    args = parser.parse_args(list(argv))
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    summaries = list_agent_runs(
        Path(args.root).expanduser() if args.root else None,
        agent=args.agent or None,
        status=args.status or None,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps([_summary_payload(summary) for summary in summaries], indent=2, sort_keys=True))
    else:
        print(_render_summary_table(summaries))
    return 0


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
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv[:1] == ["list"]:
        return _main_list(raw_argv[1:])

    config = parse_args(raw_argv)
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
