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
from agilab.agent_trace import AgentTraceStore, load_trace_events, trace_artifact_payload
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
    tags: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
    protocol_adapters: Sequence[str] = (),
    capabilities: Sequence[str] = (),
    limit: int | None = None,
) -> list[Path]:
    """Find agent-run manifest files, newest first."""

    explicit_root = root is not None
    search_root = Path(root).expanduser() if explicit_root else _default_log_root() / "agents"
    if agent and not explicit_root:
        search_root = search_root / _slug(agent, "agent")
    required_tags = set(_normalize_tags(tags))
    required_metadata = dict(metadata or {})
    required_protocol_adapters = set(_normalize_slug_values(protocol_adapters))
    required_capabilities = set(_normalize_slug_values(capabilities))
    if not search_root.exists():
        return []
    candidates = [
        path
        for path in search_root.rglob(MANIFEST_FILENAME)
        if path.is_file()
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if (
        agent
        or status
        or required_tags
        or required_metadata
        or required_protocol_adapters
        or required_capabilities
    ):
        filtered: list[Path] = []
        for path in candidates:
            try:
                manifest = load_agent_run_manifest(path)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if agent and manifest.get("agent") != agent:
                continue
            if manifest.get("status") == status:
                pass
            elif status:
                continue
            context = manifest.get("context", {})
            context_map = context if isinstance(context, dict) else {}
            raw_tags = context_map.get("tags", [])
            manifest_tags = set(str(tag) for tag in raw_tags) if isinstance(raw_tags, list) else set()
            if required_tags and not required_tags.issubset(manifest_tags):
                continue
            raw_metadata = context_map.get("metadata", {})
            manifest_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            if required_metadata and any(
                str(manifest_metadata.get(key, "")) != value
                for key, value in required_metadata.items()
            ):
                continue
            protocols = manifest.get("protocols", {})
            protocols_map = protocols if isinstance(protocols, dict) else {}
            raw_adapters = protocols_map.get("adapters", [])
            manifest_adapters = (
                set(str(value) for value in raw_adapters)
                if isinstance(raw_adapters, list)
                else set()
            )
            if required_protocol_adapters and not required_protocol_adapters.issubset(manifest_adapters):
                continue
            raw_capabilities = protocols_map.get("capabilities", [])
            manifest_capabilities = (
                set(str(value) for value in raw_capabilities)
                if isinstance(raw_capabilities, list)
                else set()
            )
            if required_capabilities and not required_capabilities.issubset(manifest_capabilities):
                continue
            filtered.append(path)
        candidates = filtered
    return candidates[:limit] if limit is not None else candidates


def list_agent_runs(
    root: Path | str | None = None,
    *,
    agent: str | None = None,
    status: str | None = None,
    tags: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
    protocol_adapters: Sequence[str] = (),
    capabilities: Sequence[str] = (),
    limit: int | None = None,
) -> list[AgentRunSummary]:
    """Return compact summaries for agent-run manifests, newest first."""

    summaries: list[AgentRunSummary] = []
    for path in find_agent_run_manifests(
        root,
        agent=agent,
        status=status,
        tags=tags,
        metadata=metadata,
        protocol_adapters=protocol_adapters,
        capabilities=capabilities,
        limit=limit,
    ):
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
    parser.add_argument("--tag", action="append", default=[], help="Only list runs containing this tag. May be repeated.")
    parser.add_argument("--metadata", action="append", default=[], help="Only list runs with this metadata KEY=VALUE. May be repeated.")
    parser.add_argument(
        "--protocol-adapter",
        action="append",
        default=[],
        help="Only list runs containing this protocol adapter label. May be repeated.",
    )
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        help="Only list runs containing this capability label. May be repeated.",
    )
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


def _protocol_summary(manifest: dict[str, object]) -> dict[str, object]:
    protocols = manifest.get("protocols", {})
    protocols_map = protocols if isinstance(protocols, dict) else {}
    return {
        "adapters": list(protocols_map.get("adapters", []))
        if isinstance(protocols_map.get("adapters"), list)
        else [],
        "capabilities": list(protocols_map.get("capabilities", []))
        if isinstance(protocols_map.get("capabilities"), list)
        else [],
        "mode": str(protocols_map.get("mode") or ""),
    }


