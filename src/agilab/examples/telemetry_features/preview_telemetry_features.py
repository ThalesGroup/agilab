# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#   "featuretools==1.31.0",
#   "pandas==2.3.3",
#   "woodwork==0.31.0",
#   "setuptools==80.9.0",
# ]
# ///
"""Compute a small telemetry feature bundle; verify it without optional imports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "agilab.feature-evidence.v1"
DEFAULT_CUTOFF = "2026-01-01T00:10:00Z"
ARTIFACTS = (
    "assets.csv",
    "samples.csv",
    "feature_plan.json",
    "feature_definitions.json",
    "feature_matrix.csv",
    "feature_lineage.json",
    "feature_lineage.md",
)
RUNTIME_PACKAGES = (
    "featuretools",
    "pandas",
    "woodwork",
    "numpy",
    "scipy",
    "scikit-learn",
    "setuptools",
)
PRIMITIVES = {
    "Count": "featuretools.primitives.standard.aggregation.count",
    "Max": "featuretools.primitives.standard.aggregation.max_primitive",
    "Mean": "featuretools.primitives.standard.aggregation.mean",
}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(data: bytes) -> dict[str, Any]:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def _adapter():
    try:
        import featuretools as ft
        import pandas as pd
    except ImportError as exc:
        raise ValueError(
            "Feature generation/replay requires the optional pinned environment. "
            "Run `uv run --script preview_telemetry_features.py --help` from this "
            "example directory to prepare it; see README.md."
        ) from exc
    return ft, pd


def _runtime() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name) for name in RUNTIME_PACKAGES
        },
    }


def _utc(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError(
            "cutoff must include a timezone, for example 2026-01-01T00:10:00Z"
        )
    return stamp.astimezone(timezone.utc)


def feature_plan(
    cutoff: str = DEFAULT_CUTOFF, window_minutes: int = 5
) -> dict[str, Any]:
    if type(window_minutes) is not int or not 1 <= window_minutes <= 60:
        raise ValueError("window_minutes must be an integer between 1 and 60")
    return {
        "kind": "feature-plan",
        "version": 1,
        "entityset": "telemetry",
        "target_dataframe": "assets",
        "tables": {
            "assets": {"index": "asset_id", "columns": {"asset_id": "Categorical"}},
            "samples": {
                "index": "sample_id",
                "time_index": "available_at",
                "columns": {
                    "sample_id": "Integer",
                    "asset_id": "Categorical",
                    "available_at": "Datetime",
                    "observed_at": "Datetime",
                    "latency_ms": "Double",
                },
            },
        },
        "relationship": ["assets", "asset_id", "samples", "asset_id"],
        "cutoff_time": _utc(cutoff).isoformat().replace("+00:00", "Z"),
        "timezone": "UTC",
        "training_window_minutes": window_minutes,
        "include_cutoff_time": False,
        "agg_primitives": ["count", "max", "mean"],
        "trans_primitives": [],
        "max_depth": 1,
        "max_features": 3,
        "ignored_columns": {"samples": ["observed_at"]},
        "time_semantics": "available_at is when this immutable observation became known",
    }


def _csv_bytes(columns: list[str], rows: list[list[Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def fixture_tables() -> dict[str, bytes]:
    """Two assets; include old, boundary, cutoff, and late-arriving observations."""
    rows = []
    for asset, multiplier in [("node-a", 1), ("node-b", 2)]:
        for observed, available, latency in [
            (1, 1, 999),
            (5, 5, 10),
            (7, 7, 20),
            (9, 9, 30),
            (10, 10, 100),
            (6, 11, 50),
        ]:
            rows.append(
                [
                    len(rows) + 1,
                    asset,
                    f"2026-01-01T00:{available:02d}:00Z",
                    f"2026-01-01T00:{observed:02d}:00Z",
                    latency * multiplier,
                ]
            )
    return {
        "assets.csv": _csv_bytes(["asset_id"], [["node-a"], ["node-b"]]),
        "samples.csv": _csv_bytes(
            ["sample_id", "asset_id", "available_at", "observed_at", "latency_ms"],
            rows,
        ),
    }


def _entityset(tables: dict[str, bytes], plan: dict[str, Any], ft, pd):
    es = ft.EntitySet(id=plan["entityset"])
    for name, spec in plan["tables"].items():
        frame = pd.read_csv(io.BytesIO(tables[f"{name}.csv"]))
        for column, logical_type in spec["columns"].items():
            if logical_type == "Datetime":
                frame[column] = pd.to_datetime(frame[column], utc=True).dt.tz_localize(
                    None
                )
        es = es.add_dataframe(
            dataframe_name=name,
            dataframe=frame,
            index=spec["index"],
            time_index=spec.get("time_index"),
            logical_types=spec["columns"],
        )
    es = es.add_relationship(*plan["relationship"])
    es.add_last_time_indexes()
    return es


def _synthesize(es, plan: dict[str, Any], ft):
    return ft.dfs(
        entityset=es,
        target_dataframe_name=plan["target_dataframe"],
        agg_primitives=plan["agg_primitives"],
        trans_primitives=plan["trans_primitives"],
        max_depth=plan["max_depth"],
        max_features=plan["max_features"],
        ignore_columns=plan["ignored_columns"],
        features_only=True,
    )


def _calculate(es, definitions, plan: dict[str, Any], ft, pd) -> bytes:
    matrix = (
        ft.calculate_feature_matrix(
            definitions,
            entityset=es,
            cutoff_time=pd.Timestamp(plan["cutoff_time"]).tz_convert(None),
            training_window=f"{plan['training_window_minutes']} minutes",
            include_cutoff_time=plan["include_cutoff_time"],
            n_jobs=1,
        )
        .sort_index()
        .sort_index(axis=1)
    )
    return matrix.to_csv(
        lineterminator="\n", float_format="%.12g", na_rep="NaN"
    ).encode("utf-8")


def _load_definitions(data: bytes, ft):
    """Only this example's standard primitives may be deserialized."""
    saved = _read_json(data)
    primitives = saved.get("primitive_definitions", {})
    if not isinstance(primitives, dict) or not primitives:
        raise ValueError("Saved definitions contain no primitives")
    for primitive in primitives.values():
        if not isinstance(primitive, dict):
            raise ValueError("Saved definitions contain an invalid primitive")
        name = primitive.get("type")
        if name not in PRIMITIVES or primitive != {
            "type": name,
            "module": PRIMITIVES.get(name),
            "arguments": {},
        }:
            raise ValueError("Saved definitions contain an unsupported primitive")
    features = saved.get("feature_definitions")
    if not isinstance(features, dict) or not features:
        raise ValueError("Saved definitions contain no features")
    if any(
        not isinstance(item, dict)
        or item.get("type") not in {"AggregationFeature", "IdentityFeature"}
        for item in features.values()
    ):
        raise ValueError("Saved definitions contain an unsupported feature type")
    return ft.load_features(io.StringIO(data.decode("utf-8")))


