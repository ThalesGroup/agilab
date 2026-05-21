from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


HEALTH_PAYLOAD_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "builtin"
    / "mycode_project"
    / "service_templates"
    / "sample_health_running.json"
)
DEFAULT_OUTPUT_PATH = Path.home() / "log" / "execute" / "service_mode" / "service_operator_preview.json"
DEFAULT_APP = "mycode_project"
DEFAULT_TARGET = "mycode"


def _int_field(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def evaluate_health_gate(
    payload: dict[str, Any],
    *,
    allow_idle: bool = False,
    max_unhealthy: int = 0,
    max_restart_rate: float = 0.25,
) -> dict[str, Any]:
    status = str(payload.get("status", "unknown") or "unknown").lower()
    unhealthy = _int_field(payload, "workers_unhealthy_count")
    running = _int_field(payload, "workers_running_count")
    restarted = _int_field(payload, "workers_restarted_count")
    restart_rate = float(restarted) / float(running) if running > 0 else 0.0

    ok = True
    reason = "ok"
    if unhealthy > max_unhealthy:
        ok = False
        reason = f"unhealthy workers {unhealthy} exceeds limit {max_unhealthy}"
    elif status == "running" and running <= 0:
        ok = False
        reason = "service has no running workers"
    elif status in {"error", "degraded"}:
        ok = False
        reason = f"service status is {status}"
    elif status == "idle" and not allow_idle:
        ok = False
        reason = "service status is idle"
    elif status not in {"idle", "running"}:
        ok = False
        reason = f"service status is {status}"
    elif restart_rate > max_restart_rate:
        ok = False
        reason = f"restart rate {restart_rate:.3f} exceeds limit {max_restart_rate:.3f}"

    return {
        "ok": ok,
        "reason": reason,
        "thresholds": {
            "allow_idle": allow_idle,
            "max_unhealthy": max_unhealthy,
            "max_restart_rate": max_restart_rate,
        },
        "details": {
            "status": status,
            "workers_running_count": running,
            "workers_unhealthy_count": unhealthy,
            "workers_restarted_count": restarted,
            "restart_rate": restart_rate,
        },
    }


def service_action_sequence(app: str = DEFAULT_APP) -> list[dict[str, str]]:
    return [
        {
            "action": "start",
            "call": 'await AGI.serve(env, action="start", mode=AGI.DASK_MODE)',
            "operator_meaning": f"Start persistent worker loops for {app}.",
        },
        {
            "action": "status",
            "call": 'await AGI.serve(env, action="status")',
            "operator_meaning": "Read runtime state without exporting health JSON.",
        },
        {
            "action": "health",
            "call": 'await AGI.serve(env, action="health")',
            "operator_meaning": "Export health JSON and evaluate worker health gates.",
        },
        {
            "action": "stop",
            "call": 'await AGI.serve(env, action="stop", shutdown_on_stop=False)',
            "operator_meaning": "Request loop termination before changing topology.",
        },
    ]


def load_health_payload(path: Path = HEALTH_PAYLOAD_PATH) -> dict[str, Any]:
    with path.expanduser().open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise SystemExit(f"Health payload must be a JSON object: {path}")
    return payload


def build_preview(
    *,
    health_payload_path: Path = HEALTH_PAYLOAD_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    allow_idle: bool = False,
    max_unhealthy: int = 0,
    max_restart_rate: float = 0.25,
) -> dict[str, Any]:
    payload = load_health_payload(health_payload_path)
    app = str(payload.get("app") or DEFAULT_APP)
    target = str(payload.get("target") or DEFAULT_TARGET)
    health_gate = evaluate_health_gate(
        payload,
        allow_idle=allow_idle,
        max_unhealthy=max_unhealthy,
        max_restart_rate=max_restart_rate,
    )

    preview = {
        "example": "service_mode",
        "goal": "Understand AGILAB service lifecycle and health gates before starting persistent workers.",
        "target_app": app,
        "target": target,
        "operator_sequence": service_action_sequence(app),
        "health_gate": health_gate,
        "artifacts": {
            "health_json": str(payload.get("path") or f"service/{target}/health.json"),
            "operator_snapshot": str(Path.home() / "log" / "execute" / target / "service_operator_snapshot.json"),
        },
        "real_service_execution": False,
    }
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(preview, indent=2, sort_keys=True), encoding="utf-8")
    return preview


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview AGILAB service-mode actions and health-gate interpretation."
    )
    parser.add_argument(
        "--health-payload",
        type=Path,
        default=HEALTH_PAYLOAD_PATH,
        help="Path to an agi.service.health.v1 JSON payload.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write the service operator preview JSON.",
    )
    parser.add_argument(
        "--allow-idle",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Treat status=idle as healthy in the preview gate.",
    )
    parser.add_argument("--max-unhealthy", type=int, default=0)
    parser.add_argument("--max-restart-rate", type=float, default=0.25)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    preview = build_preview(
        health_payload_path=args.health_payload,
        output_path=args.output,
        allow_idle=bool(args.allow_idle),
        max_unhealthy=max(int(args.max_unhealthy), 0),
        max_restart_rate=max(0.0, min(float(args.max_restart_rate), 1.0)),
    )
    print(json.dumps(preview, indent=2, sort_keys=True))
    return preview


if __name__ == "__main__":
    main()