def agent_handoff_payload(manifest_or_path: dict[str, object] | Path | str) -> dict[str, object]:
    """Build a compact, redacted handoff card for a prior agent run."""

    if isinstance(manifest_or_path, dict):
        manifest = manifest_or_path
    else:
        manifest = load_agent_run_manifest(manifest_or_path)
    summary = summarize_agent_run(manifest)
    command = manifest.get("command", {})
    command_map = command if isinstance(command, dict) else {}
    permission = manifest.get("permission", {})
    permission_map = permission if isinstance(permission, dict) else {}
    trace_events: list[dict[str, object]] = []
    if summary.trace_events_path:
        for event in load_trace_events(summary.trace_events_path.parent):
            trace_events.append(
                {
                    "sequence": event.sequence,
                    "event": event.event,
                    "status": event.status,
                    "message": event.message,
                }
            )
    manifest_path = str(summary.manifest_path)
    continue_prompt = (
        "Continue from AGILAB agent-run evidence "
        f"{manifest_path}. Read the manifest first, inspect stdout/stderr only if needed, "
        "and preserve the recorded tags, metadata, protocol adapters, and capabilities "
        "when creating follow-up evidence."
    )
    return {
        "schema": "agilab.agent_handoff.v1",
        "run": _summary_payload(summary),
        "command": {
            "argv": command_map.get("argv", []),
            "argv_redacted": bool(command_map.get("argv_redacted", False)),
            "argv_count": command_map.get("argv_count"),
            "argv_sha256": command_map.get("argv_sha256"),
            "cwd": command_map.get("cwd"),
        },
        "protocols": _protocol_summary(manifest),
        "permission": {
            "allowed": bool(permission_map.get("allowed", False)),
            "tier": permission_map.get("tier"),
            "level": permission_map.get("level"),
            "reason": permission_map.get("reason"),
        },
        "trace": {
            "event_count": len(trace_events),
            "events": trace_events,
        },
        "handoff": {
            "continue_prompt": continue_prompt,
            "artifact_policy": "Manifest paths and counts only; stdout/stderr contents are not embedded.",
        },
    }


def render_handoff_markdown(payload: dict[str, object]) -> str:
    """Render an agent handoff payload as compact Markdown."""

    run = payload.get("run", {})
    run_map = run if isinstance(run, dict) else {}
    protocols = payload.get("protocols", {})
    protocol_map = protocols if isinstance(protocols, dict) else {}
    handoff = payload.get("handoff", {})
    handoff_map = handoff if isinstance(handoff, dict) else {}
    trace = payload.get("trace", {})
    trace_map = trace if isinstance(trace, dict) else {}
    tags = run_map.get("tags", [])
    metadata = run_map.get("metadata", {})
    lines = [
        "# AGILAB agent handoff",
        "",
        f"- run_id: {run_map.get('run_id', '')}",
        f"- agent: {run_map.get('agent', '')}",
        f"- status: {run_map.get('status', '')}",
        f"- label: {run_map.get('label', '')}",
        f"- manifest: {run_map.get('manifest', '')}",
        f"- stdout: {run_map.get('stdout', '')}",
        f"- stderr: {run_map.get('stderr', '')}",
        f"- trace_events: {run_map.get('trace_events', '')}",
        f"- tags: {', '.join(str(tag) for tag in tags) if isinstance(tags, list) else ''}",
        f"- metadata: {json.dumps(metadata, sort_keys=True) if isinstance(metadata, dict) else '{}'}",
        f"- protocol_adapters: {', '.join(str(value) for value in protocol_map.get('adapters', []))}",
        f"- capabilities: {', '.join(str(value) for value in protocol_map.get('capabilities', []))}",
        f"- trace_event_count: {trace_map.get('event_count', 0)}",
        "",
        "## Continue prompt",
        "",
        str(handoff_map.get("continue_prompt", "")),
    ]
    return "\n".join(lines)


