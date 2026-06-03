from __future__ import annotations

import json
import importlib.util
from pathlib import Path


SAMPLE_PATH = Path("docs/source/data/scenario_cockpit_uav_queue_sample.json")
TOOL_PATH = Path("tools/scenario_cockpit_evidence.py")


def _load_tool():
    spec = importlib.util.spec_from_file_location("scenario_cockpit_evidence_tool", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scenario_cockpit_evidence_runs_real_uav_queue_worker(tmp_path: Path) -> None:
    tool = _load_tool()
    proof = tool.build_source_proof(tmp_path / "scenario-cockpit-proof", clean=True)

    assert proof["schema"] == tool.SCHEMA
    assert proof["execution"]["mode"] == "real_uav_queue_worker_execution"
    assert proof["gate"]["status"] == "promotable"
    assert proof["artifact_summary"]["missing_artifact_count"] == 0
    assert proof["artifact_summary"]["hashed_artifact_count"] == proof["artifact_summary"]["artifact_count"]
    assert len(proof["normalized_bundle_sha256"]) == 64

    by_policy = {row["routing_policy"]: row for row in proof["selected_runs"]}
    assert by_policy["queue_aware"]["pdr"] > by_policy["shortest_path"]["pdr"]
    assert by_policy["queue_aware"]["mean_e2e_delay_ms"] < by_policy["shortest_path"]["mean_e2e_delay_ms"]


def test_scenario_cockpit_doc_sample_matches_current_real_worker_output(tmp_path: Path) -> None:
    tool = _load_tool()
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    proof = tool.build_source_proof(tmp_path / "scenario-cockpit-proof", clean=True)

    assert proof == sample
