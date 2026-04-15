from __future__ import annotations

import importlib.util
import math
import tomllib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import networkx as nx
import numpy as np

from agi_env import AgiEnv
import pandas as pd

MODULE_PATH = Path(
    "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py"
)
APP_SETTINGS_PATH = Path("src/agilab/apps/builtin/flight_project/src/app_settings.toml")


def _load_view_maps_network_module(monkeypatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("view_maps_network_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    active_app = Path("src/agilab/apps/builtin/flight_project").resolve()
    argv = [MODULE_PATH.name, "--active-app", str(active_app)]
    AgiEnv.reset()
    with patch("sys.argv", argv):
        spec.loader.exec_module(module)
    return module


def _write_heatmap_npz(
    path: Path,
    *,
    heatmap: np.ndarray | None = None,
    x_min: float = 0.0,
    z_min: float = 0.0,
    step: float = 1.0,
    center: tuple[float, float] = (0.0, 0.0),
) -> None:
    np.savez(
        path,
        heatmap=np.asarray(
            heatmap if heatmap is not None else np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
            dtype=np.float32,
        ),
        x_min=np.asarray(x_min, dtype=np.float32),
        z_min=np.asarray(z_min, dtype=np.float32),
        step=np.asarray(step, dtype=np.float32),
        center=np.asarray(center, dtype=np.float32),
    )


def test_view_maps_network_reads_builtin_flight_page_defaults(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    with APP_SETTINGS_PATH.open("rb") as handle:
        app_settings = tomllib.load(handle)

    module.st = SimpleNamespace(session_state={"app_settings": app_settings})
    settings = module._get_view_maps_page_settings()

    assert settings["dataset_base_choice"] == "AGI_SHARE_DIR"
    assert settings["dataset_subpath"] == "flight/dataframe"
    assert settings["default_traj_globs"] == [
        "flight/dataframe/*.parquet",
        "flight/dataframe/*.csv",
    ]


def test_view_maps_network_normalizes_settings_sources(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    assert module._coerce_str_list(" alpha, beta; alpha\n gamma ") == ["alpha", "beta", "gamma"]
    assert module._get_first_nonempty_setting(
        [{"unused": " "}, "ignored", {"primary": " ", "secondary": " chosen "}],
        "primary",
        "secondary",
    ) == "chosen"
    assert module._get_setting_list(
        [{"paths": "one, two;one"}, {"paths": ["two", "three"]}, {"paths": None}],
        "paths",
    ) == ["one", "two", "three"]


def test_view_maps_network_reads_query_params_and_subdirectories(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    module.st = SimpleNamespace(query_params={"multi": ["first", "second"], "single": "value"})

    scan_root = tmp_path / "scan_root"
    scan_root.mkdir()
    (scan_root / "visible_b").mkdir()
    (scan_root / "visible_a").mkdir()
    (scan_root / ".hidden").mkdir()
    (scan_root / "file.txt").write_text("payload", encoding="utf-8")

    assert module._read_query_param("multi") == "second"
    assert module._read_query_param("single") == "value"
    assert module._read_query_param("missing") is None
    assert module._list_subdirectories(scan_root) == ["visible_a", "visible_b"]


def test_view_maps_network_loads_missing_settings_as_empty(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    module.st = SimpleNamespace(session_state={})

    module._ensure_app_settings_loaded(SimpleNamespace(app_settings_file=tmp_path / "missing.toml"))

    assert module.st.session_state["app_settings"] == {}


def test_view_maps_network_persists_app_settings(tmp_path: Path, monkeypatch) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    settings_path = tmp_path / "app_settings.toml"
    module.st = SimpleNamespace(
        session_state={
            "app_settings": {
                "view_maps_network": {
                    "dataset_base_choice": "AGI_SHARE_DIR",
                }
            }
        }
    )

    module._persist_app_settings(SimpleNamespace(app_settings_file=settings_path))

    written = settings_path.read_text(encoding="utf-8")
    assert "view_maps_network" in written
    assert 'dataset_base_choice = "AGI_SHARE_DIR"' in written


def test_view_maps_network_drops_ambiguous_index_levels(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    df = pd.DataFrame(
        {
            "classique_plane": ["A", "B"],
            "time_index": [0, 1],
        },
        index=pd.Index(["A", "B"], name="classique_plane"),
    )

    normalized = module._drop_index_levels_shadowing_columns(df)

    assert list(normalized.columns) == ["classique_plane", "time_index"]
    assert normalized.index.name is None
    assert normalized["classique_plane"].tolist() == ["A", "B"]


def test_view_maps_network_warns_when_no_dataset_exists(
    tmp_path: Path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "demo_map_project",
        "demo_map",
        "[view_maps_network]\n"
        'base_dir_choice = "AGILAB_EXPORT"\n'
        'file_ext_choice = "all"\n',
        pyproject_name="demo-map-project",
    )

    at = run_page_app_test(str(MODULE_PATH), project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any("Maps Network Graph" in title.value for title in at.title)
    assert any("No files found" in warning.value for warning in at.warning)


def test_view_maps_network_resolves_relative_edges_file_from_share_root(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    share_root = tmp_path / "share"
    edges_path = share_root / "network_sim" / "pipeline" / "ilp_topology.gml"
    edges_path.parent.mkdir(parents=True)
    graph = nx.Graph()
    graph.add_edge("1", "2", bearer="satcom")
    nx.write_gml(graph, edges_path)

    resolved = module._resolve_edges_file_path(
        "network_sim/pipeline/ilp_topology.gml",
        [share_root, tmp_path / "export", tmp_path / "flight_trajectory"],
    )

    assert resolved == edges_path
    assert module.load_edges_file(resolved) == {"satcom_link": [("1", "2")]}


def test_view_maps_network_prefers_existing_absolute_edges_file(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    edges_path = tmp_path / "absolute" / "topology.gml"
    edges_path.parent.mkdir(parents=True)
    graph = nx.Graph()
    graph.add_edge("A", "B", bearer="optical")
    nx.write_gml(graph, edges_path)

    resolved = module._resolve_edges_file_path(
        str(edges_path),
        [tmp_path / "share", tmp_path / "export"],
    )

    assert resolved == edges_path
    assert module.load_edges_file(resolved) == {"optical_link": [("A", "B")]}


def test_view_maps_network_loads_heatmap_points_and_stats(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    npz_path = tmp_path / "heatmap.npz"
    _write_heatmap_npz(npz_path)

    points = module._load_cloud_heatmap_points(
        str(npz_path),
        stride=1,
        min_weight=1.5,
        max_points=2,
    )

    assert len(points) == 2
    assert sorted(points["weight"].tolist()) == [3.0, 4.0]

    grid = module._load_cloud_heatmap_grid(str(npz_path))
    assert grid["step"] == 1.0
    assert grid["heatmap"].shape == (2, 2)

    stats = module._sample_cloud_heatmap_stats(str(npz_path), 0.0, 0.0, neighborhood_radius_cells=1)
    assert stats == {
        "raw_value": 1.0,
        "proxy_value": 4.0,
        "local_mean": 2.5,
        "local_max": 4.0,
    }

    invalid = module._sample_cloud_heatmap_stats(str(npz_path), "bad", 0.0)
    assert all(math.isnan(value) for value in invalid.values())


def test_view_maps_network_decision_samples_and_heatmap_timeline(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    alloc_df = pd.DataFrame({"time_index": [1, 2], "t_now_s": [10.5, np.nan]})
    baseline_df = pd.DataFrame({"time_index": [2, 3], "t_now_s": [20.0, 30.0]})
    samples = module._decision_time_samples(alloc_df, baseline_df, [1, 2, 4])
    assert samples.to_dict("records") == [
        {"time_index": 1, "sample_time_s": 10.5},
        {"time_index": 2, "sample_time_s": 20.0},
        {"time_index": 4, "sample_time_s": 4.0},
    ]

    def fake_sample_cloud_heatmap_stats(
        _npz_path: str,
        lat: float,
        lon: float,
        neighborhood_radius_cells: int = 25,
    ) -> dict[str, float]:
        assert neighborhood_radius_cells == 2
        return {
            "raw_value": float(lat),
            "proxy_value": float(lat + lon),
            "local_mean": 1.5,
            "local_max": 2.5,
        }

    monkeypatch.setattr(module, "_sample_cloud_heatmap_stats", fake_sample_cloud_heatmap_stats)

    trajectory_df = pd.DataFrame(
        {
            "id_col": ["A", "A", "B", "A"],
            "time_col": [0, 2, 1, 4],
            "lat": [1.0, 2.0, 8.0, np.nan],
            "long": [10.0, 11.0, 12.0, 13.0],
        }
    )
    timeline = module._selected_nodes_heatmap_timeline(
        trajectory_df,
        "unused.npz",
        {"A"},
        neighborhood_radius_cells=2,
    )

    assert timeline.to_dict("records") == [
        {
            "node_id": "A",
            "map_time": 0,
            "heatmap_value": 11.0,
            "raw_heatmap_value": 1.0,
            "local_mean": 1.5,
            "local_max": 2.5,
            "lat": 1.0,
            "long": 10.0,
        },
        {
            "node_id": "A",
            "map_time": 2,
            "heatmap_value": 13.0,
            "raw_heatmap_value": 2.0,
            "local_mean": 1.5,
            "local_max": 2.5,
            "lat": 2.0,
            "long": 11.0,
        },
    ]


def test_view_maps_network_downsamples_and_plots_heatmap_timeline(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    numeric_timeline = pd.DataFrame(
        {
            "node_id": ["A", "A", "A", "A"],
            "map_time": [0, 1, 2, 5],
            "heatmap_value": [1.0, 2.0, 3.0, 4.0],
            "raw_heatmap_value": [1.0, 2.0, 3.0, 4.0],
            "local_mean": [1.0, 1.5, 2.0, 2.5],
            "local_max": [1.0, 2.0, 3.0, 4.0],
            "lat": [1.0, 1.1, 1.2, 1.3],
            "long": [2.0, 2.1, 2.2, 2.3],
        }
    )
    downsampled_numeric = module._downsample_heatmap_timeline(numeric_timeline, step_s=2)
    assert downsampled_numeric["map_time"].tolist() == [0, 2, 5]

    datetime_timeline = numeric_timeline.copy()
    datetime_timeline["node_id"] = ["A", "A", "B", "B"]
    datetime_timeline["map_time"] = pd.to_datetime(
        [
            datetime(2024, 1, 1, 0, 0, 0),
            datetime(2024, 1, 1, 0, 0, 1),
            datetime(2024, 1, 1, 0, 0, 0),
            datetime(2024, 1, 1, 0, 0, 3),
        ]
    )
    downsampled_datetime = module._downsample_heatmap_timeline(datetime_timeline, step_s=2)
    assert downsampled_datetime["map_time"].tolist() == [
        pd.Timestamp("2024-01-01 00:00:00"),
        pd.Timestamp("2024-01-01 00:00:00"),
        pd.Timestamp("2024-01-01 00:00:03"),
    ]

    fig = module._plot_selected_nodes_heatmap_timeline(datetime_timeline, "SAT")
    assert len(fig.data) == 2
    assert fig.layout.title.text == "SAT cloud intensity proxy at planes A and B over trajectory time"
    assert fig.data[0].name == "A"
    assert fig.data[1].name == "B"


def test_view_maps_network_builds_cloud_and_trace_layers(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    warnings: list[str] = []
    module.st = SimpleNamespace(
        session_state={
            "show_cloud_heatmap": True,
            "cloud_heatmap_stride": 3,
            "cloud_heatmap_min_weight": 0.25,
            "cloud_heatmap_sat_path": "sat_map.npz",
            "cloud_heatmap_ivdl_path": "missing_map.npz",
            "show_trajectory_traces": True,
        },
        sidebar=SimpleNamespace(warning=warnings.append),
    )

    def fake_load_cloud_heatmap_points(path: str, stride: int, min_weight: float):
        assert stride == 3
        assert min_weight == 0.25
        if "missing" in path:
            raise FileNotFoundError(path)
        return pd.DataFrame({"long": [1.0], "lat": [2.0], "weight": [3.0]})

    monkeypatch.setattr(module, "_load_cloud_heatmap_points", fake_load_cloud_heatmap_points)

    heatmap_layers = module._cloud_heatmap_layers()
    assert len(heatmap_layers) == 1
    assert heatmap_layers[0].type == "HeatmapLayer"
    assert heatmap_layers[0].data == [{"long": 1.0, "lat": 2.0, "weight": 3.0}]
    assert warnings == ["IVDL cloud map unavailable (missing_map.npz): missing_map.npz"]

    traces = module._trajectory_trace_layers(
        pd.DataFrame(
            {
                "id_col": ["A", "A", "A", "B"],
                "time_col": [1, 2, 3, 1],
                "long": [1.0, 2.0, 2.0, 5.0],
                "lat": [10.0, 11.0, 11.0, 20.0],
            }
        ),
        color_lookup={"A": [1, 2, 3, 4]},
    )
    assert len(traces) == 1
    assert traces[0].type == "PathLayer"
    assert traces[0].data == [
        {
            "id_col": "A",
            "path": [[1.0, 10.0], [2.0, 11.0]],
            "color": [1, 2, 3, 4],
        }
    ]


def test_view_maps_network_builds_topology_layers_and_coerces_slider_values(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    module.st = SimpleNamespace(session_state={"show_topology_links": True})

    def fake_create_edges_geomap(
        _df: pd.DataFrame,
        link_col: str,
        _current_positions: pd.DataFrame,
        *,
        allowed_edge_pairs: set[tuple[str, str]] | None = None,
    ) -> pd.DataFrame:
        assert allowed_edge_pairs is None
        if link_col != "satcom_link":
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "source": [[0.0, 0.0]],
                "target": [[1.0, 1.0]],
                "midpoint": [[0.5, 0.5]],
                "label": ["SAT"],
            }
        )

    monkeypatch.setattr(module, "create_edges_geomap", fake_create_edges_geomap)

    layers = module._topology_link_layers(
        ["satcom_link", "optical_link"],
        pd.DataFrame(),
        pd.DataFrame(),
        {"satcom_link": "rgb(1, 2, 3)"},
    )
    assert [layer.type for layer in layers] == ["LineLayer", "TextLayer"]
    assert layers[0].data == [
        {
            "source": [0.0, 0.0],
            "target": [1.0, 1.0],
            "midpoint": [0.5, 0.5],
            "label": "SAT",
        }
    ]

    assert module._coerce_slider_value([0, 10, 20], 12) == 10
    assert module._coerce_slider_value(
        [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-05")],
        "2024-01-04",
    ) == pd.Timestamp("2024-01-05")
    assert module._coerce_slider_value([], 1) is None
    assert module._coerce_slider_value([1, 2, 3], None, prefer_last=True) == 3


def test_view_maps_network_resolves_candidates_and_declared_paths(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    base = tmp_path / "share"
    hidden = base / ".hidden" / "pipeline"
    visible = base / "network_a" / "pipeline"
    visible.mkdir(parents=True)
    hidden.mkdir(parents=True)

    topology_path = visible / "topology.gml"
    routing_edges_path = visible / "routing_edges.jsonl"
    hidden_path = hidden / "topology.gml"
    topology_path.write_text("graph", encoding="utf-8")
    routing_edges_path.write_text("{}", encoding="utf-8")
    hidden_path.write_text("hidden", encoding="utf-8")
    topology_path.touch()
    routing_edges_path.touch()

    edge_candidates = module._candidate_edges_paths([base])
    assert topology_path in edge_candidates
    assert routing_edges_path in edge_candidates
    assert hidden_path not in edge_candidates

    share_candidates = module._quick_share_edges_paths(base)
    assert topology_path in share_candidates
    assert hidden_path not in share_candidates

    traj_root = tmp_path / "trajectories"
    parquet_path = traj_root / "demo_trajectory" / "pipeline" / "points.parquet"
    csv_path = traj_root / "demo_trajectory" / "pipeline" / "points.csv"
    parquet_path.parent.mkdir(parents=True)
    parquet_path.write_text("parquet", encoding="utf-8")
    csv_path.write_text("csv", encoding="utf-8")

    globs_list = module._quick_share_traj_globs(traj_root)
    assert any(pattern.endswith("*.parquet") for pattern in globs_list)
    assert any(pattern.endswith("*.csv") for pattern in globs_list)

    matched_files = module._candidate_files_from_globs([str(parquet_path), str(parquet_path), str(csv_path)])
    assert matched_files == [csv_path, parquet_path] or matched_files == [parquet_path, csv_path]

    expanded = module._expand_glob_patterns(
        ["  data/*.csv  ", str(csv_path)],
        [traj_root / "demo_trajectory"],
    )
    assert str(traj_root / "demo_trajectory" / "data/*.csv") in expanded
    assert str(csv_path) in expanded

    declared = module._resolve_declared_path("demo_trajectory/pipeline/points.csv", [traj_root, base])
    assert declared == str(csv_path)

    cloud_root = tmp_path / "cloud_root"
    cloud_path = cloud_root / "dataset" / "sat_map.npz"
    cloud_path.parent.mkdir(parents=True)
    _write_heatmap_npz(cloud_path)
    cloud_candidates = module._candidate_cloudmap_paths([cloud_root], ("sat_map.npz",))
    assert cloud_candidates == [cloud_path]
