"""Reduce-contract adoption for the built-in UAV relay queue app."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agi_node.reduction import (
    ReduceArtifact,
    ReduceContract,
    ReducePartial,
    require_payload_keys,
)


REDUCE_ARTIFACT_FILENAME_TEMPLATE = "reduce_summary_worker_{worker_id}.json"
REDUCE_ARTIFACT_NAME = "uav_relay_queue_reduce_summary"
REDUCER_NAME = "uav_relay_queue.queue-metrics.v1"

_REQUIRED_METRIC_KEYS = (
    "scenario",
    "routing_policy",
    "random_seed",
    "packets_generated",
    "packets_delivered",
    "packets_dropped",
    "mean_e2e_delay_ms",
    "mean_queue_wait_ms",
    "max_queue_depth_pkts",
    "bottleneck_relay",
)
_REQUIRED_PAYLOAD_KEYS = (
    "scenario_count",
    "packets_generated",
    "packets_delivered",
    "packets_dropped",
    "delay_weighted_sum_ms",
    "queue_wait_weighted_sum_ms",
    "max_queue_depth_pkts",
    "scenarios",
    "routing_policies",
    "bottleneck_relays",
    "random_seeds",
)


def _as_int(metrics: Mapping[str, Any], key: str) -> int:
    return int(metrics.get(key, 0) or 0)


def _as_float(metrics: Mapping[str, Any], key: str) -> float:
    return float(metrics.get(key, 0.0) or 0.0)


def _sorted_strings(values: set[str]) -> list[str]:
    return sorted(value for value in values if value)


def _merge_uav_relay_queue_partials(partials: Sequence[ReducePartial]) -> dict[str, Any]:
    scenarios: set[str] = set()
    routing_policies: set[str] = set()
    bottleneck_relays: set[str] = set()
    random_seeds: set[str] = set()
    generated = 0
    delivered = 0
    dropped = 0
    delay_weighted_sum_ms = 0.0
    queue_wait_weighted_sum_ms = 0.0
    max_queue_depth_pkts = 0

    for partial in partials:
        payload = partial.payload
        generated += int(payload["packets_generated"])
        delivered += int(payload["packets_delivered"])
        dropped += int(payload["packets_dropped"])
        delay_weighted_sum_ms += float(payload["delay_weighted_sum_ms"])
        queue_wait_weighted_sum_ms += float(payload["queue_wait_weighted_sum_ms"])
        max_queue_depth_pkts = max(max_queue_depth_pkts, int(payload["max_queue_depth_pkts"]))
        scenarios.update(str(item) for item in payload["scenarios"])
        routing_policies.update(str(item) for item in payload["routing_policies"])
        bottleneck_relays.update(str(item) for item in payload["bottleneck_relays"])
        random_seeds.update(str(item) for item in payload["random_seeds"])

    return {
        "scenario_count": len(scenarios),
        "scenarios": _sorted_strings(scenarios),
        "routing_policies": _sorted_strings(routing_policies),
        "random_seeds": _sorted_strings(random_seeds),
        "bottleneck_relays": _sorted_strings(bottleneck_relays),
        "packets_generated": generated,
        "packets_delivered": delivered,
        "packets_dropped": dropped,
        "pdr": round(float(delivered) / float(generated), 4) if generated else 0.0,
        "mean_e2e_delay_ms": round(delay_weighted_sum_ms / delivered, 3) if delivered else 0.0,
        "mean_queue_wait_ms": round(queue_wait_weighted_sum_ms / delivered, 3) if delivered else 0.0,
        "max_queue_depth_pkts": max_queue_depth_pkts,
    }


def _validate_uav_relay_queue_artifact(artifact: ReduceArtifact) -> None:
    payload = artifact.payload
    if int(payload["scenario_count"]) <= 0:
        raise ValueError("uav_relay_queue reducer produced no scenarios")
    if int(payload["packets_generated"]) <= 0:
        raise ValueError("uav_relay_queue reducer produced no generated packets")


UAV_RELAY_QUEUE_REDUCE_CONTRACT = ReduceContract(
    name=REDUCER_NAME,
    artifact_name=REDUCE_ARTIFACT_NAME,
    merge=_merge_uav_relay_queue_partials,
    validate_partial=require_payload_keys(*_REQUIRED_PAYLOAD_KEYS),
    validate_artifact=_validate_uav_relay_queue_artifact,
    metadata={
        "app": "uav_relay_queue_project",
        "domain": "uav-relay-queue",
        "scope": "scenario-summary",
    },
)


def reduce_artifact_path(output_dir: Path | str, worker_id: int | str) -> Path:
    filename = REDUCE_ARTIFACT_FILENAME_TEMPLATE.format(worker_id=worker_id)
    return Path(output_dir) / filename


def partial_from_summary_metrics(
    metrics: Mapping[str, Any],
    *,
    partial_id: str,
    artifact_path: Path | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReducePartial:
    missing = [key for key in _REQUIRED_METRIC_KEYS if key not in metrics]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"uav_relay_queue summary metrics missing columns: {missing_text}")

    delivered = _as_int(metrics, "packets_delivered")
    scenario = str(metrics["scenario"])
    routing_policy = str(metrics["routing_policy"])
    bottleneck_relay = str(metrics["bottleneck_relay"])
    random_seed = str(metrics["random_seed"])
    payload = {
        "scenario_count": 1,
        "scenarios": [scenario],
        "routing_policies": [routing_policy],
        "random_seeds": [random_seed],
        "bottleneck_relays": [bottleneck_relay] if bottleneck_relay else [],
        "packets_generated": _as_int(metrics, "packets_generated"),
        "packets_delivered": delivered,
        "packets_dropped": _as_int(metrics, "packets_dropped"),
        "delay_weighted_sum_ms": _as_float(metrics, "mean_e2e_delay_ms") * delivered,
        "queue_wait_weighted_sum_ms": _as_float(metrics, "mean_queue_wait_ms") * delivered,
        "max_queue_depth_pkts": _as_int(metrics, "max_queue_depth_pkts"),
    }
    return ReducePartial(
        partial_id=partial_id,
        payload=payload,
        metadata=metadata or {},
        artifact_path=str(artifact_path) if artifact_path else None,
    )


def build_reduce_artifact(partials: Sequence[ReducePartial]) -> ReduceArtifact:
    return UAV_RELAY_QUEUE_REDUCE_CONTRACT.build_artifact(partials)


def write_reduce_artifact(
    metrics: Mapping[str, Any],
    output_dir: Path | str,
    *,
    worker_id: int | str,
) -> Path:
    output_path = reduce_artifact_path(output_dir, worker_id)
    partial = partial_from_summary_metrics(
        metrics,
        partial_id=f"uav_relay_queue_worker_{worker_id}_{metrics['artifact_stem']}",
        artifact_path=output_path,
        metadata={
            "worker_id": str(worker_id),
            "artifact_stem": str(metrics.get("artifact_stem", "")),
        },
    )
    artifact = build_reduce_artifact((partial,))
    output_path.write_text(
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


__all__ = [
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "UAV_RELAY_QUEUE_REDUCE_CONTRACT",
    "build_reduce_artifact",
    "partial_from_summary_metrics",
    "reduce_artifact_path",
    "write_reduce_artifact",
]
