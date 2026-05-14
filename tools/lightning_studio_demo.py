#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path


DEFAULT_ACTIVE_APP = "flight_telemetry_project"
DEFAULT_PORT = 8501
DEFAULT_RUNTIME_DIR = ".lightning_studio_runtime"


def find_repo_root(start: Path) -> Path:
    start = start.expanduser().resolve()
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "agilab" / "main_page.py").is_file():
            return candidate
    raise RuntimeError(
        f"Could not find the AGILAB repository root from {start}. "
        "Run this command from inside a checkout of https://github.com/ThalesGroup/agilab."
    )


def resolve_runtime_dir(repo_root: Path, runtime_dir: str) -> Path:
    candidate = Path(runtime_dir).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    return candidate.resolve()


def build_demo_env(repo_root: Path, runtime_dir: Path, environ: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(environ or os.environ)
    env["IS_SOURCE_ENV"] = "1"
    env["AGI_CLUSTER_ENABLED"] = "0"
    env.pop("IS_WORKER_ENV", None)
    env["PYTHONUNBUFFERED"] = "1"
    env["AGI_LOG_DIR"] = str(runtime_dir / "log")
    env["AGI_EXPORT_DIR"] = str(runtime_dir / "export")
    env["AGI_LOCAL_SHARE"] = str(runtime_dir / "localshare")
    env["MLFLOW_TRACKING_DIR"] = str(runtime_dir / "mlflow")
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["APPS_PATH"] = str((repo_root / "src" / "agilab" / "apps").resolve())
    return env


def ensure_runtime_layout(runtime_dir: Path) -> None:
    for rel in ("log", "export", "localshare", "mlflow"):
        (runtime_dir / rel).mkdir(parents=True, exist_ok=True)


def build_streamlit_command(repo_root: Path, *, active_app: str, port: int) -> list[str]:
    cmd = [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "streamlit",
        "run",
        str((repo_root / "src" / "agilab" / "main_page.py").resolve()),
        "--server.address",
        "0.0.0.0",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--",
        "--apps-path",
        str((repo_root / "src" / "agilab" / "apps").resolve()),
    ]
    if active_app:
        cmd.extend(["--active-app", active_app])
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Launch the AGILAB UI in a Lightning Studio friendly local-only mode. "
            "This is a single-machine demo path, not the full distributed product path."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="AGILAB repository root or any path inside the repository (default: current directory).",
    )
    parser.add_argument(
        "--runtime-dir",
        default=DEFAULT_RUNTIME_DIR,
        help=(
            "Writable runtime root for logs, exports, local share, and MLflow tracking. "
            "Relative paths are resolved under the repository root."
        ),
    )
    parser.add_argument(
        "--active-app",
        default=DEFAULT_ACTIVE_APP,
        help="Active app name or path to select on startup (default: flight_telemetry_project).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Streamlit server port to expose in Lightning Studio (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Print the final Streamlit command and exit without launching it.",
    )
    parser.add_argument(
        "--print-env",
        action="store_true",
        help="Print the demo-specific environment overrides before launching.",
    )
    args = parser.parse_args(argv)

    repo_root = find_repo_root(Path(args.repo_root))
    runtime_dir = resolve_runtime_dir(repo_root, args.runtime_dir)
    ensure_runtime_layout(runtime_dir)
    env = build_demo_env(repo_root, runtime_dir)
    cmd = build_streamlit_command(repo_root, active_app=args.active_app, port=args.port)

    print(f"[lightning-demo] repo root: {repo_root}")
    print(f"[lightning-demo] runtime dir: {runtime_dir}")
    print(
        "[lightning-demo] This launcher forces local-only mode for a single Studio VM. "
        "It is intended for the AGILAB UI demo, not remote cluster orchestration."
    )

    if args.print_env:
        for key in (
            "IS_SOURCE_ENV",
            "AGI_CLUSTER_ENABLED",
            "AGI_LOG_DIR",
            "AGI_EXPORT_DIR",
            "AGI_LOCAL_SHARE",
            "MLFLOW_TRACKING_DIR",
            "APPS_PATH",
        ):
            print(f"{key}={env[key]}")

    rendered = shlex.join(cmd)
    print(f"[lightning-demo] command: {rendered}")

    if args.print_command:
        return 0

    return subprocess.call(cmd, cwd=str(repo_root), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
