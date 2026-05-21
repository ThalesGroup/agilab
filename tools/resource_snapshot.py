#!/usr/bin/env python3
"""Write a local resource snapshot for agent and workflow evidence."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "agilab.resource_snapshot.v1"


def _bytes_to_gb(value: int | float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / (1024**3), 3)


def detect_memory_bytes() -> dict[str, int | None]:
    if hasattr(os, "sysconf"):
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            total_pages = int(os.sysconf("SC_PHYS_PAGES"))
            available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
            return {
                "total": page_size * total_pages,
                "available": page_size * available_pages,
            }
        except (OSError, ValueError):
            pass
    return {"total": None, "available": None}


def detect_nvidia_gpus() -> list[dict[str, Any]]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=5, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    gpus: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        name, _, memory_mb = line.partition(",")
        try:
            memory_gb = round(float(memory_mb.strip()) / 1024, 3)
        except ValueError:
            memory_gb = None
        gpus.append({"name": name.strip(), "memory_gb": memory_gb, "backend": "cuda"})
    return gpus


def detect_gpu() -> dict[str, Any]:
    nvidia = detect_nvidia_gpus()
    apple_silicon = (
        platform.system() == "Darwin"
        and platform.machine().lower() in {"arm64", "aarch64"}
    )
    backends = []
    if nvidia:
        backends.append("cuda")
    if apple_silicon:
        backends.append("metal")
    return {
        "nvidia": nvidia,
        "apple_silicon": apple_silicon,
        "available_backends": backends,
        "total_gpus": len(nvidia) + (1 if apple_silicon else 0),
    }


def recommendations(snapshot: dict[str, Any]) -> dict[str, Any]:
    cpu_count = snapshot["cpu"]["logical_cores"] or 1
    available_gb = snapshot["memory"]["available_gb"]
    disk_available_gb = snapshot["disk"]["available_gb"]
    suggested_workers = max(1, int(cpu_count) - 1)
    if cpu_count >= 8:
        parallel_strategy = "high_parallelism"
    elif cpu_count >= 4:
        parallel_strategy = "moderate_parallelism"
    else:
        parallel_strategy = "sequential_default"

    if available_gb is None:
        memory_strategy = "unknown_memory"
    elif available_gb < 4:
        memory_strategy = "memory_constrained"
    elif available_gb < 16:
        memory_strategy = "chunk_large_data"
    else:
        memory_strategy = "in_memory_ok_for_moderate_data"

    if disk_available_gb is None:
        disk_strategy = "unknown_disk"
    elif disk_available_gb < 10:
        disk_strategy = "avoid_large_intermediates"
    elif disk_available_gb < 100:
        disk_strategy = "watch_intermediate_size"
    else:
        disk_strategy = "disk_ok_for_artifacts"

    return {
        "parallel_processing": {
            "strategy": parallel_strategy,
            "suggested_workers": suggested_workers,
            "libraries": ["joblib", "multiprocessing", "dask"],
        },
        "memory_strategy": {
            "strategy": memory_strategy,
            "libraries": ["dask", "zarr", "parquet"],
        },
        "gpu_acceleration": {
            "available": bool(snapshot["gpu"]["available_backends"]),
            "backends": snapshot["gpu"]["available_backends"],
            "libraries": ["pytorch", "jax", "tensorflow"],
        },
        "artifact_storage": {
            "strategy": disk_strategy,
        },
    }


def build_snapshot(workdir: Path) -> dict[str, Any]:
    memory = detect_memory_bytes()
    disk = shutil.disk_usage(workdir)
    snapshot: dict[str, Any] = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workdir": str(workdir.resolve()),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
        },
        "cpu": {
            "logical_cores": os.cpu_count(),
        },
        "memory": {
            "total_gb": _bytes_to_gb(memory["total"]),
            "available_gb": _bytes_to_gb(memory["available"]),
        },
        "disk": {
            "total_gb": _bytes_to_gb(disk.total),
            "available_gb": _bytes_to_gb(disk.free),
        },
        "gpu": detect_gpu(),
    }
    snapshot["recommendations"] = recommendations(snapshot)
    return snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("resource_snapshot.json"))
    parser.add_argument("--json", action="store_true", help="Print the snapshot JSON to stdout.")
    parser.add_argument("--compact", action="store_true", help="Write compact JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    snapshot = build_snapshot(args.workdir)
    indent = None if args.compact else 2
    text = json.dumps(snapshot, indent=indent, sort_keys=True) + "\n"
    args.output.write_text(text, encoding="utf-8")
    if args.json:
        print(text, end="")
    else:
        print(f"resource snapshot -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
