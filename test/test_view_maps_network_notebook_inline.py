from __future__ import annotations

import importlib.util
from pathlib import Path

import networkx as nx
import pandas as pd


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_maps_network/src/view_maps_network/notebook_inline.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("view_maps_network_notebook_inline_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_view_maps_network_notebook_inline_reports_missing_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    export_dir = tmp_path / "export" / "demo"
    export_dir.mkdir(parents=True, exist_ok=True)

    outputs = module.render_inline(
        page="view_maps_network",
        record={"label": "Maps Network", "artifacts": ["pipeline/topology.gml"]},
        export_payload={"artifact_dir": str(export_dir)},
    )

    assert len(outputs) == 1
    assert "No notebook-native map could be rendered" in outputs[0].data
    assert "pipeline/topology.gml" in outputs[0].data


def test_view_maps_network_notebook_inline_renders_geo_figure_from_export_artifacts(tmp_path: Path) -> None:
    module = _load_module()
    export_dir = tmp_path / "export" / "demo"
    topology_dir = export_dir / "network_sim" / "pipeline"
    trajectory_dir = export_dir / "flight_trajectory" / "pipeline"
    topology_dir.mkdir(parents=True, exist_ok=True)
    trajectory_dir.mkdir(parents=True, exist_ok=True)

    graph = nx.Graph()
    graph.add_edge("1001", "2002")
    nx.write_gml(graph, topology_dir / "topology.gml")
    pd.DataFrame(
        [
            {"plane_id": "1001", "time_s": 0.0, "latitude": 48.0, "longitude": 2.0},
            {"plane_id": "2002", "time_s": 0.0, "latitude": 49.0, "longitude": 3.0},
        ]
    ).to_csv(trajectory_dir / "nodes.csv", index=False)
    (export_dir / "app_settings.toml").write_text(
        "[view_maps_network]\n"
        "edges_file = \"network_sim/pipeline/topology.gml\"\n"
        "traj_glob = \"flight_trajectory/pipeline/*.csv\"\n",
        encoding="utf-8",
    )

    outputs = module.render_inline(
        page="view_maps_network",
        record={"label": "Maps Network", "artifacts": []},
        export_payload={"artifact_dir": str(export_dir)},
    )

    assert len(outputs) == 2
    figure = outputs[1]
    assert figure.layout.title.text == "Maps Network"
    assert len(figure.data) >= 1
