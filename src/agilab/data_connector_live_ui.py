# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""Streamlit connector-state rendering contract for AGILAB evidence reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agilab.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    load_connector_catalog,
)
from agilab.data_connector_resolution import (
    DEFAULT_SETTINGS_RELATIVE_PATH,
    load_app_settings,
)
from agilab.data_connector_ui_preview import (
    SCHEMA as UI_PREVIEW_SCHEMA,
    build_data_connector_ui_preview,
)


SCHEMA = "agilab.data_connector_live_ui.v1"
DEFAULT_RUN_ID = "data-connector-live-ui-proof"
CREATED_AT = "2026-04-25T00:00:26Z"
UPDATED_AT = "2026-04-25T00:00:26Z"
DEFAULT_RELEASE_DECISION_PAGE = Path(
    "src/agilab/apps-pages/view_release_decision/src/"
    "view_release_decision/view_release_decision.py"
)


class _FallbackContext:
    def __init__(self, fallback: Any) -> None:
        self._fallback = fallback

    def __enter__(self) -> Any:
        return self._fallback

    def __exit__(self, *_args: Any) -> bool:
        return False


class StreamlitCallRecorder:
    """Minimal Streamlit-like recorder used by reports and tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> "StreamlitCallRecorder":
        self.calls.append({"method": "__enter__"})
        return self

    def __exit__(self, *_args: Any) -> bool:
        self.calls.append({"method": "__exit__"})
        return False

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        payload: dict[str, Any] = {
            "method": method,
            "args": [str(arg) for arg in args],
            "kwargs": {key: str(value) for key, value in kwargs.items()},
        }
        if args and isinstance(args[0], list):
            payload["row_count"] = len(args[0])
        self.calls.append(payload)

    def expander(self, *args: Any, **kwargs: Any) -> "StreamlitCallRecorder":
        self._record("expander", *args, **kwargs)
        return self

    def columns(self, spec: int | list[Any] | tuple[Any, ...]) -> list["StreamlitCallRecorder"]:
        count = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        self._record("columns", spec)
        return [self for _ in range(count)]

    def markdown(self, *args: Any, **kwargs: Any) -> None:
        self._record("markdown", *args, **kwargs)

    def caption(self, *args: Any, **kwargs: Any) -> None:
        self._record("caption", *args, **kwargs)

    def metric(self, *args: Any, **kwargs: Any) -> None:
        self._record("metric", *args, **kwargs)

    def dataframe(self, *args: Any, **kwargs: Any) -> None:
        self._record("dataframe", *args, **kwargs)

    def info(self, *args: Any, **kwargs: Any) -> None:
        self._record("info", *args, **kwargs)

    def warning(self, *args: Any, **kwargs: Any) -> None:
        self._record("warning", *args, **kwargs)


def _call(target: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    handler = getattr(target, method, None)
    if callable(handler):
        return handler(*args, **kwargs)
    return None


def _context(target: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    maybe_context = _call(target, method, *args, **kwargs)
    if hasattr(maybe_context, "__enter__") and hasattr(maybe_context, "__exit__"):
        return maybe_context
    return _FallbackContext(target)


def _columns(target: Any, count: int) -> list[Any]:
    columns = _call(target, "columns", count)
    if isinstance(columns, list) and len(columns) == count:
        return columns
    if isinstance(columns, tuple) and len(columns) == count:
        return list(columns)
    return [target for _ in range(count)]


def _dict_rows(state: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    return [row for row in state.get(key, []) if isinstance(row, dict)]


def _status_values(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row.get("health_status", row.get("status", ""))) for row in rows})


def build_connector_live_ui_payload(
    preview_state: Mapping[str, Any],
    *,
    component_id: str = "release_decision_connector_preview",
) -> dict[str, Any]:
    cards = _dict_rows(preview_state, "connector_cards")
    page_bindings = _dict_rows(preview_state, "page_bindings")
    legacy_fallbacks = _dict_rows(preview_state, "legacy_fallbacks")
    health_probes = _dict_rows(preview_state, "health_probes")
    preview_summary = preview_state.get("summary", {})
    preview_provenance = preview_state.get("provenance", {})
    source_ready = (
        preview_state.get("schema") == UI_PREVIEW_SCHEMA
        and preview_state.get("run_status") == "ready_for_ui_preview"
    )
    health_opt_in_required = (
        preview_provenance.get("operator_opt_in_required_for_health") is True
        and all(probe.get("operator_context_required") is True for probe in health_probes)
    )
    summary = {
        "component_id": component_id,
        "source_schema": preview_state.get("schema", ""),
        "source_run_status": preview_state.get("run_status", ""),
        "source_execution_mode": preview_summary.get("execution_mode", ""),
        "connector_card_count": len(cards),
        "page_binding_count": len(page_bindings),
        "legacy_fallback_count": len(legacy_fallbacks),
        "health_probe_status_count": len(health_probes),
        "streamlit_metric_count": 4,
        "streamlit_dataframe_count": 4,
        "streamlit_component_count": 9,
        "network_probe_count": 0,
        "operator_opt_in_required_for_health": health_opt_in_required,
        "health_status_values": _status_values(cards),
        "page_ids": sorted({str(row.get("page", "")) for row in page_bindings}),
    }
    return {
        "schema": SCHEMA,
        "component_id": component_id,
        "run_status": "ready_for_live_ui" if source_ready else "invalid",
        "execution_mode": "streamlit_render_contract_only",
        "summary": summary,
        "connector_cards": cards,
        "page_bindings": page_bindings,
        "legacy_fallbacks": legacy_fallbacks,
        "health_probes": health_probes,
        "provenance": {
            "executes_network_probe": False,
            "renders_streamlit": True,
            "requires_operator_opt_in_for_health": health_opt_in_required,
            "source_static_preview_schema": preview_state.get("schema", ""),
        },
    }


def render_connector_live_ui(
    st_api: Any,
    preview_state: Mapping[str, Any],
    *,
    component_id: str = "release_decision_connector_preview",
) -> dict[str, Any]:
    payload = build_connector_live_ui_payload(
        preview_state,
        component_id=component_id,
    )
    summary = payload["summary"]
    with _context(st_api, "expander", "Connector state and provenance", expanded=False) as panel:
        _call(panel, "markdown", "**Connector state and provenance**")
        _call(
            panel,
            "caption",
            (
                "Connector references, fallback paths, and planned health probes "
                "are rendered from checked-in connector evidence. No network "
                "probe is executed in this view."
            ),
        )
        metrics = _columns(panel, 4)
        _call(metrics[0], "metric", "Connectors", summary["connector_card_count"])
        _call(metrics[1], "metric", "Page bindings", summary["page_binding_count"])
        _call(metrics[2], "metric", "Legacy fallbacks", summary["legacy_fallback_count"])
        _call(metrics[3], "metric", "Network probes", summary["network_probe_count"])
        _call(
            panel,
            "dataframe",
            payload["connector_cards"],
            width="stretch",
            hide_index=True,
        )
        _call(
            panel,
            "dataframe",
            payload["page_bindings"],
            width="stretch",
            hide_index=True,
        )
        _call(
            panel,
            "dataframe",
            payload["legacy_fallbacks"],
            width="stretch",
            hide_index=True,
        )
        _call(
            panel,
            "dataframe",
            payload["health_probes"],
            width="stretch",
            hide_index=True,
        )
        if summary["operator_opt_in_required_for_health"]:
            _call(
                panel,
                "info",
                "Health probes remain unknown_not_probed until an operator opts in.",
            )
        else:
            _call(panel, "warning", "Connector health opt-in boundary is missing.")
    return payload


def release_decision_live_ui_hook(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return {
            "path": str(path),
            "loaded": False,
            "error": str(exc),
            "imports_renderer": False,
            "builds_preview": False,
            "calls_renderer": False,
            "stores_session_state": False,
        }
    return {
        "path": str(path),
        "loaded": True,
        "imports_renderer": "render_connector_live_ui" in text,
        "builds_preview": "build_data_connector_ui_preview(" in text,
        "calls_renderer": "render_connector_live_ui(" in text,
        "stores_session_state": "release_decision_connector_live_ui" in text,
    }


def build_data_connector_live_ui(
    *,
    settings: Mapping[str, Any],
    catalog: Mapping[str, Any],
    settings_path: Path | str,
    catalog_path: Path | str,
    release_decision_page: Path | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    preview_state = build_data_connector_ui_preview(
        settings=settings,
        catalog=catalog,
        settings_path=settings_path,
        catalog_path=catalog_path,
    )
    recorder = StreamlitCallRecorder()
    payload = render_connector_live_ui(recorder, preview_state)
    hook_path = release_decision_page or DEFAULT_RELEASE_DECISION_PAGE
    hook = release_decision_live_ui_hook(Path(hook_path))
    issues = []
    if payload.get("run_status") != "ready_for_live_ui":
        issues.append(
            {
                "level": "error",
                "location": "connector_live_ui",
                "message": "connector live UI payload is not ready",
            }
        )
    for flag in (
        "loaded",
        "imports_renderer",
        "builds_preview",
        "calls_renderer",
        "stores_session_state",
    ):
        if hook.get(flag) is not True:
            issues.append(
                {
                    "level": "error",
                    "location": "release_decision_page",
                    "message": f"release decision hook missing {flag}",
                }
            )
    method_counts: dict[str, int] = {}
    for call in recorder.calls:
        method = str(call.get("method", ""))
        method_counts[method] = method_counts.get(method, 0) + 1
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "run_status": "ready_for_live_ui" if not issues else "invalid",
        "execution_mode": "streamlit_render_contract_only",
        "source": {
            "settings_path": str(settings_path),
            "catalog_path": str(catalog_path),
            "release_decision_page": str(hook_path),
            "preview_schema": preview_state.get("schema", ""),
        },
        "summary": {
            **payload.get("summary", {}),
            "streamlit_call_count": len(recorder.calls),
            "streamlit_call_methods": method_counts,
            "release_decision_hooked": not issues,
        },
        "render_payload": payload,
        "streamlit_calls": recorder.calls,
        "release_decision_hook": hook,
        "issues": issues,
        "provenance": {
            "executes_network_probe": False,
            "streamlit_import_required": False,
            "report_uses_fake_streamlit_recorder": True,
        },
    }


def write_data_connector_live_ui(path: Path, state: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_data_connector_live_ui(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def persist_data_connector_live_ui(
    *,
    repo_root: Path,
    output_path: Path,
    settings_path: Path | None = None,
    catalog_path: Path | None = None,
    release_decision_page: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    settings_path = settings_path or (repo_root / DEFAULT_SETTINGS_RELATIVE_PATH)
    catalog_path = catalog_path or (repo_root / DEFAULT_CONNECTORS_RELATIVE_PATH)
    release_decision_page = release_decision_page or (repo_root / DEFAULT_RELEASE_DECISION_PAGE)
    if not settings_path.is_absolute():
        settings_path = repo_root / settings_path
    if not catalog_path.is_absolute():
        catalog_path = repo_root / catalog_path
    if not release_decision_page.is_absolute():
        release_decision_page = repo_root / release_decision_page
    settings = load_app_settings(settings_path)
    catalog = load_connector_catalog(catalog_path)
    state = build_data_connector_live_ui(
        settings=settings,
        catalog=catalog,
        settings_path=settings_path,
        catalog_path=catalog_path,
        release_decision_page=release_decision_page,
    )
    path = write_data_connector_live_ui(output_path, state)
    reloaded = load_data_connector_live_ui(path)
    return {
        "ok": state == reloaded and state.get("run_status") == "ready_for_live_ui",
        "path": str(path),
        "settings_path": str(settings_path),
        "catalog_path": str(catalog_path),
        "release_decision_page": str(release_decision_page),
        "state": state,
        "reloaded_state": reloaded,
        "round_trip_ok": state == reloaded,
    }
