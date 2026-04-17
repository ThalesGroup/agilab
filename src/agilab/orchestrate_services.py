import textwrap
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st

SERVICE_MODE_POOL = 1
SERVICE_MODE_CYTHON = 2
SERVICE_MODE_ENABLED = 4
SERVICE_MODE_RAPIDS = 8

DEFAULT_SERVICE_POLL_INTERVAL_SEC = 1.0
DEFAULT_SERVICE_STOP_TIMEOUT_SEC = 30.0
DEFAULT_SERVICE_HEARTBEAT_TIMEOUT_SEC = 10.0
DEFAULT_SERVICE_CLEANUP_DONE_TTL_HOURS = 168.0
DEFAULT_SERVICE_CLEANUP_FAILED_TTL_HOURS = 336.0
DEFAULT_SERVICE_CLEANUP_HEARTBEAT_TTL_HOURS = 24.0
DEFAULT_SERVICE_CLEANUP_DONE_MAX_FILES = 2000
DEFAULT_SERVICE_CLEANUP_FAILED_MAX_FILES = 2000
DEFAULT_SERVICE_CLEANUP_HEARTBEAT_MAX_FILES = 1000


SERVICE_SESSION_DEFAULTS: dict[str, Any] = {
    "service_log_cache": "",
    "service_status_cache": "idle",
    "service_snapshot_path_cache": "",
    "service_poll_interval": DEFAULT_SERVICE_POLL_INTERVAL_SEC,
    "service_stop_timeout": DEFAULT_SERVICE_STOP_TIMEOUT_SEC,
    "service_shutdown_on_stop": True,
    "service_heartbeat_timeout": DEFAULT_SERVICE_HEARTBEAT_TIMEOUT_SEC,
    "service_cleanup_done_ttl_hours": DEFAULT_SERVICE_CLEANUP_DONE_TTL_HOURS,
    "service_cleanup_failed_ttl_hours": DEFAULT_SERVICE_CLEANUP_FAILED_TTL_HOURS,
    "service_cleanup_heartbeat_ttl_hours": DEFAULT_SERVICE_CLEANUP_HEARTBEAT_TTL_HOURS,
    "service_cleanup_done_max_files": DEFAULT_SERVICE_CLEANUP_DONE_MAX_FILES,
    "service_cleanup_failed_max_files": DEFAULT_SERVICE_CLEANUP_FAILED_MAX_FILES,
    "service_cleanup_heartbeat_max_files": DEFAULT_SERVICE_CLEANUP_HEARTBEAT_MAX_FILES,
    "service_health_cache": [],
}


@dataclass(frozen=True)
class OrchestrateServiceDeps:
    reset_traceback_skip: Callable[[], None]
    append_log_lines: Callable[[list[str], str], None]
    extract_result_dict_from_output: Callable[[str], Optional[dict]]
    evaluate_service_health_gate: Callable[..., tuple[int, str, dict[str, Any]]]
    coerce_bool_setting: Callable[[Any, bool], bool]
    coerce_int_setting: Callable[[Any, int], int]
    coerce_float_setting: Callable[[Any, float], float]
    write_app_settings_toml: Callable[[Path, dict], dict]
    clear_load_toml_cache: Callable[[], None]
    log_display_max_lines: int
    install_log_height: int


@dataclass(frozen=True)
class ServiceHealthGateKeys:
    allow_idle: str
    max_unhealthy: str
    max_restart_rate: str


def ensure_service_session_defaults(session_state: Any) -> None:
    for key, value in SERVICE_SESSION_DEFAULTS.items():
        session_state.setdefault(key, value)


def service_health_gate_keys(app: str) -> ServiceHealthGateKeys:
    return ServiceHealthGateKeys(
        allow_idle=f"service_health_allow_idle__{app}",
        max_unhealthy=f"service_health_max_unhealthy__{app}",
        max_restart_rate=f"service_health_max_restart_rate__{app}",
    )


