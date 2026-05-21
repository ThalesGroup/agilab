#!/usr/bin/env python3
"""Launch the source-checkout AGILAB Streamlit UI with the required UI extra."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Mapping


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_uv_binary() -> str | None:
    uv_bin = shutil.which("uv")
    if uv_bin:
        return uv_bin

    fallback = Path.home() / ".local" / "bin" / "uv"
    if fallback.exists():
        return str(fallback)
    return None


def build_streamlit_command(root: Path, app_args: list[str], uv_bin: str) -> list[str]:
    return [
        uv_bin,
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--extra",
        "ui",
        "python",
        "-m",
        "streamlit",
        "run",
        str(root / "src" / "agilab" / "main_page.py"),
        "--",
        *app_args,
    ]


def build_child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    child_env = dict(environ)
    for key in ("UV_NO_SYNC", "UV_RUN_RECURSION_DEPTH", "VIRTUAL_ENV"):
        child_env.pop(key, None)
    return child_env


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch AGILAB's source Streamlit UI through uv with the ui extra enabled."
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Print the uv command instead of executing it.",
    )
    known, app_args = parser.parse_known_args(argv)
    known.app_args = app_args
    return known


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    uv_bin = resolve_uv_binary()
    if uv_bin is None:
        print("Unable to locate uv. Install uv or add it to PATH before launching AGILAB.", file=sys.stderr)
        return 127

    command = build_streamlit_command(repo_root(), args.app_args, uv_bin)
    if args.print_command:
        print(shlex.join(command))
        return 0

    os.execvpe(command[0], command, build_child_environment(os.environ))
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
