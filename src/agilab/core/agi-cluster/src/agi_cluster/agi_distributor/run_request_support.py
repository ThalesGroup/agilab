from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, TypeAlias


RunMode: TypeAlias = int | list[int] | str | None
RUN_STAGES_KEY = "_agilab_run_stages"


@dataclass(frozen=True)
class StageRequest:
    """A single named AGILAB workflow stage."""

    name: str
    args: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("StageRequest.name must be a non-empty string")
        if not isinstance(self.args, Mapping):
            raise TypeError("StageRequest.args must be a mapping")
        object.__setattr__(self, "args", dict(self.args))

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "args": dict(self.args)}


def _coerce_stage_request(stage: StageRequest | Mapping[str, Any]) -> StageRequest:
    if isinstance(stage, StageRequest):
        return stage
    if not isinstance(stage, Mapping):
        raise TypeError("RunRequest.stages entries must be StageRequest or mapping values")
    return StageRequest(name=str(stage.get("name", "")), args=stage.get("args") or {})


@dataclass(frozen=True)
class RunRequest:
    """Typed public request for AGILAB execution.

    ``params`` are app-constructor arguments. ``stages`` are workflow stages and never
    get passed as a top-level ``args`` constructor value.
    """

    params: Mapping[str, Any] = field(default_factory=dict)
    stages: Sequence[StageRequest | Mapping[str, Any]] = field(default_factory=tuple)
    data_in: Any = None
    data_out: Any = None
    reset_target: bool | None = None
    scheduler: str | None = None
    workers: dict[str, int] | None = None
    workers_data_path: str | None = None
    verbose: int = 0
    mode: RunMode = None
    rapids_enabled: bool = False
    benchmark_best_single_node: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.params, Mapping):
            raise TypeError("RunRequest.params must be a mapping")
        params = dict(self.params)
        if "args" in params:
            raise ValueError("RunRequest.params cannot contain legacy key 'args'; use stages=[...]")
        if "steps" in params:
            raise ValueError("RunRequest.params cannot contain legacy key 'steps'; use stages=[...]")
        if RUN_STAGES_KEY in params:
            raise ValueError(f"RunRequest.params cannot contain reserved key {RUN_STAGES_KEY!r}")
        object.__setattr__(self, "params", params)
        object.__setattr__(self, "stages", tuple(_coerce_stage_request(stage) for stage in self.stages))
        if self.workers is not None and not isinstance(self.workers, dict):
            raise ValueError("workers must be a dict. {'ip-address':nb-worker}")

    def to_app_kwargs(self) -> dict[str, Any]:
        payload = dict(self.params)
        if self.data_in is not None:
            payload["data_in"] = self.data_in
        if self.data_out is not None:
            payload["data_out"] = self.data_out
        if self.reset_target is not None:
            payload["reset_target"] = self.reset_target
        return payload

    def to_dispatch_kwargs(self) -> dict[str, Any]:
        payload = self.to_app_kwargs()
        if self.stages:
            payload[RUN_STAGES_KEY] = [stage.to_payload() for stage in self.stages]
        return payload

    def to_target_kwargs(self) -> dict[str, Any]:
        return self.to_dispatch_kwargs()

    def with_execution(self, **updates: Any) -> "RunRequest":
        allowed = {
            "scheduler",
            "workers",
            "workers_data_path",
            "verbose",
            "mode",
            "rapids_enabled",
            "benchmark_best_single_node",
        }
        unknown = set(updates) - allowed
        if unknown:
            raise TypeError(f"Unknown execution field(s): {', '.join(sorted(unknown))}")
        return replace(self, **updates)