def _lineage(definitions, plan: dict[str, Any], ft) -> tuple[bytes, bytes]:
    features = [
        {
            "name": feature.get_name(),
            "description": ft.describe_feature(feature),
            "primitive": feature.primitive.name,
            "dependencies": sorted(
                f"{dependency.dataframe_name}.{dependency.get_name()}"
                for dependency in feature.get_dependencies(deep=True)
            ),
        }
        for feature in sorted(definitions, key=lambda item: item.get_name())
    ]
    lineage = {
        "kind": "feature-lineage",
        "version": 1,
        "features": features,
        "relationship": plan["relationship"],
        "cutoff_time": plan["cutoff_time"],
        "training_window_minutes": plan["training_window_minutes"],
        "include_cutoff_time": plan["include_cutoff_time"],
    }
    lines = [
        "# Telemetry feature lineage",
        "",
        f"Cutoff: {plan['cutoff_time']} (excluded).",
        f"History: {plan['training_window_minutes']} minutes; lower boundary included.",
        "Time is based on information availability, not observation time.",
        "",
    ]
    for feature in features:
        lines += [
            f"## {feature['name']}",
            "",
            feature["description"],
            "",
            "Inputs: " + ", ".join(feature["dependencies"]),
            "",
        ]
    return _json_bytes(lineage), ("\n".join(lines) + "\n").encode("utf-8")


def build_preview(
    output_dir: Path, *, cutoff: str = DEFAULT_CUTOFF, window_minutes: int = 5
) -> dict[str, Any]:
    """Publish a complete bundle into a new directory; never overwrite a run."""
    output_dir = Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError(
            f"Output already exists: {output_dir}. Choose a new run directory."
        )
    plan = feature_plan(cutoff, window_minutes)
    ft, pd = _adapter()
    tables = fixture_tables()
    es = _entityset(tables, plan, ft, pd)
    definitions = _synthesize(es, plan, ft)
    saved = ft.save_features(definitions).encode("utf-8")
    # Calculate from the serialized definition, exactly as inference/replay will.
    definitions = _load_definitions(saved, ft)
    lineage_json, lineage_md = _lineage(definitions, plan, ft)
    payloads = {
        **tables,
        "feature_plan.json": _json_bytes(plan),
        "feature_definitions.json": saved,
        "feature_matrix.csv": _calculate(es, definitions, plan, ft, pd),
        "feature_lineage.json": lineage_json,
        "feature_lineage.md": lineage_md,
    }
    inventory = {
        name: {"size_bytes": len(data), "sha256": _digest(data)}
        for name, data in sorted(payloads.items())
    }
    manifest = {
        "schema": SCHEMA,
        "status": "passed",
        "artifact_root": ".",
        "run_id": _digest(_json_bytes(inventory)),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "producer": {
            "name": "preview_telemetry_features.py",
            "version": 1,
            "sha256": _digest(Path(__file__).read_bytes()),
            "command": [
                "uv",
                "run",
                "--script",
                "preview_telemetry_features.py",
                "--output-dir",
                "NEW_BUNDLE",
                "--cutoff",
                plan["cutoff_time"],
                "--window-minutes",
                str(window_minutes),
            ],
        },
        "runtime": _runtime(),
        "artifacts": inventory,
        "target": {
            "dataframe": "assets",
            "cutoff_time": plan["cutoff_time"],
            "synthetic_data": True,
            "worker_execution": "not_requested",
        },
        "checks": {
            "generation": "passed",
            "artifact_integrity": "not_run",
            "replay": "not_run",
        },
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".telemetry-features-", dir=output_dir.parent
    ) as temporary:
        bundle = Path(temporary) / "bundle"
        bundle.mkdir()
        for name, data in payloads.items():
            (bundle / name).write_bytes(data)
        (bundle / "feature_manifest.json").write_bytes(_json_bytes(manifest))
        bundle.rename(output_dir)
    return manifest