def _next_action_items(summary: AgentRunSummary, permission: Mapping[str, object]) -> list[dict[str, str]]:
    status = summary.status
    if status == "pass":
        return [
            {
                "priority": "P1",
                "action": "Attach this manifest path to the proof, review, or release note that depends on it.",
                "reason": "The agent run completed successfully and has reusable evidence artifacts.",
            },
            {
                "priority": "P2",
                "action": "Use matching tags, metadata, protocol adapters, and capabilities for follow-up runs.",
                "reason": "Context-stable metadata keeps later agent evidence queryable.",
            },
        ]
    if status == "denied":
        return [
            {
                "priority": "P0",
                "action": "Inspect the permission tier and stderr artifact before rerunning.",
                "reason": str(permission.get("reason") or "The command was blocked by the permission policy."),
            },
            {
                "priority": "P1",
                "action": "Prefer a narrower non-destructive command; escalate permission only with explicit operator intent.",
                "reason": "AGILAB records confirmation requirements but does not sandbox the process.",
            },
        ]
    if status == "timeout":
        return [
            {
                "priority": "P0",
                "action": "Inspect stderr, stdout, and trace events to identify the slow phase before increasing timeout.",
                "reason": "A timeout is ambiguous without artifact review.",
            },
            {
                "priority": "P1",
                "action": "Retry with the same tags and metadata after narrowing the command or extending timeout deliberately.",
                "reason": "Stable context makes timeout regressions comparable.",
            },
        ]
    if status == "fail":
        return [
            {
                "priority": "P0",
                "action": "Inspect stderr and trace events, fix the smallest reproducible cause, then rerun.",
                "reason": "The command returned a non-zero exit status.",
            },
            {
                "priority": "P1",
                "action": "Record the follow-up run with metadata followup_of=<run_id>.",
                "reason": "A linked follow-up preserves the debugging chain for another agent.",
            },
        ]
    return [
        {
            "priority": "P1",
            "action": "Read the manifest and trace events before deciding whether to rerun or archive this evidence.",
            "reason": f"Status {status!r} does not have a specialized policy.",
        }
    ]


def agent_next_actions_payload(manifest_or_path: dict[str, object] | Path | str) -> dict[str, object]:
    """Build deterministic next-action guidance from one agent-run manifest."""

    if isinstance(manifest_or_path, dict):
        manifest = manifest_or_path
    else:
        manifest = load_agent_run_manifest(manifest_or_path)
    summary = summarize_agent_run(manifest)
    permission = manifest.get("permission", {})
    permission_map = permission if isinstance(permission, dict) else {}
    followup_metadata = dict(summary.metadata)
    if summary.run_id:
        followup_metadata["followup_of"] = summary.run_id
    return {
        "schema": "agilab.agent_next_actions.v1",
        "run": _summary_payload(summary),
        "protocols": _protocol_summary(manifest),
        "permission": {
            "allowed": bool(permission_map.get("allowed", False)),
            "tier": permission_map.get("tier"),
            "level": permission_map.get("level"),
            "reason": permission_map.get("reason"),
        },
        "next_actions": _next_action_items(summary, permission_map),
        "followup_context": {
            "agent": summary.agent,
            "tags": list(summary.tags),
            "metadata": followup_metadata,
            "protocol_adapters": _protocol_summary(manifest)["adapters"],
            "capabilities": _protocol_summary(manifest)["capabilities"],
            "command_policy": (
                "Do not reconstruct redacted argv from the manifest. Rebuild the next command from current task context."
            ),
        },
    }


def render_next_actions_markdown(payload: dict[str, object]) -> str:
    """Render next-action guidance as compact Markdown."""

    run = payload.get("run", {})
    run_map = run if isinstance(run, dict) else {}
    actions = payload.get("next_actions", [])
    action_list = actions if isinstance(actions, list) else []
    lines = [
        "# AGILAB agent next actions",
        "",
        f"- run_id: {run_map.get('run_id', '')}",
        f"- agent: {run_map.get('agent', '')}",
        f"- status: {run_map.get('status', '')}",
        f"- manifest: {run_map.get('manifest', '')}",
        "",
        "## Recommended actions",
        "",
    ]
    for item in action_list:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('priority', 'P?')}: {item.get('action', '')} "
            f"Reason: {item.get('reason', '')}"
        )
    return "\n".join(lines)


