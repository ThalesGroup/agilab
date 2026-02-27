#!/usr/bin/env python3
"""CLI helper to export and evaluate AGI service health."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import tomllib

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

DEFAULT_ALLOW_IDLE = False
DEFAULT_MAX_UNHEALTHY = 0
DEFAULT_MAX_RESTART_RATE = 0.25
KNOWN_SERVICE_STATUSES = ("running", "idle", "degraded", "error", "stopped", "unknown")


def _default_apps_path() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "agilab" / "apps" / "builtin"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read AGI service health via AGI.serve(action='health'), export JSON, "
            "and exit non-zero when health gates fail."
        )
    )
    parser.add_argument("--app", required=True, help="App name (for example: mycode_project).")
    parser.add_argument(
        "--apps-path",
        default=str(_default_apps_path()),
        help="Path containing app projects (default: src/agilab/apps/builtin).",
    )
    parser.add_argument(
        "--health-output-path",
        default="",
        help="Optional output path for health JSON (absolute or AGI_SHARE_DIR-relative).",
    )
    parser.add_argument(
        "--allow-idle",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Treat status=idle as healthy. If omitted, value comes from "
            "[cluster.service_health].allow_idle in app_settings.toml."
        ),
    )
    parser.add_argument(
        "--max-unhealthy",
        type=int,
        default=None,
        help=(
            "Maximum tolerated unhealthy workers. If omitted, value comes from "
            "[cluster.service_health].max_unhealthy in app_settings.toml."
        ),
    )
    parser.add_argument(
        "--max-restart-rate",
        type=float,
        default=None,
        help=(
            "Maximum tolerated restart rate in [0.0, 1.0]. If omitted, value comes from "
            "[cluster.service_health].max_restart_rate in app_settings.toml."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("json", "prometheus"),
        default="json",
        help="Output format for stdout payload.",
    )
    parser.add_argument("--verbose", type=int, default=0, help="AgiEnv verbosity.")
    return parser


def _coerce_bool(raw: Any, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(raw: Any, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(value, minimum)


def _coerce_float(raw: Any, default: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _load_service_health_settings(env: AgiEnv) -> dict[str, Any]:
    settings_path = Path(getattr(env, "app_settings_file", "") or "")
    if not settings_path.exists():
        return {}
    try:
        with settings_path.open("rb") as stream:
            settings = tomllib.load(stream)
    except Exception:
        return {}
    cluster = settings.get("cluster")
    if not isinstance(cluster, dict):
        return {}
    service_health = cluster.get("service_health")
    if not isinstance(service_health, dict):
        return {}
    return service_health


def _resolve_health_gate_settings(
    args: argparse.Namespace, service_health_settings: dict[str, Any]
) -> tuple[bool, int, float]:
    allow_idle = (
        bool(args.allow_idle)
        if args.allow_idle is not None
        else _coerce_bool(service_health_settings.get("allow_idle"), DEFAULT_ALLOW_IDLE)
    )
    max_unhealthy = (
        max(int(args.max_unhealthy), 0)
        if args.max_unhealthy is not None
        else _coerce_int(service_health_settings.get("max_unhealthy"), DEFAULT_MAX_UNHEALTHY, minimum=0)
    )
    max_restart_rate = (
        _coerce_float(args.max_restart_rate, DEFAULT_MAX_RESTART_RATE, minimum=0.0, maximum=1.0)
        if args.max_restart_rate is not None
        else _coerce_float(
            service_health_settings.get("max_restart_rate"),
            DEFAULT_MAX_RESTART_RATE,
            minimum=0.0,
            maximum=1.0,
        )
    )
    return allow_idle, max_unhealthy, max_restart_rate


def _coerce_payload_int(payload: dict, key: str) -> int:
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _evaluate_health(
    payload: dict,
    *,
    allow_idle: bool,
    max_unhealthy: int,
    max_restart_rate: float,
) -> tuple[int, str, dict[str, float | int | str]]:
    status = str(payload.get("status", "unknown") or "unknown").lower()
    unhealthy = _coerce_payload_int(payload, "workers_unhealthy_count")
    running = _coerce_payload_int(payload, "workers_running_count")
    restarted = _coerce_payload_int(payload, "workers_restarted_count")
    restart_rate = float(restarted) / float(running) if running > 0 else 0.0
    details: dict[str, float | int | str] = {
        "status": status,
        "workers_unhealthy_count": unhealthy,
        "workers_running_count": running,
        "workers_restarted_count": restarted,
        "restart_rate": restart_rate,
    }

    if unhealthy > max_unhealthy:
        return 2, f"unhealthy workers {unhealthy} exceeds limit {max_unhealthy}", details
    if status in {"error", "degraded"}:
        return 3, f"service status is {status}", details
    if status == "idle" and not allow_idle:
        return 4, "service status is idle (use --allow-idle to accept)", details
    if restart_rate > max_restart_rate:
        return (
            5,
            f"restart rate {restart_rate:.3f} exceeds limit {max_restart_rate:.3f}",
            details,
        )
    return 0, "ok", details


def _escape_prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _to_prometheus(
    payload: dict,
    *,
    details: dict[str, float | int | str],
    exit_code: int,
    allow_idle: bool,
    max_unhealthy: int,
    max_restart_rate: float,
) -> str:
    status = str(details.get("status", "unknown") or "unknown")
    labels = (
        f'app="{_escape_prometheus_label(str(payload.get("app", "")))}",'
        f'target="{_escape_prometheus_label(str(payload.get("target", "")))}"'
    )
    running_count = int(details.get("workers_running_count", 0) or 0)
    unhealthy_count = int(details.get("workers_unhealthy_count", 0) or 0)
    restarted_count = int(details.get("workers_restarted_count", 0) or 0)
    restart_rate = float(details.get("restart_rate", 0.0) or 0.0)
    lines = [
        "# HELP agilab_service_workers_running_count Number of running workers.",
        "# TYPE agilab_service_workers_running_count gauge",
        f"agilab_service_workers_running_count{{{labels}}} {running_count}",
        "# HELP agilab_service_workers_unhealthy_count Number of unhealthy workers.",
        "# TYPE agilab_service_workers_unhealthy_count gauge",
        f"agilab_service_workers_unhealthy_count{{{labels}}} {unhealthy_count}",
        "# HELP agilab_service_workers_restarted_count Number of restarted workers.",
        "# TYPE agilab_service_workers_restarted_count gauge",
        f"agilab_service_workers_restarted_count{{{labels}}} {restarted_count}",
        "# HELP agilab_service_restart_rate Restarted/running workers ratio.",
        "# TYPE agilab_service_restart_rate gauge",
        f"agilab_service_restart_rate{{{labels}}} {restart_rate:.6f}",
        "# HELP agilab_service_health_gate_pass 1 when the gate passes, else 0.",
        "# TYPE agilab_service_health_gate_pass gauge",
        f"agilab_service_health_gate_pass{{{labels}}} {1 if exit_code == 0 else 0}",
        "# HELP agilab_service_health_gate_code Exit code of health gate evaluation.",
        "# TYPE agilab_service_health_gate_code gauge",
        f"agilab_service_health_gate_code{{{labels}}} {int(exit_code)}",
        "# HELP agilab_service_sla_allow_idle Health gate allow-idle threshold.",
        "# TYPE agilab_service_sla_allow_idle gauge",
        f"agilab_service_sla_allow_idle{{{labels}}} {1 if allow_idle else 0}",
        "# HELP agilab_service_sla_max_unhealthy Health gate max-unhealthy threshold.",
        "# TYPE agilab_service_sla_max_unhealthy gauge",
        f"agilab_service_sla_max_unhealthy{{{labels}}} {int(max_unhealthy)}",
        "# HELP agilab_service_sla_max_restart_rate Health gate max-restart-rate threshold.",
        "# TYPE agilab_service_sla_max_restart_rate gauge",
        f"agilab_service_sla_max_restart_rate{{{labels}}} {float(max_restart_rate):.6f}",
    ]

    lines.extend(
        [
            "# HELP agilab_service_status Current service status one-hot metrics.",
            "# TYPE agilab_service_status gauge",
        ]
    )
    for known_status in KNOWN_SERVICE_STATUSES:
        lines.append(
            f'agilab_service_status{{{labels},state="{known_status}"}} '
            f"{1 if status == known_status else 0}"
        )
    if status not in KNOWN_SERVICE_STATUSES:
        lines.append(
            f'agilab_service_status{{{labels},state="{_escape_prometheus_label(status)}"}} 1'
        )
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> int:
    env = AgiEnv(apps_path=Path(args.apps_path), app=str(args.app), verbose=int(args.verbose))
    settings = _load_service_health_settings(env)
    allow_idle, max_unhealthy, max_restart_rate = _resolve_health_gate_settings(args, settings)
    payload = await AGI.serve(
        env,
        action="health",
        health_output_path=(args.health_output_path or None),
    )
    code, reason, details = _evaluate_health(
        payload,
        allow_idle=allow_idle,
        max_unhealthy=max_unhealthy,
        max_restart_rate=max_restart_rate,
    )
    if args.format == "prometheus":
        print(
            _to_prometheus(
                payload,
                details=details,
                exit_code=code,
                allow_idle=allow_idle,
                max_unhealthy=max_unhealthy,
                max_restart_rate=max_restart_rate,
            )
        )
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    if code:
        print(f"[service_health_check] FAIL: {reason}", file=sys.stderr)
    else:
        print(f"[service_health_check] OK: {reason}", file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"[service_health_check] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
