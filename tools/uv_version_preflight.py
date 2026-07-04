#!/usr/bin/env python3
"""Check that the active uv binary is new enough for AGILAB workflows."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Sequence


DEFAULT_MIN_UV = "0.11.26"
_VERSION_RE = re.compile(r"uv\s+(?P<version>\d+(?:\.\d+){1,3})")


@dataclass(frozen=True, order=True)
class Version:
    parts: tuple[int, ...]

    @classmethod
    def parse(cls, value: str) -> "Version":
        parts = tuple(int(part) for part in value.split("."))
        if len(parts) < 2:
            raise ValueError(f"Invalid uv version: {value!r}")
        return cls(parts + (0,) * (4 - len(parts)))

    def compact(self) -> str:
        parts = list(self.parts)
        while len(parts) > 2 and parts[-1] == 0:
            parts.pop()
        return ".".join(str(part) for part in parts)


def _uv_version(argv: Sequence[str]) -> Version:
    try:
        completed = subprocess.run(
            [*argv, "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "uv is not installed or is not on PATH. Install uv before running AGILAB workflows."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"Failed to execute {' '.join(argv)} --version: {detail}") from exc

    output = (completed.stdout or completed.stderr or "").strip()
    match = _VERSION_RE.search(output)
    if not match:
        raise RuntimeError(f"Could not parse uv version from: {output!r}")
    return Version.parse(match.group("version"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-version", default=DEFAULT_MIN_UV)
    parser.add_argument("--uv", default="uv", help="uv executable to check")
    parser.add_argument("--json", action="store_true", help="Emit compact JSON output")
    args = parser.parse_args(argv)

    required = Version.parse(args.min_version)
    try:
        current = _uv_version([args.uv])
    except RuntimeError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        else:
            print(f"UV preflight failed: {exc}", file=sys.stderr)
        return 2

    ok = current >= required
    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "current": current.compact(),
                    "minimum": required.compact(),
                },
                sort_keys=True,
            )
        )
    elif ok:
        print(f"UV preflight passed: uv {current.compact()} >= {required.compact()}")
    else:
        print(
            f"UV preflight failed: uv {current.compact()} < {required.compact()}. "
            "Upgrade with `uv self update` or your platform package manager.",
            file=sys.stderr,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
