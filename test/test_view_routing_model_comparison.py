from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import math

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "src/agilab/apps-pages/view_routing_model_comparison/src/view_routing_model_comparison/view_routing_model_comparison.py"
)


def _load_module():
    src_path = str((ROOT / "src").resolve())
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    spec = importlib.util.spec_from_file_location(
        "view_routing_model_comparison_test_module",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_routing_model_comparison_parses_allocation_helpers() -> None:
    module = _load_module()

    assert module.safe_bool("yes") is True
    assert module.safe_bool("0") is False
    assert module.safe_bool(None) is None
    assert math.isnan(module.safe_float(None))
    assert module.parse_list_value("[(1, 2), (2, 3)]") == [(1, 2), (2, 3)]
    assert module.parse_list_value("not a literal") == ["not a literal"]
    assert module.is_edge_list_path([(1, 2), (2, 3)])

    routed = {
        "path": "[(1, 2)]",
        "delivered_bandwidth": 5.0,
        "bandwidth": 10.0,
        "bearers": "['SATCOM', 'ivdl']",
    }
    assert module.has_path(routed)
    assert module.is_routed(routed)
    assert module.get_satisfaction(routed) == 0.5
    assert module.hop_count(routed) == 1
    assert module.normalize_bearer("satcom") == "SAT"
    assert module.normalize_bearer("ivdl") == "IVDL"
    assert module.demand_outcome(False, 1.0) == "unrouted"
    assert module.demand_outcome(True, 1.0) == "fulfilled"
    assert module.demand_outcome(True, 0.5) == "partial"


def test_routing_model_comparison_loads_and_summarizes_allocations(tmp_path: Path) -> None:
    module = _load_module()
    base = tmp_path / "pipeline"
    ilp_path = base / "trainer_fcas_routing_ilp" / "allocations_steps.json"
    ppo_path = base / "trainer_fcas_routing_ppo_gnn" / "allocations_steps.json"
    ilp_path.parent.mkdir(parents=True)
    ppo_path.parent.mkdir(parents=True)
    ilp_path.write_text(
        json.dumps(
            [
                {
                    "time_index": 0,
                    "allocations": [
                        {
                            "source_label": "A",
                            "destination_label": "B",
                            "bandwidth": 10.0,
                            "delivered_bandwidth": 10.0,
                            "served_fraction": 1.0,
                            "latency_ms": 20.0,
                            "latency_target_ms": 30.0,
                            "routed": True,
                            "bearers": ["SAT", "IVDL"],
                            "path": [[1, 2], [2, 3]],
                        },
                        {
                            "source": "C",
                            "destination": "D",
                            "bandwidth": 4.0,
                            "delivered_bandwidth": 0.0,
                            "path_found": False,
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    ppo_path.write_text(
        json.dumps(
            [
                {
                    "time_index": 0,
                    "allocations": [
                        {
                            "source_label": "A",
                            "destination_label": "B",
                            "bandwidth": 10.0,
                            "delivered_bandwidth": 5.0,
                            "latency_ms": 45.0,
                            "latency_target_ms": 30.0,
                            "routed": True,
                            "bearers": ["SAT"],
                            "path_labels": ["A", "relay", "B"],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    signatures = module.available_file_signatures(base)
    alloc_df = module.load_allocations(signatures)
    alloc_df = module.add_latency_targets(alloc_df)
    summary = module.build_summary(alloc_df)
    failures = module.build_failure_table(alloc_df)

    assert set(alloc_df["model"]) == {"ILP", "PPO-GNN"}
    assert alloc_df["outcome"].tolist().count("fulfilled") == 1
    assert alloc_df["outcome"].tolist().count("unrouted") == 1
    assert alloc_df["outcome"].tolist().count("partial") == 1
    assert summary.set_index("model").loc["ILP", "routed_count"] == 1
    assert summary.set_index("model").loc["PPO-GNN", "latency_violation_rate"] == 1.0
    assert len(failures) == 2
    assert "latency_over_target_ms" in failures.columns


def test_routing_model_comparison_figures_handle_empty_and_visible_models() -> None:
    module = _load_module()
    alloc_df = pd.DataFrame(
        [
            {
                "model": "ILP",
                "time_index": 0,
                "satisfaction_ratio": 1.0,
                "delivered_mbps": 10.0,
                "latency_ms": 20.0,
                "latency_violation": False,
                "routed": True,
                "outcome": "fulfilled",
                "hop_count": 2,
                "sat_edge_count": 1,
                "ivdl_edge_count": 1,
            },
            {
                "model": "PPO-GNN",
                "time_index": 0,
                "satisfaction_ratio": 0.5,
                "delivered_mbps": 5.0,
                "latency_ms": 45.0,
                "latency_violation": True,
                "routed": True,
                "outcome": "partial",
                "hop_count": 2,
                "sat_edge_count": 1,
                "ivdl_edge_count": 0,
            },
        ]
    )
    summary = pd.DataFrame(
        [
            {
                "model": "ILP",
                "served_bandwidth_ratio": 1.0,
                "mean_latency_ms": 20.0,
                "latency_violation_rate": 0.0,
                "routed_count": 1,
            },
            {
                "model": "PPO-GNN",
                "served_bandwidth_ratio": 0.5,
                "mean_latency_ms": 45.0,
                "latency_violation_rate": 1.0,
                "routed_count": 1,
            },
        ]
    )
    models = ["ILP", "PPO-GNN"]

    assert len(module.build_overview_figure(alloc_df, summary, models).data) >= 4
    assert len(module.build_time_figure(alloc_df, models).data) == 8
    assert len(module.build_path_figure(alloc_df, models).data) >= 2
    assert module._format_summary(summary).columns.tolist() == models