def ensure_service_health_gate_defaults(
    session_state: Any,
    *,
    app: str,
    defaults: dict[str, Any],
) -> ServiceHealthGateKeys:
    keys = service_health_gate_keys(app)
    session_state.setdefault(keys.allow_idle, defaults["allow_idle"])
    session_state.setdefault(keys.max_unhealthy, defaults["max_unhealthy"])
    session_state.setdefault(keys.max_restart_rate, defaults["max_restart_rate"])
    return keys


def compute_service_mode(cluster_params: dict[str, Any], service_enabled: bool) -> int:
    return (
        int(cluster_params.get("pool", False)) * SERVICE_MODE_POOL
        + int(cluster_params.get("cython", False)) * SERVICE_MODE_CYTHON
        + int(service_enabled) * SERVICE_MODE_ENABLED
        + int(cluster_params.get("rapids", False)) * SERVICE_MODE_RAPIDS
    )


def resolve_service_health_defaults(
    cluster_params: dict[str, Any],
    deps: OrchestrateServiceDeps,
) -> dict[str, Any]:
    service_health_defaults = {
        "allow_idle": False,
        "max_unhealthy": 0,
        "max_restart_rate": 0.25,
    }
    service_health_settings = cluster_params.get("service_health", {})
    if isinstance(service_health_settings, dict):
        service_health_defaults["allow_idle"] = deps.coerce_bool_setting(
            service_health_settings.get("allow_idle"),
            service_health_defaults["allow_idle"],
        )
        service_health_defaults["max_unhealthy"] = deps.coerce_int_setting(
            service_health_settings.get("max_unhealthy"),
            service_health_defaults["max_unhealthy"],
            minimum=0,
        )
        service_health_defaults["max_restart_rate"] = deps.coerce_float_setting(
            service_health_settings.get("max_restart_rate"),
            service_health_defaults["max_restart_rate"],
            minimum=0.0,
            maximum=1.0,
        )
    return service_health_defaults


def build_service_snippet(
    *,
    env: Any,
    verbose: int,
    service_action: str,
    service_mode: int,
    scheduler: str,
    workers: str,
    service_poll_interval: float,
    service_shutdown_on_stop: bool,
    service_stop_timeout: float,
    service_heartbeat_timeout: float,
    service_cleanup_done_ttl_hours: float,
    service_cleanup_failed_ttl_hours: float,
    service_cleanup_heartbeat_ttl_hours: float,
    service_cleanup_done_max_files: int,
    service_cleanup_failed_max_files: int,
    service_cleanup_heartbeat_max_files: int,
    args_serialized: str,
) -> str:
    return textwrap.dedent(f"""
import asyncio
from pathlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_PATH = "{env.apps_path}"
APP = "{env.app}"

async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose={verbose})
    res = await AGI.serve(
        app_env,
        action="{service_action}",
        mode={service_mode},
        scheduler={scheduler},
        workers={workers},
        poll_interval={float(service_poll_interval)},
        shutdown_on_stop={bool(service_shutdown_on_stop)},
        stop_timeout={float(service_stop_timeout)},
        heartbeat_timeout={float(service_heartbeat_timeout)},
        cleanup_done_ttl_sec={float(service_cleanup_done_ttl_hours) * 3600.0},
        cleanup_failed_ttl_sec={float(service_cleanup_failed_ttl_hours) * 3600.0},
        cleanup_heartbeat_ttl_sec={float(service_cleanup_heartbeat_ttl_hours) * 3600.0},
        cleanup_done_max_files={int(service_cleanup_done_max_files)},
        cleanup_failed_max_files={int(service_cleanup_failed_max_files)},
        cleanup_heartbeat_max_files={int(service_cleanup_heartbeat_max_files)},
        {args_serialized}
    )
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())""")


