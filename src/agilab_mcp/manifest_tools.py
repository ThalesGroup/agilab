"""Read-only manifest and artifact tools used by the AGILAB MCP bridge."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from agilab import agent_run, bridge_cli, run_manifest
from agilab.secret_uri import redact_mapping

_ALLOWED_ROOTS_ENV = "AGILAB_MCP_ALLOWED_ROOTS"
_ALLOW_CWD_ENV = "AGILAB_MCP_ALLOW_CWD"
_CONFIGURED_ROOT_ENV_NAMES = (
    # Canonical documented names come first; the AGILAB_*_ROOT names remain as
    # aliases so existing MCP deployments keep working.
    "APPS_PATH",
    "AGI_LOG_DIR",
    "AGILAB_APPS_ROOT",
    "AGILAB_LOG_ROOT",
    "AGILAB_AGENT_LOG_ROOT",
)


class _MCPPathError(ValueError):
    """A caller-controlled path crossed the configured MCP read boundary."""


def _repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "agilab-capabilities.json").is_file() or (
            parent / ".git"
        ).exists():
            return parent
    return None


def _unique_roots(paths: list[Path]) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve(strict=False)
        key = str(resolved)
        if key not in seen:
            roots.append(resolved)
            seen.add(key)
    return tuple(roots)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _configured_read_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    configured = os.environ.get(_ALLOWED_ROOTS_ENV, "")
    explicit_roots = [Path(item) for item in configured.split(os.pathsep) if item]
    if explicit_roots:
        return _unique_roots(explicit_roots)
    for env_name in _CONFIGURED_ROOT_ENV_NAMES:
        env_value = os.environ.get(env_name)
        if env_value:
            roots.append(Path(env_value))
    repo_root = _repo_root()
    if repo_root is not None:
        roots.append(repo_root)
    if _env_truthy(_ALLOW_CWD_ENV):
        roots.append(Path.cwd())
    home = Path.home()
    roots.extend((home / "log" / "agents", home / "log" / "execute"))
    return _unique_roots(roots)


def _is_under_root(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _mcp_read_path(path: str | Path, *, purpose: str) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    roots = _configured_read_roots()
    if any(_is_under_root(resolved, root) for root in roots):
        return resolved
    allowed = ", ".join(str(root) for root in roots) or "<none>"
    raise _MCPPathError(
        f"MCP path for {purpose} is outside configured read roots: "
        f"{resolved} (allowed roots: {allowed})"
    )


def _mcp_resource_path(
    path: str | Path,
    *,
    manifest_path: Path,
    purpose: str,
) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    return _mcp_read_path(candidate, purpose=purpose)


def _canonicalize_path_value(
    value: object,
    *,
    manifest_path: Path,
    purpose: str,
) -> object:
    if isinstance(value, str) and value:
        return str(
            _mcp_resource_path(
                value,
                manifest_path=manifest_path,
                purpose=purpose,
            )
        )
    if isinstance(value, Mapping):
        raw_path = value.get("path")
        if isinstance(raw_path, str) and raw_path:
            updated = dict(value)
            updated["path"] = str(
                _mcp_resource_path(
                    raw_path,
                    manifest_path=manifest_path,
                    purpose=purpose,
                )
            )
            return updated
    return value


def _canonicalize_agent_manifest_resources(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
) -> dict[str, Any]:
    """Validate and canonicalize every agent artifact path before reuse."""

    safe_manifest = deepcopy(dict(manifest))
    artifacts = safe_manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return safe_manifest
    safe_artifacts = dict(artifacts)
    for name, value in tuple(safe_artifacts.items()):
        safe_artifacts[name] = _canonicalize_path_value(
            value,
            manifest_path=manifest_path,
            purpose=f"agent run {name} artifact",
        )
    trace = safe_artifacts.get("agent_trace")
    if isinstance(trace, Mapping):
        safe_trace = dict(trace)
        for name in ("meta", "events", "tool_output_dir"):
            raw_path = safe_trace.get(name)
            if isinstance(raw_path, str) and raw_path:
                safe_trace[name] = str(
                    _mcp_resource_path(
                        raw_path,
                        manifest_path=manifest_path,
                        purpose=f"agent trace {name} resource",
                    )
                )
        safe_artifacts["agent_trace"] = safe_trace
    safe_manifest["artifacts"] = safe_artifacts
    return safe_manifest


def _agent_manifest_file(path: Path) -> Path:
    candidate = path / agent_run.MANIFEST_FILENAME if path.is_dir() else path
    return _mcp_read_path(candidate, purpose="agent run manifest file")


def _load_mcp_agent_manifest(path: str | Path) -> tuple[dict[str, Any], Path]:
    input_path = _mcp_read_path(path, purpose="agent run manifest")
    manifest_path = _agent_manifest_file(input_path)
    manifest = agent_run.load_agent_run_manifest(manifest_path)
    return (
        _canonicalize_agent_manifest_resources(
            manifest,
            manifest_path=manifest_path,
        ),
        manifest_path,
    )


def _default_agent_log_root() -> Path:
    raw = os.environ.get("AGI_LOG_DIR") or os.environ.get("AGILAB_LOG_ABS")
    return Path(raw if raw else str(Path.home() / "log")).expanduser() / "agents"


def _agent_manifest_records(
    root: Path | None,
    *,
    agent: str = "",
    status: str = "",
    tag: str = "",
    metadata: Mapping[str, str] | None = None,
    protocol_adapter: str = "",
    capability: str = "",
    limit: int | None = None,
) -> list[tuple[dict[str, Any], Path, agent_run.AgentRunSummary]]:
    """Load filtered agent records without dereferencing unchecked manifest paths."""

    search_root = _mcp_read_path(
        root if root is not None else _default_agent_log_root(),
        purpose="agent log root",
    )
    if limit == 0 or not search_root.is_dir():
        return []
    candidates: list[Path] = []
    for candidate in search_root.rglob(agent_run.MANIFEST_FILENAME):
        safe_candidate = _mcp_read_path(
            candidate,
            purpose="discovered agent run manifest",
        )
        if safe_candidate.is_file():
            candidates.append(safe_candidate)
    candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)

    required_tags = set(agent_run._normalize_tags((tag,) if tag else ()))
    required_metadata = dict(metadata or {})
    required_protocol_adapters = set(
        agent_run._normalize_slug_values(
            (protocol_adapter,) if protocol_adapter else ()
        )
    )
    required_capabilities = set(
        agent_run._normalize_slug_values((capability,) if capability else ())
    )
    records: list[tuple[dict[str, Any], Path, agent_run.AgentRunSummary]] = []
    for candidate in candidates:
        try:
            manifest, manifest_path = _load_mcp_agent_manifest(candidate)
            summary = agent_run.summarize_agent_run(manifest)
        except _MCPPathError:
            raise
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if agent and summary.agent != agent:
            continue
        if status and summary.status != status:
            continue
        if required_tags and not required_tags.issubset(summary.tags):
            continue
        if required_metadata and any(
            str(summary.metadata.get(key, "")) != value
            for key, value in required_metadata.items()
        ):
            continue
        protocols = manifest.get("protocols")
        protocol_map = protocols if isinstance(protocols, Mapping) else {}
        adapters = protocol_map.get("adapters")
        adapter_values = (
            {str(value) for value in adapters} if isinstance(adapters, list) else set()
        )
        if required_protocol_adapters and not required_protocol_adapters.issubset(
            adapter_values
        ):
            continue
        capabilities = protocol_map.get("capabilities")
        capability_values = (
            {str(value) for value in capabilities}
            if isinstance(capabilities, list)
            else set()
        )
        if required_capabilities and not required_capabilities.issubset(
            capability_values
        ):
            continue
        records.append((manifest, manifest_path, summary))
        if limit is not None and len(records) >= limit:
            break
    return records


def _canonicalize_run_manifest_resources(
    payload: Mapping[str, Any],
    *,
    manifest_path: Path,
) -> dict[str, Any]:
    safe_payload = deepcopy(dict(payload))
    artifacts = safe_payload.get("artifacts")
    if not isinstance(artifacts, list):
        return safe_payload
    safe_artifacts: list[object] = []
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, Mapping):
            safe_artifacts.append(artifact)
            continue
        safe_artifact = dict(artifact)
        raw_path = safe_artifact.get("path")
        if isinstance(raw_path, str) and raw_path:
            safe_artifact["path"] = str(
                _mcp_resource_path(
                    raw_path,
                    manifest_path=manifest_path,
                    purpose=f"run artifact {index}",
                )
            )
        safe_artifacts.append(safe_artifact)
    safe_payload["artifacts"] = safe_artifacts
    return safe_payload


def _load_mcp_run_manifest(
    path: str | Path,
    *,
    purpose: str,
) -> tuple[run_manifest.RunManifest, dict[str, Any], Path]:
    input_path = _mcp_read_path(path, purpose=purpose)
    _manifest, payload, resolved = bridge_cli._load_run_manifest(input_path)
    safe_payload = _canonicalize_run_manifest_resources(
        payload,
        manifest_path=resolved,
    )
    return run_manifest.RunManifest.from_dict(safe_payload), safe_payload, resolved


def list_projects(apps_root: str | Path) -> dict[str, Any]:
    root = _mcp_read_path(apps_root, purpose="projects root")
    projects = (
        [
            {
                "name": path.name,
                "path": str(_mcp_read_path(path, purpose="project directory")),
            }
            for path in sorted(root.iterdir())
            if path.is_dir() and path.name.endswith("_project")
        ]
        if root.is_dir()
        else []
    )
    return {
        "schema": "agilab.mcp.list_projects.v1",
        "apps_root": str(root),
        "projects": projects,
    }


def list_runs(log_root: str | Path) -> dict[str, Any]:
    root = _mcp_read_path(log_root, purpose="run log root")
    runs = (
        [
            {
                "path": str(_mcp_read_path(path, purpose="discovered run manifest")),
                "parent": str(
                    _mcp_read_path(path, purpose="discovered run manifest").parent
                ),
            }
            for path in sorted(root.rglob(run_manifest.RUN_MANIFEST_FILENAME))
        ]
        if root.is_dir()
        else []
    )
    return {
        "schema": "agilab.mcp.list_runs.v1",
        "log_root": str(root),
        "runs": runs,
    }


def _agent_run_summary_payload(summary: agent_run.AgentRunSummary) -> dict[str, Any]:
    return {
        "run_id": summary.run_id,
        "agent": summary.agent,
        "label": summary.label,
        "status": summary.status,
        "returncode": summary.returncode,
        "manifest": str(summary.manifest_path),
        "stdout": str(summary.stdout_path) if summary.stdout_path else None,
        "stderr": str(summary.stderr_path) if summary.stderr_path else None,
        "trace_events": str(summary.trace_events_path)
        if summary.trace_events_path
        else None,
        "duration_seconds": summary.duration_seconds,
        "tags": list(summary.tags),
        "metadata": summary.metadata,
    }


def list_agent_runs(
    log_root: str | Path | None = None,
    *,
    agent: str = "",
    status: str = "",
    tag: str = "",
    metadata: Mapping[str, str] | None = None,
    protocol_adapter: str = "",
    capability: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    if limit < 0:
        raise ValueError("limit must be >= 0")
    root = (
        _mcp_read_path(log_root, purpose="agent log root")
        if log_root not in (None, "")
        else None
    )
    records = _agent_manifest_records(
        root,
        agent=agent,
        status=status,
        tag=tag,
        metadata=metadata,
        protocol_adapter=protocol_adapter,
        capability=capability,
        limit=limit,
    )
    return {
        "schema": "agilab.mcp.list_agent_runs.v1",
        "log_root": str(root) if root is not None else "~/log/agents",
        "agent": agent or None,
        "status": status or None,
        "tag": tag or None,
        "metadata": dict(metadata or {}),
        "protocol_adapter": protocol_adapter or None,
        "capability": capability or None,
        "runs": [
            _agent_run_summary_payload(summary)
            for _manifest, _path, summary in records
        ],
    }


def read_agent_run(manifest_path: str | Path) -> dict[str, Any]:
    manifest, path = _load_mcp_agent_manifest(manifest_path)
    summary = agent_run.summarize_agent_run(manifest)
    resolved = summary.manifest_path if str(summary.manifest_path) else path
    return {
        "schema": "agilab.mcp.read_agent_run.v1",
        "manifest_path": str(resolved),
        "manifest": redact_mapping(manifest),
    }


def summarize_agent_run(manifest_path: str | Path) -> dict[str, Any]:
    manifest, path = _load_mcp_agent_manifest(manifest_path)
    summary = agent_run.summarize_agent_run(manifest)
    return {
        "schema": "agilab.mcp.summarize_agent_run.v1",
        "manifest_path": str(summary.manifest_path or path),
        "summary": _agent_run_summary_payload(summary),
    }


def agent_handoff(manifest_path: str | Path) -> dict[str, Any]:
    manifest, path = _load_mcp_agent_manifest(manifest_path)
    return {
        "schema": "agilab.mcp.agent_handoff.v1",
        "manifest_path": str(path),
        "handoff": agent_run.agent_handoff_payload(manifest),
    }


def agent_next_actions(manifest_path: str | Path) -> dict[str, Any]:
    manifest, path = _load_mcp_agent_manifest(manifest_path)
    return {
        "schema": "agilab.mcp.agent_next_actions.v1",
        "manifest_path": str(path),
        "next_actions": agent_run.agent_next_actions_payload(manifest),
    }


def agent_context(
    log_root: str | Path | None = None,
    *,
    agent: str = "",
    status: str = "",
    tag: str = "",
    metadata: Mapping[str, str] | None = None,
    protocol_adapter: str = "",
    capability: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    if limit < 0:
        raise ValueError("limit must be >= 0")
    root = (
        _mcp_read_path(log_root, purpose="agent log root")
        if log_root not in (None, "")
        else None
    )
    records = _agent_manifest_records(
        root,
        agent=agent,
        status=status,
        tag=tag,
        metadata=metadata,
        protocol_adapter=protocol_adapter,
        capability=capability,
        limit=limit,
    )
    summaries = [summary for _manifest, _path, summary in records]
    return {
        "schema": "agilab.mcp.agent_context.v1",
        "log_root": str(root) if root is not None else "~/log/agents",
        "context": agent_run.agent_context_payload(
            root,
            agent=agent or None,
            status=status or None,
            tags=(tag,) if tag else (),
            metadata=metadata,
            protocol_adapters=(protocol_adapter,) if protocol_adapter else (),
            capabilities=(capability,) if capability else (),
            limit=limit,
            _summaries=summaries,
            _latest_manifest=records[0][0] if records else None,
        ),
    }


def agent_lineage(
    log_root: str | Path | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    root = (
        _mcp_read_path(log_root, purpose="agent log root")
        if log_root not in (None, "")
        else None
    )
    records = _agent_manifest_records(root, limit=None)
    summaries = [summary for _manifest, _path, summary in records]
    return {
        "schema": "agilab.mcp.agent_lineage.v1",
        "log_root": str(root) if root is not None else "~/log/agents",
        "lineage": agent_run.agent_lineage_payload(
            root,
            run_id=run_id,
            _summaries=summaries,
        ),
    }


def compare_agent_runs(
    left_manifest: str | Path, right_manifest: str | Path
) -> dict[str, Any]:
    left_payload, left = _load_mcp_agent_manifest(left_manifest)
    right_payload, right = _load_mcp_agent_manifest(right_manifest)
    return {
        "schema": "agilab.mcp.compare_agent_runs.v1",
        "left_manifest": str(left),
        "right_manifest": str(right),
        "comparison": agent_run.compare_agent_runs(left_payload, right_payload),
    }


def validate_agent_run(manifest_path: str | Path) -> dict[str, Any]:
    manifest, path = _load_mcp_agent_manifest(manifest_path)
    return {
        "schema": "agilab.mcp.validate_agent_run.v1",
        "manifest_path": str(path),
        "validation": agent_run.validate_agent_run(manifest),
    }


def read_manifest(manifest_path: str | Path) -> dict[str, Any]:
    path = _mcp_read_path(manifest_path, purpose="manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Manifest must be a JSON object: {path}")
    if payload.get("kind") == agent_run.TRACE_KIND:
        payload = _canonicalize_agent_manifest_resources(
            payload,
            manifest_path=path,
        )
    else:
        payload = _canonicalize_run_manifest_resources(
            payload,
            manifest_path=path,
        )
    return {
        "schema": "agilab.mcp.read_manifest.v1",
        "manifest_path": str(path),
        "manifest": redact_mapping(payload),
    }


def summarize_run(manifest_path: str | Path) -> dict[str, Any]:
    manifest, _, resolved = _load_mcp_run_manifest(
        manifest_path,
        purpose="run manifest",
    )
    return {
        "schema": "agilab.mcp.summarize_run.v1",
        "manifest_path": str(resolved),
        "summary": run_manifest.manifest_summary(manifest),
    }


def list_artifacts(manifest_path: str | Path) -> dict[str, Any]:
    manifest, _, resolved = _load_mcp_run_manifest(
        manifest_path,
        purpose="run manifest",
    )
    return {
        "schema": "agilab.mcp.list_artifacts.v1",
        "manifest_path": str(resolved),
        "artifacts": bridge_cli._artifact_rows(manifest, resolved),
    }


def compare_runs(
    left_manifest: str | Path, right_manifest: str | Path
) -> dict[str, Any]:
    left, _, left_path = _load_mcp_run_manifest(
        left_manifest,
        purpose="left run manifest",
    )
    right, _, right_path = _load_mcp_run_manifest(
        right_manifest,
        purpose="right run manifest",
    )
    left_summary = run_manifest.manifest_summary(left)
    right_summary = run_manifest.manifest_summary(right)
    return {
        "schema": "agilab.mcp.compare_runs.v1",
        "left_manifest": str(left_path),
        "right_manifest": str(right_path),
        "status_changed": left.status != right.status,
        "duration_delta_seconds": right.timing.duration_seconds
        - left.timing.duration_seconds,
        "artifact_count_delta": right_summary["artifact_count"]
        - left_summary["artifact_count"],
        "left": left_summary,
        "right": right_summary,
    }


def export_quarto_report(
    manifest_path: str | Path, output_path: str | Path
) -> dict[str, Any]:
    manifest, payload, resolved = _load_mcp_run_manifest(
        manifest_path,
        purpose="run manifest",
    )
    output = _mcp_read_path(output_path, purpose="report output")
    return bridge_cli._export_quarto_report_loaded(
        manifest,
        payload,
        resolved,
        output,
        render=False,
    )


_CAPABILITIES_FILENAME = "agilab-capabilities.json"

# Deterministic "start here" workflow for a fresh agent. Ordered cheapest /
# safest first so an agent orients before acting.
_QUICKSTART_WORKFLOW = (
    "agent_context — build a safe, redacted context pack from prior agent-run evidence before acting.",
    "list_agent_runs — discover recent runs; read_agent_run / summarize_agent_run to inspect one.",
    "agent_handoff — get a compact continuation card; agent_next_actions for deterministic next steps.",
    "list_projects / list_runs — enumerate apps and run manifests on disk.",
    "read_manifest / summarize_run / list_artifacts — inspect a specific run's evidence.",
)


def _capabilities_manifest_path(explicit: str | Path | None = None) -> Path | None:
    """Resolve the capabilities manifest.

    An explicit path wins or fails (no silent fallback to a different manifest).
    Otherwise auto-discover via env var, repo root, then cwd.
    """
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        return (
            _mcp_read_path(candidate, purpose="capabilities manifest")
            if candidate.is_file()
            else None
        )
    candidates: list[tuple[Path, bool]] = []
    env_value = os.environ.get("AGILAB_CAPABILITIES_MANIFEST")
    if env_value:
        candidates.append((Path(env_value).expanduser(), True))
    for parent in Path(__file__).resolve().parents:
        candidates.append((parent / _CAPABILITIES_FILENAME, False))
    candidates.append((Path.cwd() / _CAPABILITIES_FILENAME, False))
    for candidate, configured in candidates:
        if candidate.is_file():
            try:
                return _mcp_read_path(candidate, purpose="capabilities manifest")
            except ValueError:
                if configured:
                    raise
    return None


def agent_quickstart(
    capabilities_path: str | Path | None = None,
    max_items: int = 20,
) -> dict[str, Any]:
    """Return a bounded 'start here' overview for a fresh agent.

    Condenses the capabilities manifest (boundary, CLI commands, app/skill
    names, counts) plus a recommended workflow so an agent can orient without
    reading the full multi-thousand-line manifest. Degrades gracefully when the
    manifest is absent — the safety boundary, workflow, and pointers always
    return. (The server layer also injects the live MCP tool list.)
    """
    limit = max(1, int(max_items))
    overview: dict[str, Any] = {
        "tool": "agilab",
        "read_only_boundary": {
            "local_files_only": True,
            "execution_tools_enabled": False,
            "shell_enabled": False,
        },
        "recommended_workflow": list(_QUICKSTART_WORKFLOW),
    }

    path = _capabilities_manifest_path(capabilities_path)
    if path is None:
        overview["capabilities_manifest"] = None
        overview["note"] = (
            "Capabilities manifest not found; set AGILAB_CAPABILITIES_MANIFEST or "
            "run from the repo root. Use tools/list for full MCP tool schemas."
        )
        return overview

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        overview["capabilities_manifest"] = None
        overview["note"] = f"Capabilities manifest unreadable: {exc}"
        return overview
    if not isinstance(manifest, Mapping):
        overview["capabilities_manifest"] = None
        overview["note"] = "Capabilities manifest is not a JSON object."
        return overview

    def _items(key: str) -> list[Any]:
        value = manifest.get(key)
        return value if isinstance(value, list) else []

    boundary = manifest.get("boundary")
    overview["capabilities_manifest"] = str(path)
    overview["what_is_agilab"] = (
        boundary.get("proves") if isinstance(boundary, Mapping) else None
    )
    overview["cli_commands"] = [
        {
            "command": item.get("command"),
            "kind": item.get("kind"),
            "maturity": item.get("maturity"),
            "description": item.get("description"),
        }
        for item in _items("cli_commands")[:limit]
        if isinstance(item, Mapping)
    ]
    overview["public_apps"] = [
        item.get("project")
        for item in _items("public_apps")[:limit]
        if isinstance(item, Mapping) and item.get("project")
    ]
    overview["agent_skills"] = [
        item.get("name")
        for item in _items("agent_skills")[:limit]
        if isinstance(item, Mapping) and item.get("name")
    ]
    overview["docs"] = [
        {"title": item.get("title"), "path": item.get("path")}
        for item in _items("docs")[:limit]
        if isinstance(item, Mapping)
    ]
    overview["counts"] = {
        key: len(_items(key))
        for key in (
            "cli_commands",
            "streamlit_pages",
            "packages",
            "public_apps",
            "agent_skills",
            "evidence_schemas",
        )
    }
    overview["full_manifest_hint"] = (
        f"Read {path.name} for full detail (evidence_schemas, packages, schemas)."
    )
    return overview
