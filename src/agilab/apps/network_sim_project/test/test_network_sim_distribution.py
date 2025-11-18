import json
import sys
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

script_path = Path(__file__).resolve()
active_app_path = script_path.parents[1]
src_path = active_app_path / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from network_sim.network_sim import NetworkSimApp, NetworkSimArgs  # noqa: E402


class DummyEnv:
    def __init__(self):
        self._is_managed_pc = False


def _create_flow_dataset(root: Path) -> None:
    flows_dir = root / "flows" / "traffic_df" / "RouteID=0"
    flows_dir.mkdir(parents=True, exist_ok=True)
    nodes_meta = {"0": "10.0.0.1", "1": "10.0.0.2"}
    (root / "flows" / "nodes_ip.json").write_text(json.dumps(nodes_meta), encoding="utf-8")

    graph = nx.MultiDiGraph()
    graph.add_node(0, label="plane_0", type="ngf")
    graph.add_node(1, label="plane_1", type="ngf")
    nx.write_gml(graph, root / "flows" / "topology.json")

    frame = pd.DataFrame(
        {
            "FlowID": ["f0", "f0", "f1"],
            "SrcID": [0, 0, 1],
            "DstID": [1, 1, 0],
            "bandwidth": [10.0, 12.0, 8.0],
            "latency": [0.5, 0.7, 0.9],
        }
    )
    frame.to_parquet(flows_dir / "part.0.parquet", index=False)


def _create_link_outputs(root: Path) -> None:
    link_dir = root / "link_insights"
    link_dir.mkdir(parents=True, exist_ok=True)

    forward_payload = [
        {
            "antenna_0": {
                "plane_1_signal": {
                    "Shannon_capacity_Mbps": 5_000,
                    "lag_ms": 60,
                    "SNR": 25,
                }
            }
        }
    ]
    backward_payload = [
        {
            "antenna_0": {
                "plane_0_signal": {
                    "Shannon_capacity_Mbps": 4_500,
                    "lag_ms": 40,
                    "SNR": 18,
                }
            }
        }
    ]
    (link_dir / "plane_0_vision.json").write_text(json.dumps(forward_payload), encoding="utf-8")
    (link_dir / "plane_1_vision.json").write_text(json.dumps(backward_payload), encoding="utf-8")


def test_simulate_builds_ilp_dataset(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    _create_flow_dataset(dataset_root)
    _create_link_outputs(dataset_root)

    args = NetworkSimArgs(
        data_source="file",
        data_in=dataset_root,
        flows_dir="flows",
        link_results_dir="link_insights",
        topology_filename="network.gml",
        summary_filename="summary.json",
        demands_filename="demands.json",
    )
    app = NetworkSimApp(env=DummyEnv(), args=args)
    summary = app.simulate()

    assert (dataset_root / "network.gml").exists()
    assert (dataset_root / "demands.json").exists()
    assert summary["nodes"] == 2
    assert summary["edges"] == 2
    assert summary["flows"] == 2

    demands = json.loads((dataset_root / "demands.json").read_text(encoding="utf-8"))
    assert {item["flow_id"] for item in demands} == {"f0", "f1"}


def test_simulate_requires_link_data(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    _create_flow_dataset(dataset_root)

    args = NetworkSimArgs(data_source="file", data_in=dataset_root)
    app = NetworkSimApp(env=DummyEnv(), args=args)

    with pytest.raises(FileNotFoundError):
        app.simulate()