def verify_evidence(output_dir: Path, *, replay: bool = False) -> dict[str, Any]:
    """Read-only verification; consume the bytes that were actually hash-checked."""
    root = Path(output_dir)
    manifest_path = root / "feature_manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Manifest must be a regular file, not a symlink")
    manifest = _read_json(manifest_path.read_bytes())
    if manifest.get("schema") != SCHEMA or manifest.get("status") != "passed":
        raise ValueError("Unsupported or unsuccessful feature manifest")
    inventory = manifest.get("artifacts", {})
    if manifest.get("artifact_root") != "." or set(inventory) != set(ARTIFACTS):
        raise ValueError(
            "Manifest artifact inventory must contain exactly the documented relative paths"
        )
    payloads = {}
    for name in ARTIFACTS:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or non-regular artifact: {name}")
        data = path.read_bytes()
        if inventory[name] != {"size_bytes": len(data), "sha256": _digest(data)}:
            raise ValueError(f"Artifact hash/size mismatch: {name}")
        payloads[name] = data
    if manifest.get("run_id") != _digest(_json_bytes(inventory)):
        raise ValueError("Run id does not match the artifact inventory")
    plan = _read_json(payloads["feature_plan.json"])
    if plan != feature_plan(plan["cutoff_time"], plan["training_window_minutes"]):
        raise ValueError("Unsupported feature plan")
    report = {
        "schema": SCHEMA,
        "run_id": manifest["run_id"],
        "status": "passed",
        "artifact_integrity": "passed",
        "replay": "not_run",
    }
    if replay:
        ft, pd = _adapter()
        if manifest.get("runtime") != _runtime():
            raise ValueError(
                "Runtime version mismatch. Recreate the versions in feature_manifest.json."
            )
        if manifest["producer"]["sha256"] != _digest(Path(__file__).read_bytes()):
            raise ValueError(
                "Producer source changed; replay with the recorded producer revision."
            )
        es = _entityset(payloads, plan, ft, pd)
        definitions = _load_definitions(payloads["feature_definitions.json"], ft)
        if _calculate(es, definitions, plan, ft, pd) != payloads["feature_matrix.csv"]:
            raise ValueError(
                "Replay mismatch: saved definitions did not reproduce feature_matrix.csv"
            )
        lineage = _lineage(definitions, plan, ft)
        if lineage != (
            payloads["feature_lineage.json"],
            payloads["feature_lineage.md"],
        ):
            raise ValueError(
                "Replay mismatch: saved definitions did not reproduce feature lineage"
            )
        report["replay"] = "passed"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("reports/telemetry-features")
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--verify", action="store_true", help="Check hashes without Featuretools"
    )
    action.add_argument(
        "--replay", action="store_true", help="Verify and recompute saved definitions"
    )
    parser.add_argument(
        "--cutoff", help=f"Generation cutoff (default: {DEFAULT_CUTOFF})"
    )
    parser.add_argument(
        "--window-minutes", type=int, help="Generation history window (default: 5)"
    )
    args = parser.parse_args(argv)
    if (args.verify or args.replay) and (
        args.cutoff is not None or args.window_minutes is not None
    ):
        parser.error(
            "--cutoff and --window-minutes are generation options; replay uses the saved plan"
        )
    try:
        if args.verify or args.replay:
            result = verify_evidence(args.output_dir, replay=args.replay)
        else:
            result = build_preview(
                args.output_dir,
                cutoff=args.cutoff or DEFAULT_CUTOFF,
                window_minutes=5
                if args.window_minutes is None
                else args.window_minutes,
            )
        print(
            json.dumps(
                {key: result[key] for key in ("schema", "run_id", "status")}
                | {
                    "artifact_integrity": result.get("artifact_integrity", "not_run"),
                    "replay": result.get("replay", "not_run"),
                },
                sort_keys=True,
            )
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Telemetry feature evidence: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
