"""Reusable Streamlit UI helpers for AGILAB workflow pages."""

from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode

MAX_INLINE_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_INLINE_PREVIEW_BYTES = 256 * 1024
MAX_ACTION_HISTORY_ITEMS = 8
DAG_WORKER_BASE_CLASSES = {"DagWorker", "Sb3TrainerWorker"}

PROJECT_UI_STATE_KEY = "agilab:workflow_ui_state"
ACTION_HISTORY_KEY = "agilab:workflow_action_history"

_TEXT_PREVIEW_SUFFIXES = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".py",
    ".text",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_IMAGE_PREVIEW_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
_COCKPIT_ARTIFACT_SUFFIXES = {
    ".csv",
    ".html",
    ".ipynb",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".npz",
    ".parquet",
    ".png",
    ".svg",
    ".toml",
    ".txt",
}
_COCKPIT_SCAN_LIMIT = 200
_COCKPIT_MAX_DRAWER_ARTIFACTS = 12


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _call_container_method(container: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(container, name, None)
    if callable(method):
        return method(*args, **kwargs)
    return None


def _stable_key_part(value: Any) -> str:
    text = _as_text(value)
    cleaned = "".join(char if char.isalnum() or char in "._:-" else "_" for char in text)
    return cleaned[:96] or "item"


def workflow_state_scope(page_label: str, env: Any | None = None) -> str:
    """Return a stable session-state scope for per-project workflow UI data."""
    page = _as_text(page_label) or "PAGE"
    app_name = _as_text(getattr(env, "app", ""))
    target_name = _as_text(getattr(env, "target", ""))
    parts = [page, app_name or "global"]
    if target_name and target_name != app_name:
        parts.append(target_name)
    return "::".join(parts)


def project_widget_key(page_label: str, env: Any | None, key: Any) -> str:
    """Return a widget key scoped to one page and one active project."""
    return f"{workflow_state_scope(page_label, env)}::{_stable_key_part(key)}"


def project_state_key(page_label: str, env: Any | None, key: Any) -> str:
    """Return a non-widget session key scoped to one page and one active project."""
    return f"{workflow_state_scope(page_label, env)}::state::{_stable_key_part(key)}"


def _identity_tokens(value: Any) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", _as_text(value).lower()) if token}


def _app_identity_values(env: Any | None, app_state_name: Any = "") -> set[str]:
    values: set[str] = set()
    if _as_text(app_state_name):
        values.add(_as_text(app_state_name))
    if env is not None:
        for attr in ("app", "target", "active_app"):
            raw_value = getattr(env, attr, None)
            if raw_value:
                values.add(Path(_as_text(raw_value)).name)
    return {value.lower() for value in values if value}


def is_dag_worker_base(value: Any) -> bool:
    """Return whether an ``AgiEnv.base_worker_cls`` value describes a DAG worker."""
    if not value:
        return False
    class_name = str(value).split(".")[-1]
    if class_name in DAG_WORKER_BASE_CLASSES:
        return True
    return "dag" in class_name.lower()


def is_dag_based_app(env: Any | None, app_state_name: Any = "") -> bool:
    """Detect DAG-style apps from AgiEnv metadata without importing worker classes."""
    if is_dag_worker_base(getattr(env, "base_worker_cls", None)):
        return True
    return any("dag" in _identity_tokens(value) for value in _app_identity_values(env, app_state_name))


def remember_project_ui_state(
    session_state: Any,
    *,
    page_label: str,
    env: Any | None = None,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist generic UI state under the current page/project scope."""
    root = session_state.setdefault(PROJECT_UI_STATE_KEY, {})
    if not isinstance(root, dict):
        root = {}
        session_state[PROJECT_UI_STATE_KEY] = root
    scope = workflow_state_scope(page_label, env)
    bucket = root.setdefault(scope, {})
    if not isinstance(bucket, dict):
        bucket = {}
        root[scope] = bucket
    bucket.update(dict(values))
    return dict(bucket)


def restore_project_ui_state(
    session_state: Any,
    *,
    page_label: str,
    env: Any | None = None,
) -> dict[str, Any]:
    """Return generic UI state saved for the current page/project scope."""
    root = session_state.get(PROJECT_UI_STATE_KEY, {})
    if not isinstance(root, dict):
        return {}
    bucket = root.get(workflow_state_scope(page_label, env), {})
    return dict(bucket) if isinstance(bucket, dict) else {}


def _project_display_name(env: Any | None) -> str:
    if env is None:
        return "No project"
    for attr in ("app", "target", "active_app"):
        value = _as_text(getattr(env, attr, ""))
        if value:
            return Path(value).name
    return "No project"


def _project_path(env: Any | None) -> Path | None:
    if env is None:
        return None
    for attr in ("active_app", "app_path"):
        path = _path_from(getattr(env, attr, None))
        if path is not None:
            return path
    apps_path = _path_from(getattr(env, "apps_path", None))
    app_name = _as_text(getattr(env, "app", ""))
    if apps_path is not None and app_name:
        return apps_path / app_name
    return None


def _runtime_roots(env: Any | None) -> list[Path]:
    if env is None:
        return []
    roots: list[Path] = []
    seen: set[str] = set()

    def append(path: Any) -> None:
        candidate = _path_from(path)
        if candidate is None:
            return
        key = candidate.expanduser().as_posix()
        if key not in seen:
            seen.add(key)
            roots.append(candidate)

    append(getattr(env, "runenv", None))
    append(getattr(env, "app_data_rel", None))
    export_root = _path_from(getattr(env, "AGILAB_EXPORT_ABS", None))
    if export_root is not None:
        append(export_root)
        target_name = _as_text(getattr(env, "target", ""))
        if target_name:
            append(export_root / target_name)
    project_root = _project_path(env)
    if project_root is not None:
        append(project_root / "notebooks")
        append(project_root / "artifacts")
    return roots


def _latest_timestamp_label(timestamp: float | None) -> str:
    if timestamp is None:
        return "no file timestamp"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def _artifact_label(path: Path) -> str:
    if path.name == "run_manifest.json":
        return "Run manifest"
    suffix = path.suffix.lower()
    if suffix == ".log":
        return "Runtime log"
    if suffix in {".csv", ".parquet"}:
        return "Table"
    if suffix in {".png", ".svg"}:
        return "Figure"
    if suffix == ".ipynb":
        return "Notebook"
    if suffix == ".json":
        return "JSON evidence"
    return path.name


def _artifact_kind_label(path: Path) -> str:
    if path.name == "run_manifest.json":
        return "manifest"
    return path.suffix.lower().lstrip(".") or "file"


def _artifact_description(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _scan_project_evidence(env: Any | None) -> dict[str, Any]:
    count = 0
    latest: float | None = None
    manifest: Path | None = None
    examples: list[str] = []
    artifact_rows: list[tuple[float, Path, Path]] = []
    truncated = False
    ignored_dirs = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "venv",
    }
    for root in _runtime_roots(env):
        try:
            if not root.exists():
                continue
            if root.is_file():
                paths = [root]
            else:
                paths = []
                for current_root, dirs, files in os.walk(root):
                    dirs[:] = sorted(
                        dirname
                        for dirname in dirs
                        if dirname not in ignored_dirs and not dirname.startswith(".")
                    )
                    for filename in sorted(files):
                        paths.append(Path(current_root) / filename)
                    if count + len(paths) >= _COCKPIT_SCAN_LIMIT:
                        truncated = True
                        break
            for path in paths:
                suffix = path.suffix.lower()
                if path.name == "run_manifest.json" and manifest is None:
                    manifest = path
                if suffix not in _COCKPIT_ARTIFACT_SUFFIXES and path.name != "run_manifest.json":
                    continue
                count += 1
                if len(examples) < 3:
                    examples.append(path.name)
                try:
                    mtime = path.stat().st_mtime
                    artifact_rows.append((mtime, path, root))
                    latest = max(latest or mtime, mtime)
                except OSError:
                    pass
                if count >= _COCKPIT_SCAN_LIMIT:
                    truncated = True
                    break
            if count >= _COCKPIT_SCAN_LIMIT:
                break
        except OSError:
            continue
    return {
        "count": count,
        "latest": latest,
        "manifest": manifest,
        "examples": examples,
        "artifacts": [
            {
                "label": _artifact_label(path),
                "path": path,
                "kind": _artifact_kind_label(path),
                "description": _artifact_description(path, root),
                "preview": path.suffix.lower()
                in (_TEXT_PREVIEW_SUFFIXES | _IMAGE_PREVIEW_SUFFIXES),
            }
            for _mtime, path, root in sorted(
                artifact_rows,
                key=lambda row: (-row[0], row[1].as_posix()),
            )[:_COCKPIT_MAX_DRAWER_ARTIFACTS]
        ],
        "truncated": truncated,
    }


def _project_install_status(env: Any | None) -> tuple[str, str, str]:
    if env is None:
        return "Unknown", "environment not loaded", "incomplete"
    try:
        from agilab.environment_health import _default_install_status

        status = _default_install_status(env)
    except Exception:
        return "Check", "install status unavailable", "incomplete"
    workerless = bool(status.get("workerless"))
    manager_ready = bool(status.get("manager_ready"))
    worker_ready = bool(status.get("worker_ready"))
    manager_exists = bool(status.get("manager_exists"))
    worker_exists = bool(status.get("worker_exists"))
    if manager_ready and (workerless or worker_ready):
        return "Ready", "manager and worker ready" if not workerless else "manager ready", "ready"
    if manager_exists or worker_exists:
        return "Incomplete", "rerun INSTALL before EXECUTE", "incomplete"
    return "Not installed", "run ORCHESTRATE -> INSTALL", "incomplete"


def _run_history(env: Any | None) -> tuple[str, str, str]:
    if env is None:
        return "0", "environment not loaded", "incomplete"
    try:
        from agilab.environment_health import run_history_summary

        count, caption = run_history_summary(env)
    except Exception:
        count, caption = "0", "run log status unavailable"
    state = "ready" if count not in {"", "0"} else "incomplete"
    return count, caption, state


def _project_page_url(page_name: str, env: Any | None) -> str:
    params: dict[str, str] = {}
    active_app = _as_text(getattr(env, "app", "") if env is not None else "")
    if active_app:
        params["active_app"] = active_app
    query = urlencode(params)
    return f"/{page_name}?{query}" if query else f"/{page_name}"


def _project_next_action(
    env: Any | None,
    *,
    project_ready: bool,
    install_value: str,
    run_value: str,
    artifact_count: int,
) -> dict[str, str]:
    if not project_ready:
        return {
            "id": "project",
            "label": "Create or select project",
            "detail": "Choose a project before installing, executing, or reviewing evidence.",
            "url": _project_page_url("PROJECT", env),
            "type": "primary",
        }
    if artifact_count:
        return {
            "id": "analysis",
            "label": "Review evidence",
            "detail": "Open ANALYSIS on the selected project outputs.",
            "url": _project_page_url("ANALYSIS", env),
            "type": "primary",
        }
    if install_value != "Ready":
        return {
            "id": "install",
            "label": "Install project",
            "detail": "Prepare the manager and worker environments before execution.",
            "url": _project_page_url("ORCHESTRATE", env),
            "type": "primary",
        }
    if run_value in {"", "0"}:
        return {
            "id": "execute",
            "label": "Execute project",
            "detail": "Run the project once to create logs, manifests, and artifacts.",
            "url": _project_page_url("ORCHESTRATE", env),
            "type": "primary",
        }
    return {
        "id": "execute",
        "label": "Create evidence",
        "detail": "Run ORCHESTRATE -> EXECUTE so ANALYSIS has outputs to inspect.",
        "url": _project_page_url("ORCHESTRATE", env),
        "type": "primary",
    }


def _render_cockpit_card(streamlit: Any, *, label: str, value: str, caption: str, state: str) -> None:
    streamlit.markdown(
        (
            f"<div class='agilab-header-card agilab-header-card--{html.escape(state)}'>"
            f"<div class='agilab-header-label'>{html.escape(label)}</div>"
            f"<div class='agilab-header-value agilab-header-value--{html.escape(state)}'>{html.escape(value)}</div>"
            f"<div class='agilab-header-caption'>{html.escape(caption)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _project_cockpit_cards(page_label: str, env: Any | None) -> list[dict[str, str]]:
    del page_label
    install_value, install_caption, install_state = _project_install_status(env)
    run_value, run_caption, run_state = _run_history(env)
    evidence = _scan_project_evidence(env)
    artifact_count = int(evidence["count"])
    artifact_suffix = "+" if evidence["truncated"] else ""
    artifact_value = f"{artifact_count}{artifact_suffix} artifact"
    if artifact_count != 1 or artifact_suffix:
        artifact_value += "s"
    if evidence["manifest"] is not None:
        evidence_value = artifact_value
        evidence_caption = f"manifest: {Path(evidence['manifest']).name}"
        evidence_state = "ready"
    elif artifact_count:
        evidence_value = artifact_value
        evidence_caption = ", ".join(evidence["examples"]) or "artifact files detected"
        evidence_state = "ready"
    else:
        evidence_value = "No evidence"
        evidence_caption = "run ORCHESTRATE -> EXECUTE"
        evidence_state = "incomplete"
    return [
        {
            "label": "Install",
            "value": install_value,
            "caption": install_caption,
            "state": install_state,
        },
        {
            "label": "Last run",
            "value": run_value,
            "caption": run_caption,
            "state": run_state,
        },
        {
            "label": "Evidence",
            "value": evidence_value,
            "caption": evidence_caption,
            "state": evidence_state,
        },
    ]


def project_next_action(env: Any | None) -> dict[str, str]:
    """Return the next user-facing action implied by current project state."""
    project_root = _project_path(env)
    project_ready = bool(project_root and (project_root.exists() or project_root.is_symlink()))
    install_value, _install_caption, _install_state = _project_install_status(env)
    run_value, _run_caption, _run_state = _run_history(env)
    evidence = _scan_project_evidence(env)
    return _project_next_action(
        env,
        project_ready=project_ready,
        install_value=install_value,
        run_value=run_value,
        artifact_count=int(evidence["count"]),
    )


def render_next_best_action(
    streamlit: Any,
    *,
    env: Any | None,
    key_prefix: str,
    title: str = "Next",
) -> dict[str, str]:
    """Render one navigation CTA derived from project readiness."""
    action = project_next_action(env)
    streamlit.caption(f"{title}: {action['detail']}")
    link_button = getattr(streamlit, "link_button", None)
    if callable(link_button):
        link_button(
            action["label"],
            action["url"],
            key=f"{key_prefix}:next:{_stable_key_part(action['id'])}",
            type=action.get("type", "primary"),
            width="content",
        )
    else:
        streamlit.markdown(f"[{action['label']}]({action['url']})")
    return action


def project_evidence_artifacts(env: Any | None) -> list[dict[str, Any]]:
    """Return latest evidence artifacts for the selected project."""
    return list(_scan_project_evidence(env).get("artifacts", []))


def render_project_evidence_drawer(
    streamlit: Any,
    *,
    env: Any | None,
    key_prefix: str,
    title: str = "Evidence drawer",
    expanded: bool = False,
) -> None:
    """Render latest project evidence in one reusable drawer."""
    artifacts = project_evidence_artifacts(env)
    if not artifacts:
        expander = streamlit.expander(title, expanded=expanded)
        with expander:
            _call_container_method(
                expander,
                "caption",
                "No evidence files found yet. Run ORCHESTRATE -> EXECUTE first.",
            )
        return
    render_artifact_drawer(
        streamlit,
        artifacts=artifacts,
        key_prefix=key_prefix,
        title=title,
        expanded=expanded,
    )


def _render_project_status_body(
    streamlit: Any,
    *,
    page_label: str,
    env: Any,
    key_prefix: str,
) -> None:
    cards = _project_cockpit_cards(page_label, env)
    columns = streamlit.columns(len(cards))
    for column, card in zip(columns, cards):
        with column:
            _render_cockpit_card(streamlit, **card)
    render_next_best_action(
        streamlit,
        env=env,
        key_prefix=key_prefix,
    )


def render_project_status_page(streamlit: Any, *, env: Any | None = None) -> None:
    """Render the PROJECT status menu page."""
    if env is None:
        return None
    if not callable(getattr(streamlit, "markdown", None)) or not callable(
        getattr(streamlit, "columns", None)
    ):
        return None
    _render_project_status_body(
        streamlit,
        page_label="PROJECT",
        env=env,
        key_prefix="project_status_page",
    )
    return None


def _render_context_link(
    streamlit: Any,
    *,
    label: str,
    url: str,
    key: str,
    type: str = "secondary",
) -> None:
    link_button = getattr(streamlit, "link_button", None)
    if callable(link_button):
        link_button(label, url, key=key, type=type, width="content")
        return
    streamlit.markdown(f"[{label}]({url})")


def render_context_expander(
    streamlit: Any,
    *,
    page_label: str,
    env: Any | None = None,
    expanded: bool = False,
) -> None:
    """Render compact project context on execution/review pages without selectors."""
    if env is None:
        return None
    if not callable(getattr(streamlit, "expander", None)) or not callable(
        getattr(streamlit, "columns", None)
    ):
        return None

    normalized_page = _stable_key_part(page_label).upper()
    title = {
        "WORKFLOW": "Workflow context",
        "ANALYSIS": "Analysis context",
    }.get(normalized_page, "Project context")
    key_root = f"context_expander:{_stable_key_part(page_label)}"
    with streamlit.expander(title, expanded=expanded):
        _render_project_status_body(
            streamlit,
            page_label=normalized_page,
            env=env,
            key_prefix=key_root,
        )
        link_columns = streamlit.columns(3)
        with link_columns[0]:
            _render_context_link(
                streamlit,
                label="Change project",
                url=_project_page_url("PROJECT_STATUS", env),
                key=f"{key_root}:change_project",
            )
        with link_columns[1]:
            target_page = "ORCHESTRATE" if normalized_page == "ANALYSIS" else "ANALYSIS"
            target_label = "Run again" if normalized_page == "ANALYSIS" else "Analyze"
            _render_context_link(
                streamlit,
                label=target_label,
                url=_project_page_url(target_page, env),
                key=f"{key_root}:{_stable_key_part(target_label)}",
            )
        with link_columns[2]:
            peer_page = "WORKFLOW" if normalized_page == "ANALYSIS" else "ORCHESTRATE"
            peer_label = "Open workflow" if normalized_page == "ANALYSIS" else "Run"
            _render_context_link(
                streamlit,
                label=peer_label,
                url=_project_page_url(peer_page, env),
                key=f"{key_root}:{_stable_key_part(peer_label)}",
            )
    return None


def render_page_context(streamlit: Any, *, page_label: str, env: Any | None = None) -> None:
    """Render the compact project cockpit as an optional expander."""
    if env is None:
        return None
    if not callable(getattr(streamlit, "markdown", None)) or not callable(
        getattr(streamlit, "columns", None)
    ):
        return None

    def _render_body(*, render_fallback_title: bool = False) -> None:
        if render_fallback_title:
            streamlit.markdown("### Project status")
        _render_project_status_body(
            streamlit,
            page_label=page_label,
            env=env,
            key_prefix=f"project_cockpit:{_stable_key_part(page_label)}",
        )

    expander_fn = getattr(streamlit, "expander", None)
    container_fn = getattr(streamlit, "container", None)
    if callable(expander_fn):
        context = expander_fn("Project status", expanded=False)
        render_fallback_title = False
    else:
        context = container_fn(border=True) if callable(container_fn) else streamlit
        render_fallback_title = True
    if hasattr(context, "__enter__") and hasattr(context, "__exit__"):
        with context:
            _render_body(render_fallback_title=render_fallback_title)
    else:
        _render_body(render_fallback_title=render_fallback_title)
    return None


def _download_log_button(
    container: Any,
    *,
    body: str,
    key: str,
    file_name: str,
) -> None:
    download_button = getattr(container, "download_button", None)
    if not callable(download_button):
        return
    download_button(
        "Download logs",
        data=body,
        file_name=file_name,
        mime="text/plain",
        key=key,
        disabled=not bool(body.strip()),
        width="stretch",
    )


def render_log_actions(
    streamlit: Any,
    *,
    body: str,
    download_key: str,
    file_name: str,
    clear_key: str | None = None,
    clear_label: str = "Clear logs",
) -> bool:
    """Render standard log actions and return whether clear was requested."""
    text = str(body or "")
    if clear_key:
        download_col, clear_col = streamlit.columns([1, 1])
        _download_log_button(download_col, body=text, key=download_key, file_name=file_name)
        return bool(
            clear_col.button(
                clear_label,
                key=clear_key,
                type="secondary",
                disabled=not bool(text.strip()),
                help="Clear the current log panel.",
                width="stretch",
            )
        )
    _download_log_button(streamlit, body=text, key=download_key, file_name=file_name)
    return False


def render_action_readiness(
    streamlit: Any,
    *,
    actions: Iterable[tuple[str, bool, str]],
    title: str = "Action status",
) -> None:
    """Show enabled/blocked action state in a consistent compact expander."""
    entries = [(label, enabled, _as_text(reason)) for label, enabled, reason in actions]
    if not entries:
        return
    expander = streamlit.expander(title, expanded=False)
    with expander:
        for label, enabled, reason in entries:
            status = "Ready" if enabled else reason or "Unavailable"
            _call_container_method(expander, "caption", f"{label}: {status}")


def _path_from(value: Any) -> Path | None:
    try:
        return Path(value) if value else None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _dataframe_shape(dataframe: Any) -> tuple[int, int] | None:
    if getattr(dataframe, "empty", True):
        return None
    shape = getattr(dataframe, "shape", None)
    if not isinstance(shape, tuple) or len(shape) < 2:
        return None
    try:
        return int(shape[0]), int(shape[1])
    except (TypeError, ValueError):
        return None


def _graph_shape(graph: Any) -> tuple[int, int] | None:
    number_of_nodes = getattr(graph, "number_of_nodes", None)
    number_of_edges = getattr(graph, "number_of_edges", None)
    if not callable(number_of_nodes) or not callable(number_of_edges):
        return None
    try:
        return int(number_of_nodes()), int(number_of_edges())
    except (TypeError, ValueError):
        return None


def _render_output_download(streamlit: Any, *, path: Path, key: str) -> None:
    download_button = getattr(streamlit, "download_button", None)
    if not callable(download_button) or not path.is_file():
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size > MAX_INLINE_DOWNLOAD_BYTES:
        streamlit.caption(f"Output file is too large for inline download: {path.name}")
        return
    try:
        data = path.read_bytes()
    except OSError:
        return
    download_button(
        "Download output",
        data=data,
        file_name=path.name,
        key=key,
        width="stretch",
    )


def render_latest_outputs(
    streamlit: Any,
    *,
    source_path: Any = None,
    dataframe: Any = None,
    graph: Any = None,
    key_prefix: str,
) -> None:
    """Render a compact latest-output summary with an optional direct download."""
    df_shape = _dataframe_shape(dataframe)
    graph_shape = _graph_shape(graph)
    path = _path_from(source_path)
    if df_shape is None and graph_shape is None and path is None:
        return

    expander = streamlit.expander("Latest outputs", expanded=False)
    with expander:
        if df_shape is not None:
            rows, columns = df_shape
            _call_container_method(expander, "caption", f"Dataframe: {rows} row(s), {columns} column(s)")
        if graph_shape is not None:
            nodes, edges = graph_shape
            _call_container_method(expander, "caption", f"Graph: {nodes} node(s), {edges} edge(s)")
        if path is not None:
            _call_container_method(expander, "caption", f"Source: {path}")
            _render_output_download(expander, path=path, key=f"{key_prefix}:download_output")


def _normalize_status(raw_status: Any) -> str:
    if raw_status is True:
        return "Done"
    if raw_status is False:
        return "Blocked"
    status = _as_text(raw_status).lower()
    return {
        "active": "Active",
        "blocked": "Blocked",
        "complete": "Done",
        "completed": "Done",
        "done": "Done",
        "error": "Failed",
        "failed": "Failed",
        "idle": "Waiting",
        "info": "Info",
        "ready": "Ready",
        "running": "Running",
        "skipped": "Skipped",
        "success": "Done",
        "warning": "Needs attention",
        "waiting": "Waiting",
    }.get(status, _as_text(raw_status) or "Waiting")


def _normalize_workflow_item(item: Any) -> tuple[str, str, str]:
    if isinstance(item, Mapping):
        return (
            _as_text(item.get("label") or item.get("name")),
            _normalize_status(item.get("state") if "state" in item else item.get("status")),
            _as_text(item.get("detail") or item.get("reason") or item.get("path")),
        )
    if isinstance(item, (list, tuple)):
        label = _as_text(item[0]) if len(item) > 0 else ""
        status = _normalize_status(item[1]) if len(item) > 1 else "Waiting"
        detail = _as_text(item[2]) if len(item) > 2 else ""
        return label, status, detail
    return _as_text(item), "Waiting", ""


def render_workflow_timeline(
    streamlit: Any,
    *,
    items: Iterable[Any],
    title: str = "Workflow",
    expanded: bool = False,
) -> None:
    """Render a compact generic workflow timeline."""
    rows = [_normalize_workflow_item(item) for item in items]
    rows = [(label, status, detail) for label, status, detail in rows if label]
    if not rows:
        return

    expander = streamlit.expander(title, expanded=expanded)
    with expander:
        for index, (label, status, detail) in enumerate(rows, start=1):
            suffix = f": {detail}" if detail else ""
            _call_container_method(expander, "caption", f"{index}. {label} - {status}{suffix}")


def _normalize_command(command: Any) -> dict[str, Any] | None:
    if isinstance(command, Mapping):
        label = _as_text(command.get("label") or command.get("name") or command.get("id"))
        command_id = _as_text(command.get("id") or label)
        enabled = bool(command.get("enabled", True))
        reason = _as_text(command.get("reason") or command.get("help"))
        button_type = _as_text(command.get("type")) or "secondary"
    elif isinstance(command, (list, tuple)):
        label = _as_text(command[0]) if len(command) > 0 else ""
        command_id = _stable_key_part(command[1] if len(command) > 1 else label)
        enabled = bool(command[2]) if len(command) > 2 else True
        reason = _as_text(command[3]) if len(command) > 3 else ""
        button_type = _as_text(command[4]) if len(command) > 4 else "secondary"
    else:
        label = _as_text(command)
        command_id = _stable_key_part(label)
        enabled = True
        reason = ""
        button_type = "secondary"
    if not label or not command_id:
        return None
    if button_type not in {"primary", "secondary", "tertiary"}:
        button_type = "secondary"
    return {
        "id": command_id,
        "label": label,
        "enabled": enabled,
        "reason": reason,
        "type": button_type,
    }


def render_command_bar(
    streamlit: Any,
    *,
    commands: Iterable[Any],
    key_prefix: str,
    title: str = "Quick actions",
    max_columns: int = 4,
) -> str | None:
    """Render a compact command bar and return the selected command id."""
    items = [item for item in (_normalize_command(command) for command in commands) if item]
    if not items:
        return None

    _call_container_method(streamlit, "caption", title)
    column_count = max(1, min(int(max_columns or 1), len(items)))
    columns = streamlit.columns(column_count)
    selected: str | None = None
    for index, item in enumerate(items):
        column = columns[index % column_count]
        disabled = not bool(item["enabled"])
        help_text = item["reason"] if disabled and item["reason"] else item["reason"] or None
        clicked = column.button(
            item["label"],
            key=f"{key_prefix}:command:{_stable_key_part(item['id'])}",
            type=item["type"],
            disabled=disabled,
            help=help_text,
            width="stretch",
        )
        if clicked:
            selected = str(item["id"])
    return selected


def _artifact_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".json":
        return "application/json"
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix in _IMAGE_PREVIEW_SUFFIXES:
        return f"image/{'jpeg' if suffix in {'.jpg', '.jpeg'} else suffix.lstrip('.')}"
    return "text/plain"


def _artifact_kind(path: Path | None, explicit_kind: Any = None) -> str:
    explicit = _as_text(explicit_kind)
    if explicit:
        return explicit
    if path is None:
        return "artifact"
    suffix = path.suffix.lower().lstrip(".")
    return suffix or ("folder" if path.is_dir() else "file")


def _artifact_status(path: Path | None) -> str:
    if path is None:
        return "No path"
    try:
        if path.is_file():
            return "Ready"
        if path.is_dir():
            return "Folder"
    except OSError:
        return "Unavailable"
    return "Missing"


def _normalize_artifact(artifact: Any) -> dict[str, Any] | None:
    if isinstance(artifact, Mapping):
        raw_path = artifact.get("path") or artifact.get("file") or artifact.get("source")
        description = _as_text(artifact.get("description") or artifact.get("detail"))
        if not raw_path and not description:
            return None
        path = _path_from(raw_path)
        if path is None and not description:
            return None
        label = _as_text(artifact.get("label") or artifact.get("name"))
        if not label and path is not None:
            label = path.name or str(path)
        return {
            "label": label or "Artifact",
            "path": path,
            "kind": _artifact_kind(path, artifact.get("kind") or artifact.get("type")),
            "description": description,
            "preview": bool(artifact.get("preview", True)),
        }
    path = _path_from(artifact)
    if path is None:
        return None
    return {
        "label": path.name or str(path),
        "path": path,
        "kind": _artifact_kind(path),
        "description": "",
        "preview": True,
    }


def _render_artifact_download(container: Any, *, path: Path, key: str, label: str = "Download") -> None:
    download_button = getattr(container, "download_button", None)
    if not callable(download_button) or not path.is_file():
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size > MAX_INLINE_DOWNLOAD_BYTES:
        _call_container_method(container, "caption", f"{path.name} is too large for inline download.")
        return
    try:
        data = path.read_bytes()
    except OSError:
        return
    download_button(
        label,
        data=data,
        file_name=path.name,
        mime=_artifact_mime(path),
        key=key,
        width="stretch",
    )


def _read_text_preview(path: Path, *, max_bytes: int = MAX_INLINE_PREVIEW_BYTES) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size > max_bytes:
        return f"{path.name} is too large for inline preview."
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _render_artifact_preview(container: Any, *, path: Path, kind: str) -> None:
    if not path.is_file():
        return
    suffix = path.suffix.lower()
    if suffix in _IMAGE_PREVIEW_SUFFIXES:
        image = getattr(container, "image", None)
        if callable(image):
            image(str(path), caption=path.name, width="stretch")
        return
    if suffix not in _TEXT_PREVIEW_SUFFIXES:
        return

    if suffix == ".json":
        preview_text = _read_text_preview(path)
        if not preview_text:
            return
        try:
            payload = json.loads(preview_text)
        except json.JSONDecodeError:
            payload = None
        json_view = getattr(container, "json", None)
        if callable(json_view) and payload is not None:
            json_view(payload)
            return
        if payload is not None:
            preview_text = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        preview_text = _read_text_preview(path)

    if not preview_text:
        return
    language = {"py": "python", "toml": "toml", "json": "json"}.get(kind.lower(), "text")
    _call_container_method(container, "code", preview_text[:MAX_INLINE_PREVIEW_BYTES], language=language)


def render_artifact_drawer(
    streamlit: Any,
    *,
    artifacts: Iterable[Any],
    key_prefix: str,
    title: str = "Artifacts",
    expanded: bool = False,
) -> None:
    """Render generic artifacts with status, download, and small inline previews."""
    items = [item for item in (_normalize_artifact(artifact) for artifact in artifacts) if item]
    if not items:
        return

    expander = streamlit.expander(title, expanded=expanded)
    with expander:
        for index, item in enumerate(items):
            path = item["path"]
            label = item["label"]
            status = _artifact_status(path)
            kind = _as_text(item["kind"]) or "artifact"
            detail = f" ({kind})" if kind else ""
            _call_container_method(expander, "caption", f"{label}: {status}{detail}")
            if item["description"]:
                _call_container_method(expander, "caption", item["description"])
            if path is not None:
                _call_container_method(expander, "caption", f"Path: {path}")
                _render_artifact_download(
                    expander,
                    path=path,
                    key=f"{key_prefix}:artifact:{index}:{_stable_key_part(label)}",
                )
                if item["preview"]:
                    _render_artifact_preview(expander, path=path, kind=kind)


def render_latest_run_card(
    streamlit: Any,
    *,
    status: Any = "",
    output_path: Any = None,
    log_path: Any = None,
    started_at: Any = "",
    duration: Any = "",
    key_prefix: str,
    title: str = "Latest run",
    expanded: bool = False,
) -> None:
    """Render a compact latest-run summary with links to generic artifacts."""
    status_text = _normalize_status(status) if _as_text(status) else ""
    output = _path_from(output_path)
    log = _path_from(log_path)
    if not any([status_text, output, log, _as_text(started_at), _as_text(duration)]):
        return

    expander = streamlit.expander(title, expanded=expanded)
    with expander:
        if status_text:
            _call_container_method(expander, "caption", f"Status: {status_text}")
        if _as_text(started_at):
            _call_container_method(expander, "caption", f"Started: {_as_text(started_at)}")
        if _as_text(duration):
            _call_container_method(expander, "caption", f"Duration: {_as_text(duration)}")
        if output is not None:
            _call_container_method(expander, "caption", f"Output: {output}")
            _render_artifact_download(expander, path=output, key=f"{key_prefix}:latest_output")
        if log is not None:
            _call_container_method(expander, "caption", f"Log: {log}")
            _render_artifact_download(expander, path=log, key=f"{key_prefix}:latest_log", label="Download log")


def record_action_history(
    session_state: Any,
    *,
    page_label: str,
    env: Any | None = None,
    title: str,
    status: Any = "info",
    detail: Any = "",
    artifact: Any = "",
    limit: int = MAX_ACTION_HISTORY_ITEMS,
) -> dict[str, str]:
    """Record a small project-scoped UI activity item."""
    root = session_state.setdefault(ACTION_HISTORY_KEY, {})
    if not isinstance(root, dict):
        root = {}
        session_state[ACTION_HISTORY_KEY] = root
    scope = workflow_state_scope(page_label, env)
    items = root.setdefault(scope, [])
    if not isinstance(items, list):
        items = []
        root[scope] = items
    entry = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "title": _as_text(title) or "Action",
        "status": _normalize_status(status),
        "detail": _as_text(detail),
        "artifact": _as_text(artifact),
    }
    items.insert(0, entry)
    del items[max(1, int(limit or MAX_ACTION_HISTORY_ITEMS)) :]
    return entry


def render_action_history(
    streamlit: Any,
    *,
    session_state: Any,
    page_label: str,
    env: Any | None = None,
    title: str = "Recent activity",
    expanded: bool = False,
) -> None:
    """Render recent project-scoped UI activity."""
    root = session_state.get(ACTION_HISTORY_KEY, {})
    if not isinstance(root, dict):
        return
    items = root.get(workflow_state_scope(page_label, env), [])
    if not isinstance(items, list) or not items:
        return

    expander = streamlit.expander(title, expanded=expanded)
    with expander:
        for item in items[:MAX_ACTION_HISTORY_ITEMS]:
            if not isinstance(item, Mapping):
                continue
            title_text = _as_text(item.get("title")) or "Action"
            status = _as_text(item.get("status")) or "Info"
            at = _as_text(item.get("at"))
            detail = _as_text(item.get("detail"))
            artifact = _as_text(item.get("artifact"))
            prefix = f"{at} - " if at else ""
            _call_container_method(expander, "caption", f"{prefix}{title_text}: {status}")
            if detail:
                _call_container_method(expander, "caption", detail)
            if artifact:
                _call_container_method(expander, "caption", f"Artifact: {artifact}")
