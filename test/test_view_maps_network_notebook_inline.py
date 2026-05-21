from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

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


def test_view_maps_network_notebook_inline_helper_edge_cases(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()

    assert module._coerce_str_list(None) == []
    assert module._coerce_str_list(" a; b\nc, a ") == ["a", "b", "c"]
    assert module._coerce_str_list(["x", "x", "", "y"]) == ["x", "y"]
    assert module._coerce_str_list(12) == ["12"]
    assert module._read_toml_dict(object()) == {}
    assert module._read_toml_dict(tmp_path / "missing.toml") == {}
    broken_toml = tmp_path / "broken.toml"
    broken_toml.write_text("[broken\n", encoding="utf-8")
    assert module._read_toml_dict(broken_toml) == {}

    export_dir = tmp_path / "export"
    export_dir.mkdir()
    settings_file = tmp_path / "workspace_settings.toml"
    (export_dir / "app_settings.toml").write_text(
        "[view_maps_network]\n"
        "dataset_subpath = 'network_sim'\n"
        "traj_glob = 'flight/*.csv, flight/*.csv'\n"
        "[pages.view_maps_network]\n"
        "edges_file = 'nested/topology.json'\n",
        encoding="utf-8",
    )
    settings_file.write_text("[pages.view_maps_network]\ndefault_traj_globs=['extra/*.csv']\n", encoding="utf-8")
    sources = module._page_setting_sources(
        {"artifact_dir": str(export_dir), "app_settings_file": str(settings_file)}
    )
    assert len(sources) == 3
    assert module._first_nonempty_setting(["bad", {}, {"edges_file": " topology.gml "}], "edges_file") == "topology.gml"
    assert module._first_nonempty_setting([{}], "missing") == ""
    assert module._setting_list(["bad", {"traj_glob": "a.csv, a.csv", "default_traj_globs": ["b.csv"]}], "traj_glob", "default_traj_globs") == [
        "a.csv",
        "b.csv",
    ]
    assert module._setting_list(
        [{"traj_glob": ["dup.csv"]}, {"default_traj_globs": ["dup.csv", "new.csv"]}],
        "traj_glob",
        "default_traj_globs",
    ) == ["dup.csv", "new.csv"]
    base_dirs = module._candidate_base_dirs({"artifact_dir": str(export_dir)}, sources)
    assert export_dir.resolve() in base_dirs
    assert (export_dir / "network_sim").resolve() in base_dirs
    assert module._candidate_base_dirs({"artifact_dir": "bad\0path"}, [])
    deduped_base_dirs = module._candidate_base_dirs({"artifact_dir": str(export_dir)}, [{"dataset_subpath": "."}])
    assert len(deduped_base_dirs) == len(set(deduped_base_dirs))
    assert module._resolve_declared_path("", base_dirs) is None
    assert module._resolve_declared_path(str(export_dir / "absolute.gml"), base_dirs) == export_dir / "absolute.gml"
    relative_file = export_dir / "network_sim" / "relative.csv"
    relative_file.parent.mkdir(parents=True, exist_ok=True)
    relative_file.write_text("id,lat,lon,time\n", encoding="utf-8")
    assert module._resolve_declared_path("relative.csv", base_dirs) == relative_file
    assert module._resolve_declared_path("missing.csv", base_dirs) is None

    glob_dir = export_dir / "glob"
    glob_dir.mkdir()
    (glob_dir / "dir.csv").mkdir()
    first = glob_dir / "first.csv"
    second = glob_dir / "second.csv"
    first.write_text("a\n", encoding="utf-8")
    second.write_text("a\n", encoding="utf-8")
    matches = module._expand_globs(["", str(glob_dir / "*.csv"), str(glob_dir / "*.csv")], [export_dir])
    assert sorted(path.name for path in matches) == ["first.csv", "second.csv"]

    real_path = module.Path

    class ResolveFailPath:
        def __init__(self, value):
            self._path = real_path(value)

        def expanduser(self):
            return self

        def is_absolute(self):
            return self._path.is_absolute()

        def is_file(self):
            return True

        def resolve(self, *, strict=False):
            raise OSError("cannot resolve")

        def exists(self):
            return True

        def stat(self):
            return SimpleNamespace(st_mtime=0.0)

        def __str__(self):
            return str(self._path)

        def __hash__(self):
            return hash(self._path)

        def __eq__(self, other):
            return isinstance(other, ResolveFailPath) and self._path == other._path

    monkeypatch.setattr(module, "Path", ResolveFailPath)
    monkeypatch.setattr(module.glob, "glob", lambda *_args, **_kwargs: [str(first)])
    assert len(module._expand_globs(["*.csv"], [export_dir])) == 1


def test_view_maps_network_notebook_inline_graph_position_and_graph_only_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()

    assert module._load_graph(None) is None
    bad_graph = tmp_path / "bad_graph.txt"
    bad_graph.write_text("not json or gml", encoding="utf-8")
    assert module._load_graph(bad_graph) is None

    dict_graph_path = tmp_path / "topology.json"
    dict_graph_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "A", "weight": 1}, "B", None, {"id": ""}],
                "edges": [
                    {"source": "A", "target": "B", "capacity": 3},
                    ["B", "C"],
                    {"source": "", "target": "C"},
                ],
            }
        ),
        encoding="utf-8",
    )
    dict_graph = module._load_graph(dict_graph_path)
    assert dict_graph is not None
    assert sorted(dict_graph.nodes()) == ["A", "B", "C"]
    assert sorted(tuple(sorted(edge)) for edge in dict_graph.edges()) == [("A", "B"), ("B", "C")]

    list_graph_path = tmp_path / "list_topology.json"
    list_graph_path.write_text(json.dumps([["X", "Y"], ["Y", "Z"], ["skip"]]), encoding="utf-8")
    list_graph = module._load_graph(list_graph_path)
    assert list_graph is not None
    assert sorted(list_graph.nodes()) == ["X", "Y", "Z"]
    empty_graph_path = tmp_path / "empty_topology.json"
    empty_graph_path.write_text("{}", encoding="utf-8")
    assert module._load_graph(empty_graph_path) is None

    assert module._first_column({"time": "Time"}, "missing", "time") == "Time"
    assert module._first_column({}, "missing") == ""
    assert module._best_id_column(pd.DataFrame({"Call_Sign": ["A"]})) == "Call_Sign"
    assert module._best_id_column(pd.DataFrame({"unknown": ["A"]})) == ""
    parquet_path = tmp_path / "positions.parquet"
    parquet_path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(
        module.pd,
        "read_parquet",
        lambda _path: pd.DataFrame({"node_id": ["P"], "lat": [1.0], "lon": [2.0]}),
    )
    assert module._load_frame(parquet_path)["node_id"].tolist() == ["P"]

    missing_positions = module._load_positions([tmp_path / "missing.csv"])
    assert list(missing_positions.columns) == ["node_id", "lat", "lon", "alt", "source_file"]
    incomplete_csv = tmp_path / "incomplete.csv"
    incomplete_csv.write_text("node_id,time_s\nA,1\n", encoding="utf-8")
    assert module._load_positions([incomplete_csv]).empty
    invalid_positions = tmp_path / "invalid_positions.csv"
    invalid_positions.write_text("node_id,time_s,lat,lon\nA,1,bad,bad\n", encoding="utf-8")
    assert module._load_positions([invalid_positions]).empty
    positions_csv = tmp_path / "positions.csv"
    pd.DataFrame(
        [
            {"Call_Sign": "A", "time": 1, "lat": 47.0, "lon": 2.0},
            {"Call_Sign": "A", "time": 2, "lat": 48.0, "lon": 3.0},
            {"Call_Sign": "B", "time": 1, "lat": 49.0, "lon": 4.0},
            {"Call_Sign": "C", "time": 1, "lat": 50.0, "lon": 5.0},
            {"Call_Sign": "D", "time": 1, "lat": None, "lon": 6.0},
        ]
    ).to_csv(positions_csv, index=False)
    positions = module._load_positions([positions_csv])
    assert sorted(positions[["node_id", "lat", "lon", "alt"]].to_dict("records"), key=lambda row: row["node_id"]) == [
        {"node_id": "A", "lat": 48.0, "lon": 3.0, "alt": 0.0},
        {"node_id": "B", "lat": 49.0, "lon": 4.0, "alt": 0.0},
        {"node_id": "C", "lat": 50.0, "lon": 5.0, "alt": 0.0},
    ]

    geo_figure = module._geo_map_figure(dict_graph, positions, title="Geo")
    assert geo_figure.layout.title.text == "Geo"
    assert len(geo_figure.data) == 2
    sparse_graph = nx.Graph()
    sparse_graph.add_edge("A", "missing")
    sparse_geo = module._geo_map_figure(sparse_graph, positions, title="Sparse")
    assert len(sparse_geo.data) == 1
    topology_figure = module._topology_figure(dict_graph, title="Topology")
    assert topology_figure.layout.title.text == "Topology"
    assert len(topology_figure.data) == 2

    export_dir = tmp_path / "graph_only_export"
    pipeline_dir = export_dir / "pipeline"
    pipeline_dir.mkdir(parents=True)
    (pipeline_dir / "topology.json").write_text(json.dumps([["A", "B"]]), encoding="utf-8")
    outputs = module.render_inline(
        page="",
        record={},
        export_payload={"artifact_dir": str(export_dir)},
    )
    assert len(outputs) == 2
    assert "Graph nodes/edges: 2 / 1" in outputs[0].data
    assert outputs[1].layout.title.text == "Maps Network"