def agent_context_payload(
    root: Path | str | None = None,
    *,
    agent: str | None = None,
    status: str | None = None,
    tags: Sequence[str] = (),
    metadata: Mapping[str, str] | None = None,
    protocol_adapters: Sequence[str] = (),
    capabilities: Sequence[str] = (),
    limit: int = 20,
) -> dict[str, object]:
    """Build a safe context pack from matching agent-run evidence."""

    summaries = list_agent_runs(
        root,
        agent=agent,
        status=status,
        tags=tags,
        metadata=metadata,
        protocol_adapters=protocol_adapters,
        capabilities=capabilities,
        limit=limit,
    )
    status_counts: dict[str, int] = {}
    for summary in summaries:
        key = summary.status or "unknown"
        status_counts[key] = status_counts.get(key, 0) + 1
    latest_handoff: dict[str, object] | None = None
    latest_next_actions: dict[str, object] | None = None
    if summaries and str(summaries[0].manifest_path):
        try:
            latest_handoff = agent_handoff_payload(summaries[0].manifest_path)
            latest_next_actions = agent_next_actions_payload(summaries[0].manifest_path)
        except (OSError, json.JSONDecodeError, ValueError):
            latest_handoff = None
            latest_next_actions = None
    return {
        "schema": "agilab.agent_context.v1",
        "query": {
            "root": str(Path(root).expanduser()) if root is not None else "~/log/agents",
            "agent": agent,
            "status": status,
            "tags": list(_normalize_tags(tags)),
            "metadata": dict(metadata or {}),
            "protocol_adapters": list(_normalize_slug_values(protocol_adapters)),
            "capabilities": list(_normalize_slug_values(capabilities)),
            "limit": limit,
        },
        "match_count": len(summaries),
        "status_counts": status_counts,
        "runs": [_summary_payload(summary) for summary in summaries],
        "latest": {
            "handoff": latest_handoff,
            "next_actions": latest_next_actions,
        },
        "artifact_policy": "Manifest paths and counts only; stdout/stderr contents are not embedded.",
    }


def render_context_markdown(payload: dict[str, object]) -> str:
    """Render an agent context pack as compact Markdown."""

    runs = payload.get("runs", [])
    run_list = runs if isinstance(runs, list) else []
    status_counts = payload.get("status_counts", {})
    status_map = status_counts if isinstance(status_counts, dict) else {}
    latest = payload.get("latest", {})
    latest_map = latest if isinstance(latest, dict) else {}
    latest_next = latest_map.get("next_actions", {})
    latest_next_map = latest_next if isinstance(latest_next, dict) else {}
    actions = latest_next_map.get("next_actions", [])
    action_list = actions if isinstance(actions, list) else []
    lines = [
        "# AGILAB agent context pack",
        "",
        f"- match_count: {payload.get('match_count', 0)}",
        f"- status_counts: {json.dumps(status_map, sort_keys=True)}",
        "",
        "## Matching runs",
        "",
    ]
    if not run_list:
        lines.append("- No matching agent runs found.")
    for item in run_list:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('status', '-')}: {item.get('agent', '-')} "
            f"{item.get('run_id', '-')} - {item.get('label', '')}"
        )
    if action_list:
        lines.extend(["", "## Latest run next actions", ""])
        for item in action_list:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('priority', 'P?')}: {item.get('action', '')} "
                f"Reason: {item.get('reason', '')}"
            )
    return "\n".join(lines)


