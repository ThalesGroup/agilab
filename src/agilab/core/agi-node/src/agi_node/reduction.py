from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Number
from typing import Any


SCHEMA_VERSION = 1
Payload = Mapping[str, Any]
MergeFn = Callable[[Sequence["ReducePartial"]], Payload]
PartialValidator = Callable[["ReducePartial"], None]
ArtifactValidator = Callable[["ReduceArtifact"], None]


def _as_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    return dict(value)


@dataclass(frozen=True)
class ReducePartial:
    """A worker-produced partial output that can be consumed by a reducer."""

    partial_id: str
    payload: Payload
    metadata: Payload = field(default_factory=dict)
    artifact_path: str | None = None

    def __post_init__(self) -> None:
        if not self.partial_id:
            raise ValueError("partial_id must not be empty")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "payload", _as_dict(self.payload))
        object.__setattr__(self, "metadata", _as_dict(self.metadata))


@dataclass(frozen=True)
class ReduceArtifact:
    """Standard serialized result of a reduce contract run."""

    name: str
    reducer: str
    payload: Payload
    partial_count: int
    partial_ids: tuple[str, ...] = ()
    metadata: Payload = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must not be empty")
        if not self.reducer:
            raise ValueError("reducer must not be empty")
        if self.partial_count < 0:
            raise ValueError("partial_count must not be negative")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "payload", _as_dict(self.payload))
        object.__setattr__(self, "metadata", _as_dict(self.metadata))
        object.__setattr__(self, "partial_ids", tuple(self.partial_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "reducer": self.reducer,
            "partial_count": self.partial_count,
            "partial_ids": list(self.partial_ids),
            "payload": _as_dict(self.payload),
            "metadata": _as_dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReduceArtifact":
        schema_version = value.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported reduce artifact schema: {schema_version!r}")
        return cls(
            name=str(value["name"]),
            reducer=str(value["reducer"]),
            payload=_as_dict(value["payload"]),
            partial_count=int(value["partial_count"]),
            partial_ids=tuple(str(item) for item in value.get("partial_ids", ())),
            metadata=_as_dict(value.get("metadata", {})),
            schema_version=SCHEMA_VERSION,
        )


@dataclass(frozen=True)
class ReduceContract:
    """Named reducer with explicit partial input and artifact output semantics."""

    name: str
    merge: MergeFn
    artifact_name: str = "reduce_summary"
    validate_partial: PartialValidator | None = None
    validate_artifact: ArtifactValidator | None = None
    metadata: Payload = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must not be empty")
        if not self.artifact_name:
            raise ValueError("artifact_name must not be empty")
        if not callable(self.merge):
            raise TypeError("merge must be callable")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        object.__setattr__(self, "metadata", _as_dict(self.metadata))

    def build_artifact(self, partials: Iterable[ReducePartial]) -> ReduceArtifact:
        partial_list = tuple(partials)
        if not partial_list:
            raise ValueError("reduce contract requires at least one partial")

        for partial in partial_list:
            if self.validate_partial is not None:
                self.validate_partial(partial)

        payload = self.merge(partial_list)
        if not isinstance(payload, Mapping):
            raise TypeError("merge must return a mapping payload")

        artifact = ReduceArtifact(
            name=self.artifact_name,
            reducer=self.name,
            payload=payload,
            partial_count=len(partial_list),
            partial_ids=tuple(partial.partial_id for partial in partial_list),
            metadata=self.metadata,
        )
        if self.validate_artifact is not None:
            self.validate_artifact(artifact)
        return artifact


def require_payload_keys(*keys: str) -> PartialValidator:
    if not keys:
        raise ValueError("at least one required key is needed")

    def _validate(partial: ReducePartial) -> None:
        missing = [key for key in keys if key not in partial.payload]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"Partial {partial.partial_id!r} is missing: {missing_text}")

    return _validate


def numeric_sum_merge(*keys: str) -> MergeFn:
    if not keys:
        raise ValueError("at least one numeric key is needed")

    def _merge(partials: Sequence[ReducePartial]) -> dict[str, Any]:
        totals = {key: 0 for key in keys}
        for partial in partials:
            for key in keys:
                value = partial.payload[key]
                if isinstance(value, bool) or not isinstance(value, Number):
                    raise TypeError(
                        f"Partial {partial.partial_id!r} key {key!r} is not numeric"
                    )
                totals[key] += value
        return totals

    return _merge
