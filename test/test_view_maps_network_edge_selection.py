from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/agilab/apps-pages/view_maps_network/src/view_maps_network/edge_selection.py"
)
SPEC = importlib.util.spec_from_file_location("view_maps_network_edge_selection", MODULE_PATH)
assert SPEC and SPEC.loader
edge_selection = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = edge_selection
SPEC.loader.exec_module(edge_selection)


def test_stale_topology_path_recovers_to_detected_topology_candidate():
    state = edge_selection.resolve_edges_picker_state(
        "network_sim/pipeline/flows/topology.json",
        [
            "/Users/agi/clustershare/sb3_trainer/pipeline/trainer_routing/routing_edges.jsonl",
            "/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml",
        ],
    )

    assert state.choice == "/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml"
    assert state.edges_clean == "/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml"
    assert state.recovered_from_missing is True


def test_missing_custom_path_stays_custom_when_no_candidate_exists():
    state = edge_selection.resolve_edges_picker_state(
        "/missing/custom/topology.json",
        [],
    )

    assert state.choice == edge_selection.CUSTOM_OPTION
    assert state.custom_value == "/missing/custom/topology.json"
    assert state.edges_clean == "/missing/custom/topology.json"
    assert state.recovered_from_missing is False


def test_dead_custom_picker_choice_recovers_to_detected_candidate():
    state = edge_selection.resolve_edges_picker_state(
        "/missing/custom/topology.json",
        [
            "/Users/agi/clustershare/sb3_trainer/pipeline/trainer_routing/routing_edges.jsonl",
            "/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml",
        ],
        current_choice=edge_selection.CUSTOM_OPTION,
        current_custom="/missing/custom/topology.json",
    )

    assert state.choice == "/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml"
    assert state.custom_value == ""
    assert state.edges_clean == "/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml"
    assert state.recovered_from_missing is True
