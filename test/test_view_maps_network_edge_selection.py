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


def test_edge_selection_picker_helpers_cover_existing_and_fallback_paths(tmp_path: Path):
    existing_custom = tmp_path / "topology.json"
    existing_custom.write_text("{}", encoding="utf-8")

    custom_state = edge_selection.resolve_edges_picker_state(
        str(existing_custom),
        [],
        current_choice=edge_selection.CUSTOM_OPTION,
        current_custom=str(existing_custom),
    )
    assert custom_state.choice == edge_selection.CUSTOM_OPTION
    assert custom_state.edges_clean == str(existing_custom)
    assert custom_state.recovered_from_missing is False

    none_state = edge_selection.resolve_edges_picker_state(
        "",
        ["/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml"],
        current_choice=edge_selection.NONE_OPTION,
    )
    assert none_state.choice == edge_selection.NONE_OPTION
    assert none_state.edges_clean == ""

    assert edge_selection._path_exists("\0") is False
    assert edge_selection._preferred_recovery_candidate(
        "routing_edges.old",
        [
            "/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml",
            "/Users/agi/clustershare/network_sim/pipeline/routing_edges.jsonl",
        ],
    ) == "/Users/agi/clustershare/network_sim/pipeline/routing_edges.jsonl"
    assert edge_selection._preferred_recovery_candidate(
        "custom-name.json",
        [
            "/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml",
            "/Users/agi/clustershare/network_sim/pipeline/routing_edges.jsonl",
        ],
    ) == "/Users/agi/clustershare/network_sim/pipeline/ilp_topology.gml"


def test_edge_selection_covers_empty_and_existing_path_branches(tmp_path: Path):
    existing_edge_path = tmp_path / "routing_edges.jsonl"
    existing_edge_path.write_text("{}", encoding="utf-8")

    assert edge_selection._path_exists("") is False
    assert edge_selection._preferred_recovery_candidate("missing.json", []) is None
    assert edge_selection._preferred_recovery_candidate(
        "legacy_edges.json",
        [str(existing_edge_path)],
    ) == str(existing_edge_path)

    direct_state = edge_selection.resolve_edges_picker_state(
        str(existing_edge_path),
        [str(existing_edge_path)],
    )
    assert direct_state.choice == str(existing_edge_path)
    assert direct_state.edges_clean == str(existing_edge_path)

    existing_custom_state = edge_selection.resolve_edges_picker_state(
        str(existing_edge_path),
        [],
    )
    assert existing_custom_state.choice == edge_selection.CUSTOM_OPTION
    assert existing_custom_state.custom_value == str(existing_edge_path)
    assert existing_custom_state.edges_clean == str(existing_edge_path)