def agent_lineage_payload(
    root: Path | str | None = None,
    *,
    run_id: str,
) -> dict[str, object]:
    """Build a follow-up lineage graph from agent-run metadata."""

    summaries = list_agent_runs(root, limit=None)
    by_run_id = {summary.run_id: summary for summary in summaries if summary.run_id}
    children_by_parent: dict[str, list[AgentRunSummary]] = {}
    parent_by_child: dict[str, str] = {}
    for summary in summaries:
        parent = summary.metadata.get("followup_of")
        if not isinstance(parent, str) or not parent:
            continue
        parent_by_child[summary.run_id] = parent
        children_by_parent.setdefault(parent, []).append(summary)

    target = by_run_id.get(run_id)
    ancestors: list[AgentRunSummary] = []
    seen = {run_id}
    cursor = run_id
    while cursor in parent_by_child:
        parent_id = parent_by_child[cursor]
        if parent_id in seen:
            break
        seen.add(parent_id)
        parent = by_run_id.get(parent_id)
        if parent is None:
            break
        ancestors.append(parent)
        cursor = parent_id
    ancestors.reverse()

    descendants: list[AgentRunSummary] = []

    def visit(parent_id: str, seen_ids: set[str]) -> None:
        for child in children_by_parent.get(parent_id, []):
            if child.run_id in seen_ids:
                continue
            seen_ids.add(child.run_id)
            descendants.append(child)
            visit(child.run_id, seen_ids)

    visit(run_id, {run_id})
    chain = [*ancestors, *([target] if target is not None else []), *descendants]
    edges = [
        {"from": parent, "to": child}
        for child, parent in sorted(parent_by_child.items())
        if child in by_run_id and parent in by_run_id
    ]
    return {
        "schema": "agilab.agent_lineage.v1",
        "query": {
            "root": str(Path(root).expanduser()) if root is not None else "~/log/agents",
            "run_id": run_id,
        },
        "found": target is not None,
        "target": _summary_payload(target) if target is not None else None,
        "ancestors": [_summary_payload(summary) for summary in ancestors],
        "descendants": [_summary_payload(summary) for summary in descendants],
        "chain": [_summary_payload(summary) for summary in chain],
        "edges": edges,
        "artifact_policy": "Manifest paths and metadata links only; stdout/stderr contents are not embedded.",
    }


def render_lineage_markdown(payload: dict[str, object]) -> str:
    """Render an agent lineage graph as compact Markdown."""

    chain = payload.get("chain", [])
    chain_list = chain if isinstance(chain, list) else []
    edges = payload.get("edges", [])
    edge_list = edges if isinstance(edges, list) else []
    lines = [
        "# AGILAB agent lineage",
        "",
        f"- run_id: {payload.get('query', {}).get('run_id', '') if isinstance(payload.get('query'), dict) else ''}",
        f"- found: {payload.get('found', False)}",
        "",
        "## Chain",
        "",
    ]
    if not chain_list:
        lines.append("- No linked agent runs found.")
    for item in chain_list:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- {item.get('status', '-')}: {item.get('run_id', '-')} "
            f"({item.get('agent', '-')}) - {item.get('label', '')}"
        )
    if edge_list:
        lines.extend(["", "## Links", ""])
        for edge in edge_list:
            if not isinstance(edge, dict):
                continue
            lines.append(f"- {edge.get('from', '')} -> {edge.get('to', '')}")
    return "\n".join(lines)


def _string_set_delta(left: Sequence[object], right: Sequence[object]) -> dict[str, list[str]]:
    left_set = {str(value) for value in left}
    right_set = {str(value) for value in right}
    return {
        "added": sorted(right_set - left_set),
        "removed": sorted(left_set - right_set),
    }


def _metadata_delta(
    left: Mapping[str, object], right: Mapping[str, object]
) -> dict[str, object]:
    left_keys = set(left)
    right_keys = set(right)
    shared = left_keys & right_keys
    return {
        "added": {key: right[key] for key in sorted(right_keys - left_keys)},
        "removed": {key: left[key] for key in sorted(left_keys - right_keys)},
        "changed": {
            key: {"left": left[key], "right": right[key]}
            for key in sorted(shared)
            if left[key] != right[key]
        },
    }


