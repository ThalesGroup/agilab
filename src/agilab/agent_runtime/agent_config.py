# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Layered AGILAB agent configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from agilab.agent_runtime.agent_provider_capabilities import ProviderCapability, resolve_provider_capability


CONFIG_SCHEMA = "agilab.agent_config.v1"
CONFIG_FILENAME = "agents.json"
AGILAB_CONFIG_DIRNAME = ".agilab"
AGENT_HOME_ENV = "AGILAB_AGENT_HOME"
_ENV_REF_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_VALID_PERMISSION_LEVELS = frozenset({"readonly", "safe", "standard", "operator"})


@dataclass(frozen=True)
class AgentProviderConfig:
    """Configured provider alias for AGILAB agent runs."""

    name: str
    provider: str
    model: str
    base_url: str = ""
    api_key_env_var: str = ""
    capability_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRuntimeConfig:
    """Resolved global/project agent configuration."""

    schema: str
    default_provider: str
    default_model: str
    permission_level: str
    trace_enabled: bool
    providers: dict[str, AgentProviderConfig]
    config_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ResolvedAgentProvider:
    """Provider selection ready to stamp into an evidence manifest."""

    name: str
    provider: str
    model: str
    base_url: str
    api_key_env_var: str
    capability: ProviderCapability
    config_paths: tuple[Path, ...] = ()


def agent_home(environ: Mapping[str, str] | None = None) -> Path:
    """Return the AGILAB agent home directory."""

    env = environ or os.environ
    raw = env.get(AGENT_HOME_ENV) or "~/.agilab/agents"
    return Path(raw).expanduser().resolve(strict=False)


def resolve_project_root(cwd: Path | str) -> Path:
    """Return the nearest Git project root, or ``cwd`` when none exists."""

    current = Path(cwd).expanduser().resolve(strict=False)
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def project_dirs(cwd: Path | str, project: Path | str | None = None) -> list[Path]:
    """Return directories from project to cwd, inclusive."""

    current = Path(cwd).expanduser().resolve(strict=False)
    root = Path(project).expanduser().resolve(strict=False) if project is not None else resolve_project_root(current)
    dirs = [current]
    while dirs[-1] != root:
        parent = dirs[-1].parent
        if parent == dirs[-1]:
            break
        dirs.append(parent)
    return list(reversed(dirs))


def discover_config_paths(cwd: Path | str, environ: Mapping[str, str] | None = None) -> list[Path]:
    """Return existing config files ordered from global to most-specific project."""

    paths: list[Path] = []
    global_path = agent_home(environ) / CONFIG_FILENAME
    if global_path.is_file():
        paths.append(global_path)
    for directory in project_dirs(cwd):
        candidate = directory / AGILAB_CONFIG_DIRNAME / CONFIG_FILENAME
        if candidate.is_file():
            paths.append(candidate)
    return paths


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _normalize_permission_level(value: Any) -> str:
    if not isinstance(value, str):
        return "safe"
    level = value.strip().lower().replace("_", "-")
    if level == "yolo":
        return "operator"
    return level if level in _VALID_PERMISSION_LEVELS else "safe"


def _parse_api_key_ref(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    match = _ENV_REF_RE.fullmatch(stripped)
    return match.group(1) if match else ""


def _provider_from_payload(name: str, payload: Mapping[str, Any]) -> AgentProviderConfig:
    provider = str(payload.get("provider") or payload.get("type") or name).strip()
    model = str(payload.get("model") or "").strip()
    capability = payload.get("capability")
    api_key_env_var = str(payload.get("api_key_env") or "").strip()
    return AgentProviderConfig(
        name=name,
        provider=provider,
        model=model,
        base_url=str(payload.get("base_url") or "").strip(),
        api_key_env_var=api_key_env_var or _parse_api_key_ref(payload.get("api_key")),
        capability_overrides=dict(capability) if isinstance(capability, dict) else {},
    )


def load_agent_config(
    cwd: Path | str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> AgentRuntimeConfig:
    """Load global and project-local AGILAB agent config files."""

    resolved_cwd = Path(cwd or Path.cwd()).expanduser().resolve(strict=False)
    paths = discover_config_paths(resolved_cwd, environ)
    raw: dict[str, Any] = {}
    for path in paths:
        raw = _deep_merge(raw, _load_json(path))

    default_payload = raw.get("default") if isinstance(raw.get("default"), dict) else {}
    providers_payload = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    providers = {
        str(name): _provider_from_payload(str(name), payload)
        for name, payload in providers_payload.items()
        if isinstance(payload, dict)
    }

    default_provider = str(default_payload.get("provider") or raw.get("default_provider") or "").strip()
    default_model = str(default_payload.get("model") or raw.get("default_model") or "").strip()
    permission_payload = raw.get("permission") if isinstance(raw.get("permission"), dict) else {}
    permission_level = _normalize_permission_level(permission_payload.get("level") or raw.get("permission_level"))
    trace_payload = raw.get("trace") if isinstance(raw.get("trace"), dict) else {}
    trace_enabled = _as_bool(trace_payload.get("enabled", raw.get("trace_enabled")), True)

    return AgentRuntimeConfig(
        schema=CONFIG_SCHEMA,
        default_provider=default_provider,
        default_model=default_model,
        permission_level=permission_level,
        trace_enabled=trace_enabled,
        providers=providers,
        config_paths=tuple(paths),
    )


def resolve_agent_provider(
    config: AgentRuntimeConfig,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ResolvedAgentProvider:
    """Resolve selected provider/model plus capability metadata."""

    requested_provider = str(provider or config.default_provider or "").strip()
    selected = config.providers.get(requested_provider) if requested_provider else None
    provider_type = selected.provider if selected else requested_provider
    model_id = str(model or (selected.model if selected else "") or config.default_model or "").strip()
    capability = resolve_provider_capability(
        provider_type or requested_provider,
        model_id,
        overrides=selected.capability_overrides if selected else None,
    )
    return ResolvedAgentProvider(
        name=selected.name if selected else requested_provider,
        provider=capability.provider,
        model=capability.model,
        base_url=selected.base_url if selected else "",
        api_key_env_var=selected.api_key_env_var if selected else "",
        capability=capability,
        config_paths=config.config_paths,
    )
