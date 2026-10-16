"""Worker-owned, bounded verification of an original upstream queue delivery trace."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping


DELIVERY_TRACE_SCHEMA = "agilab.uav_delivered_packet_trace.v1"
HANDOFF_RECEIPT_SCHEMA = "agilab.uav_packet_handoff_receipt.v1"
MAX_CONTEXT_BYTES = 1_048_576
MAX_TRACE_PACKETS = 10_000


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _parents(path: Path, root: Path) -> list[tuple[Path, tuple[int, int]]]:
    parents = []
    current = path.parent
    while True:
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ValueError("Upstream artifact parent must be a real producer directory.")
        parents.append((current, (info.st_dev, info.st_ino)))
        if current == root:
            return parents
        current = current.parent


def _original_bytes(binding: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    if binding.get("artifact") != "queue_metrics" or binding.get("producer") != "queue_baseline":
        raise ValueError("Upstream delivery trace requires its original queue_metrics producer.")
    if binding.get("kind") != "summary_metrics" or binding.get("identity_kind") is not None:
        raise ValueError("Upstream delivery trace requires a summary metrics file artifact.")
    path_value, root_value = binding.get("path"), binding.get("producer_run_root")
    if not isinstance(path_value, str) or not isinstance(root_value, str):
        raise ValueError("Upstream artifact requires its original path and producer root.")
    path, root = Path(path_value), Path(root_value)
    if not path.is_absolute() or not root.is_absolute() or ".." in path.parts or ".." in root.parts:
        raise ValueError("Upstream artifact requires absolute producer paths.")
    # Resolve only the authorized root; inspect every component below it without
    # following links. Resolving the artifact first would hide a replaced link.
    root = root.resolve(strict=True)
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Upstream artifact escapes its original producer root.")
    expected_resolved = binding.get("resolved_path")
    if expected_resolved is not None and expected_resolved != str(path):
        raise ValueError("Upstream artifact has changed original resolved path identity.")
    size, digest = binding.get("size_bytes"), binding.get("sha256")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_CONTEXT_BYTES:
        raise ValueError("Upstream artifact byte size exceeds the bounded input limit.")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("Upstream artifact requires its original SHA-256 identity.")
    parents = _parents(path, root)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != size:
        raise ValueError("Upstream artifact is a symlink, nonregular file or has changed size identity.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if _signature(os.fstat(stream.fileno())) != _signature(before):
            raise ValueError("Upstream artifact changed while opening its original file.")
        raw = stream.read(MAX_CONTEXT_BYTES + 1)
        if _signature(os.fstat(stream.fileno())) != _signature(before):
            raise ValueError("Upstream artifact changed while reading its original bytes.")
    if _signature(path.lstat()) != _signature(before):
        raise ValueError("Upstream artifact changed after reading its original bytes.")
    for parent, identity in parents:
        observed = parent.lstat()
        if not stat.S_ISDIR(observed.st_mode) or (observed.st_dev, observed.st_ino) != identity:
            raise ValueError("Upstream producer directory changed while reading the artifact.")
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Upstream artifact differs from its original byte identity.")
    return raw, {
        "schema": HANDOFF_RECEIPT_SCHEMA, "artifact": "queue_metrics",
        "producer": "queue_baseline", "path": path_value,
        "producer_run_root": root_value, "size_bytes": size, "sha256": digest,
        "read_scope": "worker", "numerically_conditioned": True,
        "worker_pid": os.getpid(),
    }


def _finite_time(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Upstream delivery trace has invalid {field}.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"Upstream delivery trace requires finite valid {field}.") from exc
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"Upstream delivery trace requires finite valid {field}.")
    return number


def read_upstream_delivery_trace(binding: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read original bytes inside the app worker and reject incomplete trace data."""
    try:
        raw, receipt = _original_bytes(binding)
    except OSError as exc:
        raise ValueError(f"Upstream producer artifact could not be read: {exc}") from exc
    try:
        payload = json.loads(raw)
        json.dumps(payload, allow_nan=False)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Upstream delivery trace requires finite JSON data.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Upstream delivery trace requires a summary mapping.")
    trace = payload.get("delivery_trace")
    if not isinstance(trace, dict) or trace.get("schema") != DELIVERY_TRACE_SCHEMA:
        raise ValueError("Upstream summary has no supported delivered packet trace.")
    source_end = _finite_time(trace.get("source_emission_horizon_s"), "source horizon", positive=True)
    simulation_end = _finite_time(trace.get("simulation_horizon_s"), "simulation horizon", positive=True)
    if simulation_end < source_end or payload.get("sim_time_s") != source_end:
        raise ValueError("Upstream delivery trace has inconsistent simulation horizons.")
    packets = trace.get("packets")
    if not isinstance(packets, list) or len(packets) > MAX_TRACE_PACKETS:
        raise ValueError("Upstream delivery trace exceeds the packet count limit.")
    for field in ("packets_generated", "packets_delivered"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Upstream delivery trace has invalid {field}.")
    if payload["packets_delivered"] != len(packets) or payload["packets_generated"] < len(packets):
        raise ValueError("Upstream delivery trace count differs from its completed summary.")
    previous = -1.0
    seen = set()
    normalized = []
    for packet in packets:
        if not isinstance(packet, dict) or set(packet) != {"packet_id", "delivered_s"}:
            raise ValueError("Upstream delivery trace has an invalid packet record.")
        identity = packet["packet_id"]
        if isinstance(identity, bool) or not isinstance(identity, int) or identity < 1 or identity in seen:
            raise ValueError("Upstream delivery trace has duplicate or invalid packet identity.")
        at = _finite_time(packet["delivered_s"], "packet timestamp")
        if at < previous or at > simulation_end:
            raise ValueError("Upstream delivery trace timestamps are unordered or outside their horizon.")
        normalized.append({"packet_id": identity, "delivered_s": at})
        previous = at
        seen.add(identity)
    receipt.update(
        source_packet_count=len(normalized), simulation_horizon_s=simulation_end,
        source_emission_horizon_s=source_end, scheduled_packets=[],
    )
    return normalized, receipt
