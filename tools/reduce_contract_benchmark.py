#!/usr/bin/env python3
"""Benchmark the public AGILAB reducer contract with deterministic partials."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from typing import Sequence

from agi_node import ReduceContract, ReducePartial, numeric_sum_merge, require_payload_keys


DEFAULT_PARTIALS = 8
DEFAULT_ITEMS_PER_PARTIAL = 10_000
DEFAULT_TARGET_SECONDS = 5.0


@dataclass(frozen=True)
class ReduceBenchmarkSummary:
    success: bool
    partial_count: int
    items_per_partial: int
    total_items: int
    total_duration_seconds: float
    target_seconds: float
    within_target: bool
    artifact: dict[str, object]


def build_partials(partial_count: int, items_per_partial: int) -> list[ReducePartial]:
    if partial_count <= 0:
        raise ValueError("partial_count must be positive")
    if items_per_partial <= 0:
        raise ValueError("items_per_partial must be positive")

    partials: list[ReducePartial] = []
    for partial_idx in range(partial_count):
        first_value = partial_idx * items_per_partial
        values = range(first_value, first_value + items_per_partial)
        partials.append(
            ReducePartial(
                partial_id=f"partition-{partial_idx}",
                payload={
                    "items": items_per_partial,
                    "requested_bandwidth": sum(value + 1 for value in values),
                    "delivered_bandwidth": sum(value for value in values),
                },
                metadata={"partition_index": partial_idx},
            )
        )
    return partials


def expected_payload(partial_count: int, items_per_partial: int) -> dict[str, int]:
    total_items = partial_count * items_per_partial
    delivered = sum(range(total_items))
    return {
        "items": total_items,
        "requested_bandwidth": delivered + total_items,
        "delivered_bandwidth": delivered,
    }


def build_contract() -> ReduceContract:
    keys = ("items", "requested_bandwidth", "delivered_bandwidth")
    return ReduceContract(
        name="public-reduce-benchmark",
        artifact_name="public_reduce_benchmark_summary",
        merge=numeric_sum_merge(*keys),
        validate_partial=require_payload_keys(*keys),
        metadata={"benchmark": "reduce_contract"},
    )


def run_benchmark(
    *,
    partial_count: int = DEFAULT_PARTIALS,
    items_per_partial: int = DEFAULT_ITEMS_PER_PARTIAL,
    target_seconds: float = DEFAULT_TARGET_SECONDS,
) -> ReduceBenchmarkSummary:
    start = time.perf_counter()
    partials = build_partials(partial_count, items_per_partial)
    artifact = build_contract().build_artifact(partials)
    duration = time.perf_counter() - start

    expected = expected_payload(partial_count, items_per_partial)
    success = (
        artifact.payload == expected
        and artifact.partial_count == partial_count
        and artifact.partial_ids == tuple(partial.partial_id for partial in partials)
    )
    return ReduceBenchmarkSummary(
        success=success,
        partial_count=partial_count,
        items_per_partial=items_per_partial,
        total_items=partial_count * items_per_partial,
        total_duration_seconds=duration,
        target_seconds=target_seconds,
        within_target=success and duration <= target_seconds,
        artifact=artifact.to_dict(),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the public AGILAB reduce-contract benchmark."
    )
    parser.add_argument("--partials", type=int, default=DEFAULT_PARTIALS)
    parser.add_argument("--items-per-partial", type=int, default=DEFAULT_ITEMS_PER_PARTIAL)
    parser.add_argument("--target-seconds", type=float, default=DEFAULT_TARGET_SECONDS)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    summary = run_benchmark(
        partial_count=args.partials,
        items_per_partial=args.items_per_partial,
        target_seconds=args.target_seconds,
    )
    payload = asdict(summary)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        verdict = "PASS" if summary.success and summary.within_target else "FAIL"
        print(
            f"reduce-contract-benchmark: {verdict} "
            f"{summary.total_duration_seconds:.4f}s <= {summary.target_seconds:.1f}s "
            f"for {summary.partial_count} partials / {summary.total_items} items"
        )
    return 0 if summary.success and summary.within_target else 1


if __name__ == "__main__":
    raise SystemExit(main())
