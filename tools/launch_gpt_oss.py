#!/usr/bin/env python3
"""
Launch a local GPT-OSS Responses API server with sensible defaults.

The script wraps ``python -m gpt_oss.responses_api.serve`` and applies the
repository defaults (gpt-oss-120b on port 8000).  Use ``--print-only`` when
you just want to dump the command that would be executed.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List


def _default_checkpoint() -> str:
    return os.getenv("GPT_OSS_MODEL", "gpt-oss-120b")


def _default_port() -> int:
    return int(os.getenv("GPT_OSS_PORT", "8000"))


def _default_backend() -> str:
    return os.getenv("GPT_OSS_BACKEND", "transformers")


def build_command(
    *,
    checkpoint: str,
    backend: str,
    host: str,
    port: int,
    extra: List[str],
) -> List[str]:
    python_exe = sys.executable
    cmd = [
        python_exe,
        "-m",
        "gpt_oss.responses_api.serve",
        "--checkpoint",
        checkpoint,
        "--inference-backend",
        backend,
        "--host",
        host,
        "--port",
        str(port),
    ]
    cmd.extend(extra)
    return cmd


def ensure_dependencies() -> None:
    try:
        import gpt_oss  # noqa: F401
    except ImportError as exc:  # pragma: no cover - defensive
        raise SystemExit(
            "gpt-oss is not installed. Install optional extra with "
            "'uv add \"agilab[offline]\"' or run "
            "'uv pip install gpt-oss universal-offline-ai-chatbot'."
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint",
        default=_default_checkpoint(),
        help="Model checkpoint to serve (default: %(default)s).",
    )
    parser.add_argument(
        "--backend",
        default=_default_backend(),
        help="Inference backend to use (default: %(default)s).",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("GPT_OSS_HOST", "127.0.0.1"),
        help="Bind address for the server (default: %(default)s).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_default_port(),
        help="Port to expose the Responses API (default: %(default)s).",
    )
    parser.add_argument(
        "--workspace",
        default=os.getenv("GPT_OSS_WORKDIR"),
        help="Optional directory to chdir into before launching the server.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the launch command without executing it.",
    )
    parser.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="Additional arguments forwarded to gpt_oss.responses_api.serve.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dependencies()

    extra = args.extra
    if extra and extra[0] == "--":  # allow explicit separator
        extra = extra[1:]

    command = build_command(
        checkpoint=args.checkpoint,
        backend=args.backend,
        host=args.host,
        port=args.port,
        extra=extra,
    )

    if args.print_only:
        print(" ".join(shlex.quote(part) for part in command))
        return

    workdir = args.workspace
    if workdir:
        Path(workdir).mkdir(parents=True, exist_ok=True)
        os.chdir(workdir)

    print(f"[launch-gpt-oss] Starting server: {' '.join(shlex.quote(p) for p in command)}")
    env = os.environ.copy()
    env.setdefault("GPT_OSS_MODEL", args.checkpoint)
    env.setdefault("GPT_OSS_BACKEND", args.backend)
    env.setdefault("GPT_OSS_PORT", str(args.port))
    env.setdefault("GPT_OSS_ENDPOINT", f"http://{args.host}:{args.port}/v1/responses")

    try:
        subprocess.run(command, check=True, env=env)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - runtime error
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