def _trace_event_count(summary: AgentRunSummary) -> int:
    if not summary.trace_events_path:
        return 0
    try:
        return len(load_trace_events(summary.trace_events_path.parent))
    except OSError:
        return 0


def compare_agent_runs(
    left_manifest_or_path: dict[str, object] | Path | str,
    right_manifest_or_path: dict[str, object] | Path | str,
) -> dict[str, object]:
    """Compare two agent-run manifests without embedding stdout/stderr contents."""

    left_manifest = (
        left_manifest_or_path
        if isinstance(left_manifest_or_path, dict)
        else load_agent_run_manifest(left_manifest_or_path)
    )
    right_manifest = (
        right_manifest_or_path
        if isinstance(right_manifest_or_path, dict)
        else load_agent_run_manifest(right_manifest_or_path)
    )
    left = summarize_agent_run(left_manifest)
    right = summarize_agent_run(right_manifest)
    left_command = left_manifest.get("command", {})
    right_command = right_manifest.get("command", {})
    left_command_map = left_command if isinstance(left_command, dict) else {}
    right_command_map = right_command if isinstance(right_command, dict) else {}
    left_protocols = _protocol_summary(left_manifest)
    right_protocols = _protocol_summary(right_manifest)
    left_trace_count = _trace_event_count(left)
    right_trace_count = _trace_event_count(right)
    return {
        "schema": "agilab.agent_compare.v1",
        "left": _summary_payload(left),
        "right": _summary_payload(right),
        "status_changed": left.status != right.status,
        "returncode_changed": left.returncode != right.returncode,
        "duration_delta_seconds": right.duration_seconds - left.duration_seconds,
        "command": {
            "argv_sha256_changed": left_command_map.get("argv_sha256")
            != right_command_map.get("argv_sha256"),
            "argv_count_delta": int(right_command_map.get("argv_count") or 0)
            - int(left_command_map.get("argv_count") or 0),
            "cwd_changed": left_command_map.get("cwd") != right_command_map.get("cwd"),
        },
        "tags": _string_set_delta(left.tags, right.tags),
        "metadata": _metadata_delta(left.metadata, right.metadata),
        "protocol_adapters": _string_set_delta(
            left_protocols["adapters"], right_protocols["adapters"]
        ),
        "capabilities": _string_set_delta(
            left_protocols["capabilities"], right_protocols["capabilities"]
        ),
        "trace_event_count_delta": right_trace_count - left_trace_count,
        "artifact_policy": "Manifest paths and counts only; stdout/stderr contents are not embedded.",
    }


def render_compare_markdown(payload: dict[str, object]) -> str:
    """Render an agent-run comparison as compact Markdown."""

    left = payload.get("left", {})
    right = payload.get("right", {})
    left_map = left if isinstance(left, dict) else {}
    right_map = right if isinstance(right, dict) else {}
    lines = [
        "# AGILAB agent-run comparison",
        "",
        f"- left: {left_map.get('run_id', '')} ({left_map.get('status', '')})",
        f"- right: {right_map.get('run_id', '')} ({right_map.get('status', '')})",
        f"- status_changed: {payload.get('status_changed', False)}",
        f"- returncode_changed: {payload.get('returncode_changed', False)}",
        f"- duration_delta_seconds: {payload.get('duration_delta_seconds', 0.0)}",
        f"- trace_event_count_delta: {payload.get('trace_event_count_delta', 0)}",
    ]
    metadata = payload.get("metadata", {})
    if isinstance(metadata, dict) and any(metadata.get(key) for key in ("added", "removed", "changed")):
        lines.extend(["", "## Metadata delta", "", json.dumps(metadata, sort_keys=True)])
    return "\n".join(lines)


def _build_handoff_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render an AGILAB agent-run handoff card.")
    parser.add_argument("manifest_path", help="Agent-run manifest path or run directory.")
    parser.add_argument("--json", action="store_true", help="Print the handoff card as JSON.")
    return parser


def _build_next_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render AGILAB agent-run next-action guidance.")
    parser.add_argument("manifest_path", help="Agent-run manifest path or run directory.")
    parser.add_argument("--json", action="store_true", help="Print next-action guidance as JSON.")
    return parser


