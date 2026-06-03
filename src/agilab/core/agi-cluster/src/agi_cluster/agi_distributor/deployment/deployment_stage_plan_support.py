import hashlib
import json
import logging
import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agi_cluster.agi_distributor.deployment_stage_cache_support import (
    DEPLOY_STAGE_CACHE_SCHEMA,
    _deploy_stage_file_fingerprint,
    _write_deploy_stage_cache,
)


def _deploy_stage_digest(
    stage_name: str,
    cmd: str,
    cwd: Path,
    *,
    inputs: list[Path],
) -> str:
    unique_inputs = sorted(
        {path.expanduser().resolve(strict=False).as_posix(): path for path in inputs}
    )
    payload = {
        "schema": DEPLOY_STAGE_CACHE_SCHEMA,
        "stage": stage_name,
        "cmd": cmd,
        "cwd": cwd.expanduser().resolve(strict=False).as_posix(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "os_name": os.name,
        "inputs": [
            _deploy_stage_file_fingerprint(Path(path)) for path in unique_inputs
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


async def _run_cached_deploy_stage(
    *,
    stage_name: str,
    cmd: str,
    cwd: Path,
    run_fn: Callable[..., Any],
    cache_enabled: bool,
    cache_state: dict[str, Any],
    cache_path: Path,
    inputs: list[Path],
    output_probe: Callable[[], bool],
    log: logging.Logger | Any,
) -> bool:
    if not cache_enabled:
        await run_fn(cmd, cwd)
        return True

    digest = _deploy_stage_digest(stage_name, cmd, cwd, inputs=inputs)
    stages = cache_state.setdefault("stages", {})
    cached = stages.get(stage_name) if isinstance(stages, dict) else None
    if isinstance(cached, dict) and cached.get("digest") == digest and output_probe():
        log.info("Skipping cached deploy stage: %s", stage_name)
        return False

    await run_fn(cmd, cwd)
    if output_probe() and isinstance(stages, dict):
        stages[stage_name] = {
            "digest": _deploy_stage_digest(stage_name, cmd, cwd, inputs=inputs)
        }
        _write_deploy_stage_cache(cache_path, cache_state)
    return True


@dataclass(frozen=True)
class _DeployPlanNode:
    name: str
    cmd: str
    cwd: Path
    inputs: list[Path]
    output_probe: Callable[[], bool]
    dependencies: tuple[str, ...] = ()


class _DeployPlan:
    def __init__(
        self,
        *,
        run_fn: Callable[..., Any],
        cache_enabled: bool,
        cache_state: dict[str, Any],
        cache_path: Path,
        log: logging.Logger | Any,
        time_fn: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._run_fn = run_fn
        self._cache_enabled = cache_enabled
        self._cache_state = cache_state
        self._cache_path = cache_path
        self._log = log
        self._time_fn = time_fn
        self._completed: set[str] = set()
        self.results: dict[str, str] = {}
        self.timings: list[dict[str, Any]] = []

    def record_timing(self, stage: str, result: str, seconds: float) -> None:
        self.timings.append(
            {
                "stage": stage,
                "result": result,
                "seconds": round(float(seconds), 6),
            }
        )

    async def run(self, node: _DeployPlanNode) -> str:
        missing = [
            dependency
            for dependency in node.dependencies
            if dependency not in self._completed
        ]
        if missing:
            raise RuntimeError(
                f"Deploy plan stage {node.name!r} is missing dependencies: {', '.join(missing)}"
            )

        result = "failed"
        started_at = self._time_fn()
        try:
            ran = await _run_cached_deploy_stage(
                stage_name=node.name,
                cmd=node.cmd,
                cwd=node.cwd,
                run_fn=self._run_fn,
                cache_enabled=self._cache_enabled,
                cache_state=self._cache_state,
                cache_path=self._cache_path,
                inputs=node.inputs,
                output_probe=node.output_probe,
                log=self._log,
            )
            result = "ran" if ran else "skipped"
            self.results[node.name] = result
            self._completed.add(node.name)
            return result
        finally:
            self.record_timing(node.name, result, self._time_fn() - started_at)


