#!/usr/bin/env python3
"""Print or replay the command recorded in a UI robot failure bundle."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Sequence


SCHEMA = "agilab.ui_robot_failure_replay.v1"
SUPPORTED_BUNDLE_SCHEMAS = {
    "agilab.widget_robot_failure_bundle.v1",
    "agilab.widget_robot_matrix_failure_bundle.v1",
}


def manifest_path_for(path: Path) -> Path:
    candidate = path.expanduser()
    if candidate.is_dir():
        return candidate / "manifest.json"
    return candidate


def load_manifest(path: Path) -> dict[str, Any]:
    manifest_path = manifest_path_for(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read failure bundle manifest {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Failure bundle manifest {manifest_path} is not a JSON object")
    schema = str(payload.get("schema") or "")
    if schema not in SUPPORTED_BUNDLE_SCHEMAS:
        raise SystemExit(f"Unsupported failure bundle schema {schema!r} in {manifest_path}")
    command = payload.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise SystemExit(f"Failure bundle manifest {manifest_path} does not contain a string command array")
    payload["_manifest_path"] = str(manifest_path)
    return payload


def replay_payload(manifest: dict[str, Any], *, execute: bool, cwd: Path) -> dict[str, Any]:
    command = list(manifest["command"])
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "manifest": manifest.get("_manifest_path"),
        "bundle_schema": manifest.get("schema"),
        "command": command,
        "shell_command": shlex.join(command),
        "cwd": str(cwd),
        "executed": execute,
    }
    if execute:
        completed = subprocess.run(command, cwd=cwd, check=False)
        payload["returncode"] = completed.returncode
    return payload


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "AGILAB UI robot failure replay",
        f"manifest: {payload.get('manifest')}",
        f"cwd: {payload.get('cwd')}",
        f"command: {payload.get('shell_command')}",
    ]
    if payload.get("executed"):
        lines.append(f"exit: {payload.get('returncode')}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Failure bundle directory or manifest.json path.")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Working directory used when --execute is passed.")
    parser.add_argument("--execute", action="store_true", help="Run the recorded command instead of only printing it.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest = load_manifest(args.bundle)
    payload = replay_payload(manifest, execute=args.execute, cwd=args.cwd.expanduser().resolve())
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_human(payload))
    return int(payload.get("returncode", 0))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
