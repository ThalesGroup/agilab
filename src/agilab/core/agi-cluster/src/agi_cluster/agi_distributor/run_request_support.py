from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, TypeAlias


RunMode: TypeAlias = int | list[int] | str | None
RUN_STEPS_KEY = "_agilab_run_steps"


@dataclass(frozen=True)
class StepRequest:
    """A single named AGILAB workflow step."""

    name: str
    args: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("StepRequest.name must be a non-empty string")
        if not isinstance(self.args, Mapping):
            raise TypeError("StepRequest.args must be a mapping")
        object.__setattr__(self, "args", dict(self.args))

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "args": dict(self.args)}


def _coerce_step_request(step: StepRequest | Mapping[str, Any]) -> StepRequest:
    if isinstance(step, StepRequest):
        return step
    if not isinstance(step, Mapping):
        raise TypeError("RunRequest.steps entries must be StepRequest or mapping values")
    return StepRequest(name=str(step.get("name", "")), args=step.get("args") or {})


@dataclass(frozen=True)
class RunRequest:
    """Typed public request for AGILAB execution.

    ``params`` are app-constructor arguments. ``steps`` are workflow steps and never
    get passed as a top-level ``args`` constructor value.
    """

    params: Mapping[str, Any] = field(default_factory=dict)
    steps: Sequence[StepRequest | Mapping[str, Any]] = field(default_factory=tuple)
    data_in: Any = None
    data_out: Any = None
    reset_target: bool | None = None
    scheduler: str | None = None
    workers: dict[str, int] | None = None
    workers_data_path: str | None = None
    verbose: int = 0
    mode: RunMode = None
    rapids_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.params, Mapping):
            raise TypeError("RunRequest.params must be a mapping")
        params = dict(self.params)
        if "args" in params:
            raise ValueError("RunRequest.params cannot contain legacy key 'args'; use steps=[...]")
        if RUN_STEPS_KEY in params:
            raise ValueError(f"RunRequest.params cannot contain reserved key {RUN_STEPS_KEY!r}")
        object.__setattr__(self, "params", params)
        object.__setattr__(self, "steps", tuple(_coerce_step_request(step) for step in self.steps))
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
        if self.steps:
            payload[RUN_STEPS_KEY] = [step.to_payload() for step in self.steps]
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
        }
        unknown = set(updates) - allowed
        if unknown:
            raise TypeError(f"Unknown execution field(s): {', '.join(sorted(unknown))}")
        return replace(self, **updates)
