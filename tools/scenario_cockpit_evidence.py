#!/usr/bin/env python3
"""Generate real UAV queue evidence for the Scenario Cockpit page."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
UAV_QUEUE_APP_ROOT = REPO_ROOT / "src" / "agilab" / "apps" / "builtin" / "uav_queue_project"
SCENARIO_COCKPIT_SRC = (
    REPO_ROOT
    / "src"
    / "agilab"
    / "apps-pages"
    / "view_scenario_cockpit"
    / "src"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "scenario-cockpit-proof"
SCHEMA = "agilab.scenario_cockpit_source_proof.v1"
POLICIES = ("shortest_path", "queue_aware")


for source_path in (
    REPO_ROOT / "src",
    UAV_QUEUE_APP_ROOT / "src",
    SCENARIO_COCKPIT_SRC,
):
    source_text = str(source_path)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)

from uav_queue import UavQueue, UavQueueArgs  # noqa: E402
from uav_queue_worker import UavQueueWorker  # noqa: E402
from view_scenario_cockpit.evidence import (  # noqa: E402
    build_comparison_frame,
    build_evidence_bundle,
    relative_label,
)


def _make_env(root: Path) -> SimpleNamespace:
    root = root.expanduser().resolve()
    share_root = root / "share"
    export_root = root / "export"
    share_root.mkdir(parents=True, exist_ok=True)
    export_root.mkdir(parents=True, exist_ok=True)

    def _resolve_share_path(path: str | Path) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else share_root / candidate

    return SimpleNamespace(
        verbose=0,
        resolve_share_path=_resolve_share_path,
        home_abs=root,
        _is_managed_pc=False,
        AGI_LOCAL_SHARE=str(share_root),
        agi_share_path_abs=share_root,
        agi_share_path=share_root,
        AGILAB_EXPORT_ABS=export_root,
        target="uav_queue",
    )


def _run_policy(policy: str, env: SimpleNamespace) -> Path:
    args = UavQueueArgs(routing_policy=policy, reset_target=False)
    manager = UavQueue(env, args=args)
    scenario_path = sorted(manager.args.data_in.glob("*.json"))[0]

    worker = UavQueueWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()
    result = worker.work_pool(str(scenario_path))
    worker.work_done(result)

    stem = str(result["summary_metrics"]["artifact_stem"])
    summary_path = (
        Path(env.AGILAB_EXPORT_ABS)
        / env.target
        / "queue_analysis"
        / stem
        / f"{stem}_summary_metrics.json"
    )
    if not summary_path.is_file():
        raise FileNotFoundError(f"UAV queue worker did not write summary metrics: {summary_path}")
    return summary_path


def _artifact_records(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for artifact in bundle["artifacts"]:
        records.append(
            {
                "relative_path": artifact["relative_path"],
                "exists": bool(artifact["exists"]),
                "bytes": int(artifact.get("bytes", 0)),
                "sha256": str(artifact.get("sha256", "")),
            }
        )
    return sorted(records, key=lambda record: record["relative_path"])


def _normalized_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": bundle["schema"],
        "source_page": bundle["source_page"],
        "baseline_run": bundle["baseline_run"],
        "candidate_run": bundle["candidate_run"],
        "gate": bundle["gate"],
        "selected_runs": bundle["selected_runs"],
        "artifacts": _artifact_records(bundle),
    }


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_source_proof(output_dir: Path = DEFAULT_OUTPUT_DIR, *, clean: bool = False) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    env = _make_env(output_dir)
    summary_paths = [_run_policy(policy, env) for policy in POLICIES]
    artifact_root = Path(env.AGILAB_EXPORT_ABS) / env.target / "queue_analysis"
    selected_paths = {relative_label(path, artifact_root): path for path in summary_paths}
    baseline_label = next(label for label in selected_paths if "shortest_path" in label)
    candidate_label = next(label for label in selected_paths if "queue_aware" in label)
    ordered_paths = {
        baseline_label: selected_paths[baseline_label],
        candidate_label: selected_paths[candidate_label],
    }

    comparison_df = build_comparison_frame(ordered_paths, artifact_root, baseline_label)
    bundle = build_evidence_bundle(
        selected_paths=ordered_paths,
        artifact_root=artifact_root,
        comparison_df=comparison_df,
        baseline_label=baseline_label,
        candidate_label=candidate_label,
    )
    normalized_bundle = _normalized_bundle(bundle)
    artifacts = normalized_bundle["artifacts"]
    missing_artifact_count = sum(1 for artifact in artifacts if not artifact["exists"])

    return {
        "schema": SCHEMA,
        "producer": "tools/scenario_cockpit_evidence.py",
        "app_project": "uav_queue_project",
        "page_bundle": "view_scenario_cockpit",
        "execution": {
            "mode": "real_uav_queue_worker_execution",
            "policies": list(POLICIES),
            "random_seed": 2026,
            "source_scenario": (
                "src/agilab/apps/builtin/uav_queue_project/"
                "src/uav_queue/sample_data/uav_queue_hotspot.json"
            ),
            "artifact_root": "$OUTPUT_DIR/export/uav_queue/queue_analysis",
        },
        "baseline_run": baseline_label,
        "candidate_run": candidate_label,
        "gate": normalized_bundle["gate"],
        "selected_runs": normalized_bundle["selected_runs"],
        "artifact_summary": {
            "artifact_count": len(artifacts),
            "hashed_artifact_count": sum(1 for artifact in artifacts if artifact["sha256"]),
            "missing_artifact_count": missing_artifact_count,
            "total_bytes": sum(int(artifact["bytes"]) for artifact in artifacts),
        },
        "artifacts": artifacts,
        "normalized_bundle_sha256": _sha256_json(normalized_bundle),
        "rerun_command": (
            "uv --preview-features extra-build-dependencies run python "
            "tools/scenario_cockpit_evidence.py "
            "--output-dir build/scenario-cockpit-proof --clean "
            "--write-doc-sample docs/source/data/scenario_cockpit_uav_queue_sample.json"
        ),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the real UAV queue worker twice and emit Scenario Cockpit proof evidence."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory used for generated share/export artifacts.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path for the full proof JSON. Defaults to <output-dir>/scenario_cockpit_source_proof.json.",
    )
    parser.add_argument(
        "--write-doc-sample",
        type=Path,
        default=None,
        help="Optional checked-in sample path to update, usually docs/source/data/scenario_cockpit_uav_queue_sample.json.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete the output directory before generating evidence.",
    )
    args = parser.parse_args(argv)

    proof = build_source_proof(args.output_dir, clean=args.clean)
    output_json = args.output_json or args.output_dir / "scenario_cockpit_source_proof.json"
    write_json(output_json, proof)
    if args.write_doc_sample is not None:
        write_json(args.write_doc_sample, proof)

    print(json.dumps({"path": str(output_json), "gate": proof["gate"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
