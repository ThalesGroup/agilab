from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence


EXAMPLE_DIR = Path(__file__).resolve().parent
CONTRACT_PATH = EXAMPLE_DIR / "parallel_stage.toml"
DEFAULT_OUTPUT_PATH = Path.home() / "log" / "execute" / "parallel_stage" / "parallel_stage_preview.json"
SCHEMA = "agilab.example.parallel_stage.preview.v1"
CONTRACT_SCHEMA = "agilab.parallel_stage.v1"


def load_contract(path: Path) -> dict[str, Any]:
    with path.expanduser().open("rb") as stream:
        payload = tomllib.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a TOML table")
    return payload


def _requested_workers(contract: Mapping[str, Any], available_cores: int) -> int:
    configured = contract.get("workers")
    if configured == "auto":
        return available_cores
    if not isinstance(configured, int) or configured < 1:
        raise ValueError("workers must be a positive integer or 'auto'")
    return configured


def effective_workers(
    *,
    file_count: int,
    requested_workers: int,
    files_are_splittable: bool,
) -> int:
    if file_count < 1:
        return 1
    if file_count >= requested_workers:
        return requested_workers
    if files_are_splittable:
        return requested_workers
    return file_count


def planned_partitions(
    *,
    contract: Mapping[str, Any],
    file_count: int,
    requested_workers: int,
    files_are_splittable: bool,
) -> int:
    if file_count < 1:
        return 1
    if not files_are_splittable:
        return file_count
    strategy = str(contract.get("partition_strategy", "one-file-per-partition"))
    if strategy not in {"file-chunks", "row-chunks"}:
        return file_count
    target = int(contract.get("target_partitions", 0) or 0)
    min_per_worker = int(contract.get("min_partitions_per_worker", 2) or 2)
    return max(file_count, target, requested_workers * min_per_worker)


def validate_contract(contract: Mapping[str, Any]) -> tuple[str, ...]:
    issues: list[str] = []
    required = (
        "schema",
        "name",
        "function",
        "split",
        "input",
        "workers",
        "partition_strategy",
        "target_partitions",
        "min_partitions_per_worker",
        "reducer",
        "backend",
        "output",
    )
    for key in required:
        if key not in contract:
            issues.append(f"missing required key: {key}")
    if contract.get("schema") != CONTRACT_SCHEMA:
        issues.append(f"schema must be {CONTRACT_SCHEMA}")
    if contract.get("split") != "files":
        issues.append("this preview expects split = files")
    if contract.get("partition_strategy") not in {"file-chunks", "row-chunks"}:
        issues.append("low-file-count scaling needs a chunking partition_strategy")
    if not isinstance(contract.get("target_partitions"), int) or int(contract.get("target_partitions", 0)) < 1:
        issues.append("target_partitions must be a positive integer for chunked file parallelism")
    return tuple(issues)


def build_preview(
    *,
    contract_path: Path = CONTRACT_PATH,
    output_path: Path | None = DEFAULT_OUTPUT_PATH,
    available_cores: int = 8,
    file_count: int = 3,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    issues = validate_contract(contract)
    requested_workers = _requested_workers(contract, available_cores)
    splittable_workers = effective_workers(
        file_count=file_count,
        requested_workers=requested_workers,
        files_are_splittable=True,
    )
    unsplittable_workers = effective_workers(
        file_count=file_count,
        requested_workers=requested_workers,
        files_are_splittable=False,
    )
    splittable_partitions = planned_partitions(
        contract=contract,
        file_count=file_count,
        requested_workers=requested_workers,
        files_are_splittable=True,
    )
    unsplittable_partitions = planned_partitions(
        contract=contract,
        file_count=file_count,
        requested_workers=requested_workers,
        files_are_splittable=False,
    )
    preview = {
        "schema": SCHEMA,
        "example": "parallel_stage",
        "goal": "Show that AGILAB parallelizes partitions, not raw file count.",
        "contract_path": str(contract_path),
        "contract_valid": not issues,
        "contract_issues": list(issues),
        "contract": {
            "name": contract.get("name"),
            "function": contract.get("function"),
            "split": contract.get("split"),
            "workers": contract.get("workers"),
            "partition_strategy": contract.get("partition_strategy"),
            "target_partitions": contract.get("target_partitions"),
            "min_partitions_per_worker": contract.get("min_partitions_per_worker"),
            "reducer": contract.get("reducer"),
            "backend": contract.get("backend"),
        },
        "low_file_count_policy": {
            "file_count": file_count,
            "available_cores": available_cores,
            "requested_workers": requested_workers,
            "splittable_large_files": {
                "effective_workers": splittable_workers,
                "planned_partitions": splittable_partitions,
                "rule": "split files into chunks until target_partitions or worker balance is reached",
            },
            "unsplittable_small_files": {
                "effective_workers": unsplittable_workers,
                "planned_partitions": unsplittable_partitions,
                "rule": "cap useful workers to file_count",
            },
        },
        "recommended_sequence": [
            "preview one partition locally",
            "verify artifact paths and return values",
            "verify reducer output",
            "switch backend from local to pool or dask only after the local contract passes",
        ],
    }
    if output_path is not None:
        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return preview


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview AGILAB parallel-stage partition planning.")
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--no-output", action="store_true", help="Print only; do not write preview JSON.")
    parser.add_argument("--available-cores", type=int, default=8)
    parser.add_argument("--file-count", type=int, default=3)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    preview = build_preview(
        contract_path=args.contract.expanduser(),
        output_path=None if args.no_output else args.output,
        available_cores=args.available_cores,
        file_count=args.file_count,
    )
    print(json.dumps(preview, indent=2, sort_keys=True))
    return preview


if __name__ == "__main__":
    main()