def build_service_operator_summary(
    *,
    status: str,
    worker_health: Any,
    allow_idle: bool,
    max_unhealthy: int,
    max_restart_rate: float,
    heartbeat_timeout_sec: float,
) -> dict[str, Any]:
    tracked_workers = 0
    unhealthy_workers = 0
    late_heartbeats = 0
    missing_heartbeats = 0
    max_heartbeat_age_sec: float | None = None
    reasons: list[str] = []

    health_rows = worker_health if isinstance(worker_health, list) else []
    for row in health_rows:
        if not isinstance(row, dict):
            continue
        tracked_workers += 1

        healthy_value = row.get("healthy")
        if healthy_value is False:
            unhealthy_workers += 1

        heartbeat_state = str(row.get("heartbeat_state", "")).strip().lower()
        if heartbeat_state in {"late", "stale", "timeout", "expired"}:
            late_heartbeats += 1
        elif heartbeat_state in {"missing", "absent", "none"}:
            missing_heartbeats += 1

        try:
            heartbeat_age_sec = float(row.get("heartbeat_age_sec"))
        except (TypeError, ValueError):
            heartbeat_age_sec = None
        if heartbeat_age_sec is not None:
            if max_heartbeat_age_sec is None or heartbeat_age_sec > max_heartbeat_age_sec:
                max_heartbeat_age_sec = heartbeat_age_sec

        reason = str(row.get("reason", "")).strip()
        if reason:
            reasons.append(reason)

    summary = {
        "status": str(status),
        "tracked_workers": tracked_workers,
        "unhealthy_workers": unhealthy_workers,
        "late_heartbeats": late_heartbeats,
        "missing_heartbeats": missing_heartbeats,
        "max_heartbeat_age_sec": max_heartbeat_age_sec,
        "reason_examples": list(dict.fromkeys(reasons))[:3],
        "gate_allow_idle": bool(allow_idle),
        "gate_max_unhealthy": int(max_unhealthy),
        "gate_max_restart_rate": float(max_restart_rate),
        "heartbeat_timeout_sec": float(heartbeat_timeout_sec),
    }
    lines = [
        f"Status: `{summary['status']}`",
        f"Tracked workers: `{summary['tracked_workers']}`",
        f"Unhealthy workers: `{summary['unhealthy_workers']}`",
        f"Late heartbeats: `{summary['late_heartbeats']}`",
        f"Missing heartbeats: `{summary['missing_heartbeats']}`",
        f"Heartbeat timeout: `{summary['heartbeat_timeout_sec']:.1f}s`",
        "Health gate: "
        f"`allow_idle={summary['gate_allow_idle']}, "
        f"max_unhealthy={summary['gate_max_unhealthy']}, "
        f"max_restart_rate={summary['gate_max_restart_rate']:.2f}`",
    ]
    if summary["max_heartbeat_age_sec"] is not None:
        lines.insert(
            5,
            f"Max heartbeat age: `{summary['max_heartbeat_age_sec']:.1f}s`",
        )
    if summary["reason_examples"]:
        lines.append(f"Observed reasons: `{', '.join(summary['reason_examples'])}`")
    summary["lines"] = lines
    return summary


def service_operator_snapshot_path(target: str, *, home_dir: Path | None = None) -> Path:
    base_dir = (home_dir or Path.home()) / "log" / "execute" / str(target)
    return base_dir / "service_operator_snapshot.json"


def build_service_operator_snapshot(
    *,
    app: str,
    target: str,
    status: str,
    worker_health: Any,
    allow_idle: bool,
    max_unhealthy: int,
    max_restart_rate: float,
    heartbeat_timeout_sec: float,
) -> dict[str, Any]:
    summary = build_service_operator_summary(
        status=status,
        worker_health=worker_health,
        allow_idle=allow_idle,
        max_unhealthy=max_unhealthy,
        max_restart_rate=max_restart_rate,
        heartbeat_timeout_sec=heartbeat_timeout_sec,
    )
    return {
        "schema": "agilab.service.operator_snapshot.v1",
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "app": str(app),
        "target": str(target),
        "status": str(summary["status"]),
        "health_gate": {
            "allow_idle": bool(summary["gate_allow_idle"]),
            "max_unhealthy": int(summary["gate_max_unhealthy"]),
            "max_restart_rate": float(summary["gate_max_restart_rate"]),
            "heartbeat_timeout_sec": float(summary["heartbeat_timeout_sec"]),
        },
        "summary": {
            "tracked_workers": int(summary["tracked_workers"]),
            "unhealthy_workers": int(summary["unhealthy_workers"]),
            "late_heartbeats": int(summary["late_heartbeats"]),
            "missing_heartbeats": int(summary["missing_heartbeats"]),
            "max_heartbeat_age_sec": summary["max_heartbeat_age_sec"],
            "reason_examples": list(summary["reason_examples"]),
        },
        "worker_health": worker_health if isinstance(worker_health, list) else [],
    }


