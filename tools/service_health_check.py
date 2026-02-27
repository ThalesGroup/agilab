#!/usr/bin/env python3
"""CLI helper to export and evaluate AGI service health."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv


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
        action="store_true",
        help="Treat status=idle as healthy.",
    )
    parser.add_argument(
        "--max-unhealthy",
        type=int,
        default=0,
        help="Maximum tolerated unhealthy workers before failing (default: 0).",
    )
    parser.add_argument("--verbose", type=int, default=0, help="AgiEnv verbosity.")
    return parser


def _evaluate_health(
    payload: dict,
    *,
    allow_idle: bool,
    max_unhealthy: int,
) -> tuple[int, str]:
    status = str(payload.get("status", "unknown") or "unknown").lower()
    unhealthy = int(payload.get("workers_unhealthy_count", 0) or 0)

    if unhealthy > max_unhealthy:
        return 2, f"unhealthy workers {unhealthy} exceeds limit {max_unhealthy}"
    if status in {"error", "degraded"}:
        return 3, f"service status is {status}"
    if status == "idle" and not allow_idle:
        return 4, "service status is idle (use --allow-idle to accept)"
    return 0, "ok"


async def _run(args: argparse.Namespace) -> int:
    env = AgiEnv(apps_path=Path(args.apps_path), app=str(args.app), verbose=int(args.verbose))
    payload = await AGI.serve(
        env,
        action="health",
        health_output_path=(args.health_output_path or None),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    code, reason = _evaluate_health(
        payload,
        allow_idle=bool(args.allow_idle),
        max_unhealthy=max(int(args.max_unhealthy), 0),
    )
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
