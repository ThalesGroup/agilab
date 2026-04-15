from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from agi_env import AgiEnv


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py"
)


def _load_view_maps_network_module() -> object:
    spec = importlib.util.spec_from_file_location("view_maps_network_semantic_ids_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    active_app = Path("/Users/agi/PycharmProjects/thales_agilab/apps/sb3_trainer_project")
    argv = [MODULE_PATH.name, "--active-app", str(active_app)]
    AgiEnv.reset()
    with patch("sys.argv", argv):
        spec.loader.exec_module(module)
    return module


def test_view_maps_network_extracts_semantic_node_id_from_label() -> None:
    module = _load_view_maps_network_module()

    assert module._semantic_node_id_from_text("uswc_forward_02-S002") == "2002"
    assert module._semantic_node_id_from_text("SES-10") == "10"
    assert module._semantic_node_id_from_text("NSS-11") == "11"


def test_view_maps_network_prefers_semantic_ids_when_normalizing_rows() -> None:
    module = _load_view_maps_network_module()

    row = pd.Series(
        {
            "plane_id": 1,
            "plane_label": "uswc_forward_02-S002",
            "source_file": "pipeline/uswc_forward_02-S002_2026-04-01_15-27-48.csv",
        }
    )

    assert module._preferred_node_id_from_row(row) == "2002"


def test_view_maps_network_load_positions_prefers_semantic_ids_over_local_plane_counters(
    tmp_path: Path,
) -> None:
    module = _load_view_maps_network_module()

    traj_path = tmp_path / "uswc_forward_03-S003_2026-03-31_15-30-46.csv"
    pd.DataFrame(
        [
            {
                "time_s": 0,
                "plane_id": 2,
                "plane_label": "uswc_forward_03-S003",
                "latitude": 50.0,
                "longitude": 2.0,
                "alt_m": 130.0,
            }
        ]
    ).to_csv(traj_path, index=False)

    positions = module.load_positions_at_time(str(traj_path), 0.0)

    assert not positions.empty
    assert positions.iloc[0]["flight_id"] == "3003"


def test_view_maps_network_build_allocation_layers_resolves_semantic_node_ids() -> None:
    module = _load_view_maps_network_module()

    alloc_df = pd.DataFrame(
        [
            {
                "source": 2002,
                "destination": 10,
                "bandwidth": 0.1,
                "delivered_bandwidth": 0.1,
                "path": [],
                "bearers": ["IVDL"],
            }
        ]
    )
    positions = pd.DataFrame(
        [
            {"flight_id": "2002", "long": 1.0, "lat": 2.0, "alt": 100.0},
            {"flight_id": "10", "long": 3.0, "lat": 4.0, "alt": 200.0},
        ]
    )

    layers = module.build_allocation_layers(alloc_df, positions)

    assert [layer.type for layer in layers] == ["LineLayer"]
    assert layers[0].data[0]["demand"] == "2002→10"