def write_service_operator_snapshot(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


async def render_service_panel(
    *,
    env: Any,
    project_path: Path,
    cluster_params: dict[str, Any],
    verbose: int,
    scheduler: str,
    workers: str,
    deps: OrchestrateServiceDeps,
) -> None:
    ensure_service_session_defaults(st.session_state)

    with st.expander("Service mode (persistent workers)", expanded=False):
        service_enabled = bool(cluster_params.get("cluster_enabled", False))
        if not service_enabled:
            st.info("Enable Cluster in deployment settings before starting service mode.")

        service_mode = compute_service_mode(cluster_params, service_enabled)

        service_poll_interval = st.number_input(
            "Service poll interval (seconds)",
            min_value=0.0,
            value=float(st.session_state.get("service_poll_interval", DEFAULT_SERVICE_POLL_INTERVAL_SEC)),
            step=0.1,
            key="service_poll_interval",
            disabled=not service_enabled,
            help="Used when worker loop does not handle stop_event directly.",
        )
        service_stop_timeout = st.number_input(
            "Service stop timeout (seconds)",
            min_value=0.0,
            value=float(st.session_state.get("service_stop_timeout", DEFAULT_SERVICE_STOP_TIMEOUT_SEC)),
            step=1.0,
            key="service_stop_timeout",
            disabled=not service_enabled,
            help="Maximum wait time for worker service loops to stop.",
        )
        service_shutdown_on_stop = st.toggle(
            "Shutdown cluster on STOP",
            value=bool(st.session_state.get("service_shutdown_on_stop", True)),
            key="service_shutdown_on_stop",
            disabled=not service_enabled,
        )
        service_heartbeat_timeout = st.number_input(
            "Heartbeat timeout (seconds)",
            min_value=0.1,
            value=float(st.session_state.get("service_heartbeat_timeout", DEFAULT_SERVICE_HEARTBEAT_TIMEOUT_SEC)),
            step=0.5,
            key="service_heartbeat_timeout",
            disabled=not service_enabled,
            help="Worker health timeout before auto-restart is triggered.",
        )
        with st.expander("Retention policy", expanded=False):
            service_cleanup_done_ttl_hours = st.number_input(
                "Done artifacts TTL (hours)",
                min_value=0.0,
                value=float(st.session_state.get("service_cleanup_done_ttl_hours", DEFAULT_SERVICE_CLEANUP_DONE_TTL_HOURS)),
                step=1.0,
                key="service_cleanup_done_ttl_hours",
                disabled=not service_enabled,
            )
            service_cleanup_failed_ttl_hours = st.number_input(
                "Failed artifacts TTL (hours)",
                min_value=0.0,
                value=float(st.session_state.get("service_cleanup_failed_ttl_hours", DEFAULT_SERVICE_CLEANUP_FAILED_TTL_HOURS)),
                step=1.0,
                key="service_cleanup_failed_ttl_hours",
                disabled=not service_enabled,
            )
            service_cleanup_heartbeat_ttl_hours = st.number_input(
                "Heartbeat artifacts TTL (hours)",
                min_value=0.0,
                value=float(st.session_state.get("service_cleanup_heartbeat_ttl_hours", DEFAULT_SERVICE_CLEANUP_HEARTBEAT_TTL_HOURS)),
                step=1.0,
                key="service_cleanup_heartbeat_ttl_hours",
                disabled=not service_enabled,
            )
            service_cleanup_done_max_files = st.number_input(
                "Done artifacts max files",
                min_value=0,
                value=int(st.session_state.get("service_cleanup_done_max_files", DEFAULT_SERVICE_CLEANUP_DONE_MAX_FILES)),
                step=100,
                key="service_cleanup_done_max_files",
                disabled=not service_enabled,
            )
            service_cleanup_failed_max_files = st.number_input(
                "Failed artifacts max files",
                min_value=0,
                value=int(st.session_state.get("service_cleanup_failed_max_files", DEFAULT_SERVICE_CLEANUP_FAILED_MAX_FILES)),
                step=100,
                key="service_cleanup_failed_max_files",
                disabled=not service_enabled,
            )
            service_cleanup_heartbeat_max_files = st.number_input(
                "Heartbeat artifacts max files",
                min_value=0,
                value=int(st.session_state.get("service_cleanup_heartbeat_max_files", DEFAULT_SERVICE_CLEANUP_HEARTBEAT_MAX_FILES)),
                step=100,
                key="service_cleanup_heartbeat_max_files",
                disabled=not service_enabled,
            )

        service_health_defaults = resolve_service_health_defaults(cluster_params, deps)

        gate_keys = ensure_service_health_gate_defaults(
            st.session_state,
            app=env.app,
            defaults=service_health_defaults,
        )

        with st.expander("Health gate (SLA)", expanded=False):
            st.caption("Used by the one-click HEALTH gate action and persisted in app_settings.toml.")
            service_health_allow_idle = st.toggle(
                "Allow idle status",
                key=gate_keys.allow_idle,
                disabled=not service_enabled,
            )
            service_health_max_unhealthy = st.number_input(
                "Max unhealthy workers",
                min_value=0,
                value=int(st.session_state.get(gate_keys.max_unhealthy, service_health_defaults["max_unhealthy"])),
                step=1,
                key=gate_keys.max_unhealthy,
                disabled=not service_enabled,
            )
            service_health_max_restart_rate = st.number_input(
                "Max restart rate (0.0-1.0)",
                min_value=0.0,
                max_value=1.0,
                value=float(st.session_state.get(gate_keys.max_restart_rate, service_health_defaults["max_restart_rate"])),
                step=0.05,
                key=gate_keys.max_restart_rate,
                disabled=not service_enabled,
            )

        updated_service_health_settings = {
            "allow_idle": bool(service_health_allow_idle),
            "max_unhealthy": int(service_health_max_unhealthy),
            "max_restart_rate": float(service_health_max_restart_rate),
        }
        if cluster_params.get("service_health") != updated_service_health_settings:
            cluster_params["service_health"] = updated_service_health_settings
            st.session_state.app_settings["cluster"] = cluster_params
            st.session_state.app_settings = deps.write_app_settings_toml(
                env.app_settings_file,
                st.session_state.app_settings,
            )
            try:
                deps.clear_load_toml_cache()
            except (AttributeError, RuntimeError):
                pass

        st.caption(f"Service status: `{st.session_state.get('service_status_cache', 'idle')}`")

        preview_action = st.selectbox(
            "Service snippet action",
            options=["start", "status", "health", "stop"],
            index=0,
            key="service_snippet_action",
        )
        st.code(
            build_service_snippet(
                env=env,
                verbose=verbose,
                service_action=preview_action,
                service_mode=service_mode,
                scheduler=scheduler,
                workers=workers,
                service_poll_interval=float(service_poll_interval),
                service_shutdown_on_stop=bool(service_shutdown_on_stop),
                service_stop_timeout=float(service_stop_timeout),
                service_heartbeat_timeout=float(service_heartbeat_timeout),
                service_cleanup_done_ttl_hours=float(service_cleanup_done_ttl_hours),
                service_cleanup_failed_ttl_hours=float(service_cleanup_failed_ttl_hours),
                service_cleanup_heartbeat_ttl_hours=float(service_cleanup_heartbeat_ttl_hours),
                service_cleanup_done_max_files=int(service_cleanup_done_max_files),
                service_cleanup_failed_max_files=int(service_cleanup_failed_max_files),
                service_cleanup_heartbeat_max_files=int(service_cleanup_heartbeat_max_files),
                args_serialized=st.session_state.args_serialized,
            ),
            language="python",
        )

        start_col, status_col, health_col, export_col, stop_col = st.columns(5)
        start_service_clicked = start_col.button(
            "START service",
            key="service_start_btn",
            type="primary",
            width="stretch",
            disabled=not service_enabled,
        )
        status_service_clicked = status_col.button(
            "STATUS service",
            key="service_status_btn",
            type="secondary",
            width="stretch",
            disabled=not service_enabled,
        )
        health_gate_clicked = health_col.button(
            "HEALTH gate",
            key="service_health_gate_btn",
            type="secondary",
            width="stretch",
            disabled=not service_enabled,
        )
        export_snapshot_clicked = export_col.button(
            "EXPORT snapshot",
            key="service_export_btn",
            type="secondary",
            width="stretch",
            disabled=not service_enabled,
        )
        stop_service_clicked = stop_col.button(
            "STOP service",
            key="service_stop_btn",
            type="secondary",
            width="stretch",
            disabled=not service_enabled,
        )

        service_log_placeholder = st.empty()
        service_health_placeholder = st.empty()
        service_summary_placeholder = st.empty()
        service_snapshot_placeholder = st.empty()

        def _render_service_health_table() -> None:
            health_rows = st.session_state.get("service_health_cache") or []
            if not isinstance(health_rows, list) or not health_rows:
                service_health_placeholder.empty()
                return
            try:
                health_df = pd.DataFrame(health_rows)
            except (TypeError, ValueError):
                service_health_placeholder.empty()
                return
            ordered_cols = [
                "worker",
                "healthy",
                "reason",
                "future_state",
                "heartbeat_state",
                "heartbeat_age_sec",
            ]
            display_cols = [col for col in ordered_cols if col in health_df.columns]
            if display_cols:
                health_df = health_df[display_cols]
            service_health_placeholder.dataframe(health_df, width="stretch")

        def _render_service_operator_summary() -> None:
            summary = build_service_operator_summary(
                status=str(st.session_state.get("service_status_cache", "idle")),
                worker_health=st.session_state.get("service_health_cache") or [],
                allow_idle=bool(service_health_allow_idle),
                max_unhealthy=int(service_health_max_unhealthy),
                max_restart_rate=float(service_health_max_restart_rate),
                heartbeat_timeout_sec=float(service_heartbeat_timeout),
            )
            service_summary_placeholder.info(
                "\n".join(f"- {line}" for line in summary["lines"])
            )

        def _render_service_snapshot_status() -> None:
            snapshot_path = str(st.session_state.get("service_snapshot_path_cache", "") or "").strip()
            if snapshot_path:
                service_snapshot_placeholder.caption(
                    f"Operator snapshot: `{snapshot_path}`"
                )
            else:
                service_snapshot_placeholder.empty()

        _render_service_health_table()
        _render_service_operator_summary()
        _render_service_snapshot_status()
        cached_service_log = st.session_state.get("service_log_cache", "").strip()
        if cached_service_log:
            service_log_placeholder.code(
                cached_service_log,
                language="python",
                height=deps.install_log_height,
            )

        async def _execute_service_action(action_name: str) -> Optional[dict]:
            deps.reset_traceback_skip()
            local_log: list[str] = []
            context_lines = [
                f"=== Service action: {action_name.upper()} ===",
                f"timestamp: {datetime.now().isoformat(timespec='seconds')}",
                f"app: {env.app}",
                f"mode: {service_mode}",
                f"scheduler: {cluster_params.get('scheduler') if service_enabled else 'None'}",
                f"workers: {cluster_params.get('workers') if service_enabled else 'None'}",
                f"poll_interval: {service_poll_interval}",
                f"stop_timeout: {service_stop_timeout}",
                f"shutdown_on_stop: {service_shutdown_on_stop}",
                f"heartbeat_timeout: {service_heartbeat_timeout}",
                f"cleanup_done_ttl_h: {service_cleanup_done_ttl_hours}",
                f"cleanup_failed_ttl_h: {service_cleanup_failed_ttl_hours}",
                f"cleanup_heartbeat_ttl_h: {service_cleanup_heartbeat_ttl_hours}",
                f"cleanup_done_max: {service_cleanup_done_max_files}",
                f"cleanup_failed_max: {service_cleanup_failed_max_files}",
                f"cleanup_heartbeat_max: {service_cleanup_heartbeat_max_files}",
                f"health_allow_idle: {bool(service_health_allow_idle)}",
                f"health_max_unhealthy: {int(service_health_max_unhealthy)}",
                f"health_max_restart_rate: {float(service_health_max_restart_rate)}",
                "=== Streaming service logs ===",
            ]
            for line in context_lines:
                deps.append_log_lines(local_log, line)

            def _render_logs() -> None:
                service_log_placeholder.code(
                    "\n".join(local_log[-deps.log_display_max_lines:]),
                    language="python",
                    height=deps.install_log_height,
                )

            _render_logs()
            cmd_service = build_service_snippet(
                env=env,
                verbose=verbose,
                service_action=action_name,
                service_mode=service_mode,
                scheduler=scheduler,
                workers=workers,
                service_poll_interval=float(service_poll_interval),
                service_shutdown_on_stop=bool(service_shutdown_on_stop),
                service_stop_timeout=float(service_stop_timeout),
                service_heartbeat_timeout=float(service_heartbeat_timeout),
                service_cleanup_done_ttl_hours=float(service_cleanup_done_ttl_hours),
                service_cleanup_failed_ttl_hours=float(service_cleanup_failed_ttl_hours),
                service_cleanup_heartbeat_ttl_hours=float(service_cleanup_heartbeat_ttl_hours),
                service_cleanup_done_max_files=int(service_cleanup_done_max_files),
                service_cleanup_failed_max_files=int(service_cleanup_failed_max_files),
                service_cleanup_heartbeat_max_files=int(service_cleanup_heartbeat_max_files),
                args_serialized=st.session_state.args_serialized,
            )
            service_stdout = ""
            service_stderr = ""
            service_error: Exception | None = None

            with st.spinner(f"Service action '{action_name}' in progress..."):
                def _service_log_callback(message: str) -> None:
                    deps.append_log_lines(local_log, message)
                    _render_logs()

                try:
                    service_stdout, service_stderr = await env.run_agi(
                        cmd_service.replace("asyncio.run(main())", env.snippet_tail),
                        log_callback=_service_log_callback,
                        venv=project_path,
                    )
                except (RuntimeError, OSError, TimeoutError, ValueError, AttributeError, TypeError) as exc:
                    service_error = exc
                    service_stderr = str(exc)
                    deps.append_log_lines(local_log, f"ERROR: {service_stderr}")

            if service_stdout:
                deps.append_log_lines(local_log, service_stdout)
            if service_stderr:
                deps.append_log_lines(local_log, service_stderr)

            result_payload = deps.extract_result_dict_from_output(service_stdout)
            if isinstance(result_payload, dict) and isinstance(result_payload.get("status"), str):
                st.session_state["service_status_cache"] = result_payload["status"]
                if st.session_state["service_status_cache"] in {"stopped", "idle"}:
                    st.session_state["service_health_cache"] = []
                    _render_service_health_table()
                    _render_service_operator_summary()
                restarted_workers = result_payload.get("restarted_workers") or []
                restart_reasons = result_payload.get("restart_reasons") or {}
                cleanup_stats = result_payload.get("cleanup") or {}
                worker_health = result_payload.get("worker_health") or []
                heartbeat_timeout_sec = result_payload.get("heartbeat_timeout_sec")
                health_json_path = result_payload.get("health_path") or result_payload.get("path")

                if isinstance(worker_health, list):
                    st.session_state["service_health_cache"] = worker_health
                    _render_service_health_table()
                    _render_service_operator_summary()
                    if worker_health:
                        deps.append_log_lines(local_log, "=== Service health ===")
                        for row in worker_health:
                            if not isinstance(row, dict):
                                continue
                            worker_name = row.get("worker", "?")
                            healthy = bool(row.get("healthy", False))
                            reason = row.get("reason", "")
                            age = row.get("heartbeat_age_sec", None)
                            hb_state = row.get("heartbeat_state", "missing")
                            status_word = "healthy" if healthy else "unhealthy"
                            deps.append_log_lines(
                                local_log,
                                f"{worker_name}: {status_word} "
                                f"(hb_state={hb_state}, hb_age={age}, reason={reason})",
                            )
                else:
                    st.session_state["service_health_cache"] = []
                    _render_service_health_table()
                    _render_service_operator_summary()

                if restarted_workers:
                    deps.append_log_lines(local_log, "=== Service auto-restart ===")
                    for worker in restarted_workers:
                        reason = restart_reasons.get(worker, "unhealthy")
                        deps.append_log_lines(local_log, f"restart {worker}: {reason}")

                if heartbeat_timeout_sec is not None:
                    deps.append_log_lines(local_log, f"heartbeat_timeout_sec={heartbeat_timeout_sec}")
                if health_json_path:
                    deps.append_log_lines(local_log, f"service_health_json={health_json_path}")

                if isinstance(cleanup_stats, dict) and any(
                    int(cleanup_stats.get(key, 0) or 0) > 0
                    for key in ("done", "failed", "heartbeats")
                ):
                    deps.append_log_lines(local_log, "=== Service cleanup ===")
                    deps.append_log_lines(
                        local_log,
                        f"done={int(cleanup_stats.get('done', 0) or 0)} "
                        f"failed={int(cleanup_stats.get('failed', 0) or 0)} "
                        f"heartbeats={int(cleanup_stats.get('heartbeats', 0) or 0)}",
                    )
            elif service_error or service_stderr.strip():
                st.session_state["service_status_cache"] = "error"
                st.session_state["service_health_cache"] = []
                _render_service_health_table()
                _render_service_operator_summary()

            st.session_state["service_log_cache"] = "\n".join(local_log[-deps.log_display_max_lines:])
            _render_logs()

            if service_error or service_stderr.strip():
                st.error(f"Service action '{action_name}' failed.")
            else:
                if isinstance(result_payload, dict):
                    restarted_workers = result_payload.get("restarted_workers") or []
                    if restarted_workers:
                        st.warning(
                            "Service auto-restarted worker loops: "
                            + ", ".join(str(worker) for worker in restarted_workers)
                        )
                st.success(
                    f"Service action '{action_name}' completed with status "
                    f"'{st.session_state.get('service_status_cache', 'unknown')}'."
                )
            if isinstance(result_payload, dict):
                return result_payload
            return None

        if start_service_clicked:
            await _execute_service_action("start")
        elif status_service_clicked:
            await _execute_service_action("status")
        elif health_gate_clicked:
            health_payload = await _execute_service_action("health")
            if isinstance(health_payload, dict):
                gate_code, gate_reason, gate_details = deps.evaluate_service_health_gate(
                    health_payload,
                    allow_idle=bool(service_health_allow_idle),
                    max_unhealthy=int(service_health_max_unhealthy),
                    max_restart_rate=float(service_health_max_restart_rate),
                )
                restart_rate = float(gate_details.get("restart_rate", 0.0) or 0.0)
                st.caption(
                    f"Health gate metrics: status={gate_details.get('status')}, "
                    f"unhealthy={gate_details.get('workers_unhealthy_count')}, "
                    f"restarted={gate_details.get('workers_restarted_count')}, "
                    f"running={gate_details.get('workers_running_count')}, "
                    f"restart_rate={restart_rate:.3f}"
                )
                if gate_code == 0:
                    st.success("HEALTH gate passed.")
                else:
                    st.error(f"HEALTH gate failed (code {gate_code}): {gate_reason}")
            else:
                st.error("HEALTH gate failed: unable to parse service health payload.")
        elif export_snapshot_clicked:
            snapshot_payload = build_service_operator_snapshot(
                app=env.app,
                target=env.target,
                status=str(st.session_state.get("service_status_cache", "idle")),
                worker_health=st.session_state.get("service_health_cache") or [],
                allow_idle=bool(service_health_allow_idle),
                max_unhealthy=int(service_health_max_unhealthy),
                max_restart_rate=float(service_health_max_restart_rate),
                heartbeat_timeout_sec=float(service_heartbeat_timeout),
            )
            snapshot_path = service_operator_snapshot_path(env.target)
            try:
                written_path = write_service_operator_snapshot(snapshot_path, snapshot_payload)
            except OSError as exc:
                st.error(f"Operator snapshot export failed: {exc}")
            else:
                st.session_state["service_snapshot_path_cache"] = str(written_path)
                _render_service_snapshot_status()
                st.success(f"Operator snapshot exported to '{written_path}'.")
        elif stop_service_clicked:
            await _execute_service_action("stop")