def _build_context_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render an AGILAB agent-run context pack.")
    parser.add_argument("--root", default="", help="Root directory to scan. Defaults to ~/log/agents.")
    parser.add_argument("--agent", default="", help="Only include runs for this agent.")
    parser.add_argument("--status", default="", choices=["", "planned", "pass", "fail", "timeout", "denied"], help="Only include runs with this status.")
    parser.add_argument("--tag", action="append", default=[], help="Only include runs containing this tag. May be repeated.")
    parser.add_argument("--metadata", action="append", default=[], help="Only include runs with this metadata KEY=VALUE. May be repeated.")
    parser.add_argument(
        "--protocol-adapter",
        action="append",
        default=[],
        help="Only include runs containing this protocol adapter label. May be repeated.",
    )
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        help="Only include runs containing this capability label. May be repeated.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of runs to include.")
    parser.add_argument("--json", action="store_true", help="Print the context pack as JSON.")
    return parser


def _build_lineage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render an AGILAB agent-run follow-up lineage.")
    parser.add_argument("run_id", help="Target agent-run id to explain.")
    parser.add_argument("--root", default="", help="Root directory to scan. Defaults to ~/log/agents.")
    parser.add_argument("--json", action="store_true", help="Print the lineage graph as JSON.")
    return parser


def _build_compare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two AGILAB agent-run manifests.")
    parser.add_argument("left_manifest", help="Left agent-run manifest path or run directory.")
    parser.add_argument("right_manifest", help="Right agent-run manifest path or run directory.")
    parser.add_argument("--json", action="store_true", help="Print the comparison as JSON.")
    return parser


def _main_handoff(argv: Sequence[str]) -> int:
    parser = _build_handoff_parser()
    args = parser.parse_args(list(argv))
    payload = agent_handoff_payload(Path(args.manifest_path).expanduser())
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_handoff_markdown(payload))
    return 0


def _main_next(argv: Sequence[str]) -> int:
    parser = _build_next_parser()
    args = parser.parse_args(list(argv))
    payload = agent_next_actions_payload(Path(args.manifest_path).expanduser())
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_next_actions_markdown(payload))
    return 0


def _main_context(argv: Sequence[str]) -> int:
    parser = _build_context_parser()
    args = parser.parse_args(list(argv))
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    payload = agent_context_payload(
        Path(args.root).expanduser() if args.root else None,
        agent=args.agent or None,
        status=args.status or None,
        tags=args.tag,
        metadata=_parse_metadata(args.metadata),
        protocol_adapters=args.protocol_adapter,
        capabilities=args.capability,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_context_markdown(payload))
    return 0


def _main_lineage(argv: Sequence[str]) -> int:
    parser = _build_lineage_parser()
    args = parser.parse_args(list(argv))
    payload = agent_lineage_payload(
        Path(args.root).expanduser() if args.root else None,
        run_id=args.run_id,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_lineage_markdown(payload))
    return 0


def _main_compare(argv: Sequence[str]) -> int:
    parser = _build_compare_parser()
    args = parser.parse_args(list(argv))
    payload = compare_agent_runs(
        Path(args.left_manifest).expanduser(),
        Path(args.right_manifest).expanduser(),
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_compare_markdown(payload))
    return 0


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
        tags=args.tag,
        metadata=_parse_metadata(args.metadata),
        protocol_adapters=args.protocol_adapter,
        capabilities=args.capability,
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
    if raw_argv[:1] == ["handoff"]:
        return _main_handoff(raw_argv[1:])
    if raw_argv[:1] in (["next"], ["next-actions"], ["next_actions"]):
        return _main_next(raw_argv[1:])
    if raw_argv[:1] == ["context"]:
        return _main_context(raw_argv[1:])
    if raw_argv[:1] == ["lineage"]:
        return _main_lineage(raw_argv[1:])
    if raw_argv[:1] == ["compare"]:
        return _main_compare(raw_argv[1:])

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
