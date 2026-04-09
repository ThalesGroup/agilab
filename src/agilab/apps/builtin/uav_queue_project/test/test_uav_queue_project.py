from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import pandas as pd
from agi_node.pandas_worker import PandasWorker


APP_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = APP_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from uav_queue import UavQueue, UavQueueArgs
from uav_queue_worker import UavQueueWorker


def _make_env(tmp_path: Path) -> SimpleNamespace:
    share_root = tmp_path / "share"
    share_root.mkdir(parents=True, exist_ok=True)
    export_root = tmp_path / "export"
    export_root.mkdir(parents=True, exist_ok=True)

    def _resolve_share_path(path):
        candidate = Path(path)
        return candidate if candidate.is_absolute() else share_root / candidate

    return SimpleNamespace(
        verbose=0,
        resolve_share_path=_resolve_share_path,
        home_abs=tmp_path,
        _is_managed_pc=False,
        AGI_LOCAL_SHARE=str(share_root),
        AGILAB_EXPORT_ABS=export_root,
        target="uav_queue",
    )


def test_uav_queue_manager_seeds_dataset_and_distribution(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = UavQueueArgs()
    manager = UavQueue(env, args=args)

    files = sorted(manager.args.data_in.glob("*.json"))
    assert len(files) == 1
    assert files[0].name == "uav_queue_hotspot.json"
    assert manager.analysis_artifact_dir == env.AGILAB_EXPORT_ABS / "uav_queue" / "queue_analysis"

    workers = {"127.0.0.1": 1}
    work_plan, metadata, partition_key, weights_key, unit = manager.build_distribution(workers)

    assert len(work_plan) == 1
    assert len(work_plan[0]) == 1
    assert len(work_plan[0][0]) == 1
    assert partition_key == "scenario"
    assert weights_key == "size_kb"
    assert unit == "KB"
    assert metadata[0][0]["scenario"] == "uav_queue_hotspot.json"


def test_uav_queue_worker_exports_queue_artifacts(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = UavQueueArgs(routing_policy="queue_aware", reset_target=True)
    manager = UavQueue(env, args=args)
    source = sorted(manager.args.data_in.glob("*.json"))[0]

    worker = UavQueueWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()

    result = worker.work_pool(str(source))
    worker.work_done(result)

    result_root = Path(worker.data_out)
    export_root = env.AGILAB_EXPORT_ABS / env.target / "queue_analysis"
    for root in (result_root, export_root):
        summary_files = sorted(root.glob("**/*_summary_metrics.json"))
        assert summary_files
        summary_path = summary_files[0]
        metrics = json.loads(summary_path.read_text(encoding="utf-8"))
        run_root = summary_path.parent
        stem = metrics["artifact_stem"]
        assert metrics["routing_policy"] == "queue_aware"
        assert metrics["packets_generated"] > 0
        assert 0.0 <= metrics["pdr"] <= 1.0
        for suffix in ("packet_events", "queue_timeseries", "node_positions", "routing_summary"):
            assert (run_root / f"{stem}_{suffix}.csv").is_file()
        pipeline_dir = run_root / "pipeline"
        assert (pipeline_dir / "topology.gml").is_file()
        assert (pipeline_dir / "demands.json").is_file()
        assert (pipeline_dir / "allocations_steps.csv").is_file()
        assert (pipeline_dir / "_trajectory_summary.json").is_file()

    metrics = json.loads(next(export_root.glob("**/*_summary_metrics.json")).read_text(encoding="utf-8"))
    stem = metrics["artifact_stem"]
    run_root = export_root / stem
    queue_df = pd.read_csv(run_root / f"{stem}_queue_timeseries.csv")
    packet_df = pd.read_csv(run_root / f"{stem}_packet_events.csv")
    positions_df = pd.read_csv(run_root / f"{stem}_node_positions.csv")
    routing_df = pd.read_csv(run_root / f"{stem}_routing_summary.csv")
    pipeline_dir = run_root / "pipeline"
    topology = nx.read_gml(pipeline_dir / "topology.gml")
    allocations_df = pd.read_csv(pipeline_dir / "allocations_steps.csv")
    trajectory_summary = json.loads((pipeline_dir / "_trajectory_summary.json").read_text(encoding="utf-8"))
    demand_payload = json.loads((pipeline_dir / "demands.json").read_text(encoding="utf-8"))

    assert {"time_s", "relay", "queue_depth_pkts"} <= set(queue_df.columns)
    assert {"packet_id", "origin_kind", "relay", "status"} <= set(packet_df.columns)
    assert {"node", "latitude", "longitude", "alt_m"} <= set(positions_df.columns)
    assert {"relay", "packets_generated", "packets_delivered"} <= set(routing_df.columns)
    assert {"relay_a", "relay_b"} <= set(queue_df["relay"].unique())
    assert (packet_df["origin_kind"] == "source").any()
    assert set(topology.nodes()) == {"uav_source", "relay_a", "relay_b", "ground_sink"}
    assert topology.number_of_edges() == 4
    assert {"time_index", "source", "destination", "path", "bearers"} <= set(allocations_df.columns)
    assert trajectory_summary["planned_trajectories"] == 4
    assert len(trajectory_summary["trajectory_files"]) == 4
    for file_name in trajectory_summary["trajectory_files"]:
        trajectory_df = pd.read_csv(pipeline_dir / file_name)
        assert {"time_s", "node_id", "latitude", "longitude", "alt_m"} <= set(trajectory_df.columns)
    assert demand_payload and demand_payload[0]["source"] == "uav_source"
    assert demand_payload[0]["destination"] == "ground_sink"


def test_uav_queue_worker_is_installable_supported_worker() -> None:
    assert issubclass(UavQueueWorker, PandasWorker)


def test_uav_queue_multi_scenario_outputs_do_not_overwrite(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = UavQueueArgs(nfile=2, reset_target=True)
    manager = UavQueue(env, args=args)
    source = sorted(manager.args.data_in.glob("*.json"))[0]
    variant = json.loads(source.read_text(encoding="utf-8"))
    variant["scenario"] = "uav_queue_hotspot_b"
    variant_path = manager.args.data_in / "uav_queue_hotspot_b.json"
    variant_path.write_text(json.dumps(variant, indent=2), encoding="utf-8")

    work_plan, metadata, partition_key, weights_key, unit = manager.build_distribution({"127.0.0.1": 2})

    assert len(work_plan) == 2
    assert [entry[0]["scenario"] for entry in metadata] == [
        "uav_queue_hotspot.json",
        "uav_queue_hotspot_b.json",
    ]
    assert partition_key == "scenario"
    assert weights_key == "size_kb"
    assert unit == "KB"

    worker = UavQueueWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()

    for path in sorted(manager.args.data_in.glob("*.json")):
        result = worker.work_pool(str(path))
        worker.work_done(result)

    export_root = env.AGILAB_EXPORT_ABS / env.target / "queue_analysis"
    summary_paths = sorted(export_root.glob("**/*_summary_metrics.json"))

    assert len(summary_paths) == 2
    scenario_by_run = {}
    for summary_path in summary_paths:
        metrics = json.loads(summary_path.read_text(encoding="utf-8"))
        run_root = summary_path.parent
        pipeline_dir = run_root / "pipeline"
        scenario_by_run[metrics["artifact_stem"]] = json.loads(
            (pipeline_dir / "_trajectory_summary.json").read_text(encoding="utf-8")
        )["scenario"]
        assert (pipeline_dir / "topology.gml").is_file()
        assert (pipeline_dir / "allocations_steps.csv").is_file()
        assert (pipeline_dir / "demands.json").is_file()

    assert scenario_by_run == {
        "uav_queue_hotspot_shortest_path_seed2026": "uav_queue_hotspot",
        "uav_queue_hotspot_b_shortest_path_seed2026": "uav_queue_hotspot_b",
    }


def test_uav_queue_worker_executes_distribution_batches(tmp_path: Path) -> None:
    env = _make_env(tmp_path)
    args = UavQueueArgs(nfile=2, reset_target=True)
    manager = UavQueue(env, args=args)
    source = sorted(manager.args.data_in.glob("*.json"))[0]
    variant = json.loads(source.read_text(encoding="utf-8"))
    variant["scenario"] = "uav_queue_hotspot_b"
    (manager.args.data_in / "uav_queue_hotspot_b.json").write_text(
        json.dumps(variant, indent=2),
        encoding="utf-8",
    )

    work_plan, metadata, _, _, _ = manager.build_distribution({"127.0.0.1": 2})

    worker = UavQueueWorker()
    worker.env = env
    worker.args = manager.args.model_dump(mode="json")
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()

    runtime = worker.works(work_plan, metadata)

    assert runtime >= 0.0
    export_root = env.AGILAB_EXPORT_ABS / env.target / "queue_analysis"
    summary_paths = sorted(export_root.glob("**/*_summary_metrics.json"))
    assert len(summary_paths) == 1
    metrics = json.loads(summary_paths[0].read_text(encoding="utf-8"))
    assert metrics["scenario"] == "uav_queue_hotspot"
