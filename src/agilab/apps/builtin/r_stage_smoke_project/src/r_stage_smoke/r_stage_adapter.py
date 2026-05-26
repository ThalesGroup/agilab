"""Rscript JSON/artifact stage adapter for the R smoke app."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any


SCHEMA = "agilab.app.r_stage_smoke.v1"
Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class RStageResult:
    """Structured result returned by an external R stage run."""

    output: dict[str, Any]
    manifest: dict[str, Any]
    input_path: Path
    output_path: Path
    artifact_dir: Path
    stdout_path: Path
    stderr_path: Path
    manifest_path: Path
    summary_path: Path


class RStageExecutionError(RuntimeError):
    """Raised when the external R stage process fails the contract."""


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RStageExecutionError(f"R stage output is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RStageExecutionError(f"R stage output must be a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, *, role: str, output_dir: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(output_dir)),
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _artifact_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def _run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    runner: Runner | None,
    env: Mapping[str, str] | None,
) -> subprocess.CompletedProcess[str]:
    process_runner = runner or subprocess.run
    return process_runner(
        list(command),
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
        env=dict(env) if env is not None else None,
    )


def _raise_stage_error(message: str, *, stdout_path: Path, stderr_path: Path) -> None:
    raise RStageExecutionError(f"{message}; stdout={stdout_path}; stderr={stderr_path}")


def run_r_stage(
    script_path: Path | str,
    input_payload: Mapping[str, Any],
    output_dir: Path | str,
    *,
    rscript: str = "Rscript",
    timeout_seconds: int = 120,
    runner: Runner | None = None,
    env: Mapping[str, str] | None = None,
) -> RStageResult:
    """Execute an R stage through a JSON-in, JSON-out, artifacts-out contract."""

    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    artifact_dir = output_root / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    input_path = output_root / "input.json"
    output_path = output_root / "output.json"
    stdout_path = output_root / "stage_stdout.log"
    stderr_path = output_root / "stage_stderr.log"
    manifest_path = output_root / "run_manifest.json"
    summary_path = output_root / "r_stage_summary.json"

    _write_json(input_path, dict(input_payload))
    started_at = time.time()
    script = Path(script_path).expanduser().resolve(strict=False)
    command = [rscript, str(script), str(input_path), str(output_path), str(artifact_dir)]

    try:
        completed = _run_process(
            command,
            cwd=script.parent if script.parent != Path("") else Path.cwd(),
            timeout_seconds=timeout_seconds,
            runner=runner,
            env=env,
        )
    except FileNotFoundError as exc:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(f"{rscript} not found\n", encoding="utf-8")
        _raise_stage_error(
            f"R stage launcher not found: {rscript}",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        raise AssertionError("unreachable") from exc
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text(exc.stderr or "", encoding="utf-8")
        _raise_stage_error(
            f"R stage timed out after {timeout_seconds} seconds",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        raise AssertionError("unreachable") from exc

    runtime_seconds = time.time() - started_at
    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")

    if completed.returncode != 0:
        _raise_stage_error(
            f"R stage failed with exit code {completed.returncode}",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    if not output_path.is_file():
        _raise_stage_error(
            f"R stage did not produce {output_path.name}",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

    output = _read_json_object(output_path)
    artifacts = {
        "input": _artifact(input_path, role="R stage input payload", output_dir=output_root),
        "output": _artifact(output_path, role="R stage output payload", output_dir=output_root),
        "stdout": _artifact(stdout_path, role="R stage stdout log", output_dir=output_root),
        "stderr": _artifact(stderr_path, role="R stage stderr log", output_dir=output_root),
    }
    for artifact_file in _artifact_files(artifact_dir):
        key = f"artifact:{artifact_file.relative_to(artifact_dir)}"
        artifacts[key] = _artifact(artifact_file, role="R stage artifact", output_dir=output_root)

    manifest = {
        "schema": SCHEMA,
        "app": "r_stage_smoke_project",
        "runtime": "Rscript + JSON",
        "deterministic": True,
        "command": command,
        "returncode": completed.returncode,
        "runtime_seconds": round(runtime_seconds, 6),
        "inputs": dict(input_payload),
        "result": output,
        "artifacts": artifacts,
    }
    _write_json(manifest_path, manifest)
    artifacts["manifest"] = _artifact(manifest_path, role="artifact hash manifest", output_dir=output_root)

    summary = {
        "schema": SCHEMA,
        "output_dir": str(output_root),
        "result": output,
        "metrics": {
            "n": int(output.get("n", 0) or 0),
            "mean": float(output.get("mean", 0.0) or 0.0),
            "sd": float(output.get("sd", 0.0) or 0.0),
        },
        "artifacts": artifacts,
        "manifest": str(manifest_path),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }
    _write_json(summary_path, summary)
    summary["artifacts"]["summary"] = _artifact(summary_path, role="worker summary", output_dir=output_root)
    _write_json(summary_path, summary)

    return RStageResult(
        output=output,
        manifest=manifest,
        input_path=input_path,
        output_path=output_path,
        artifact_dir=artifact_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        manifest_path=manifest_path,
        summary_path=summary_path,
    )


def build_r_stage_smoke_artifacts(
    *,
    output_dir: Path,
    script_path: Path,
    x: Sequence[float],
    rscript: str = "Rscript",
    timeout_seconds: int = 120,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Run the smoke R stage and return the persisted summary payload."""

    result = run_r_stage(
        script_path,
        {"x": [float(value) for value in x]},
        output_dir,
        rscript=rscript,
        timeout_seconds=timeout_seconds,
        runner=runner,
    )
    return _read_json_object(result.summary_path)


__all__ = [
    "RStageExecutionError",
    "RStageResult",
    "SCHEMA",
    "build_r_stage_smoke_artifacts",
    "run_r_stage",
]
