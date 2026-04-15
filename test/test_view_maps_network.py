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


def test_view_maps_network_extracts_semantic_node_id_from_label(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    assert module._semantic_node_id_from_text("uswc_forward_02-S002") == "2002"
    assert module._semantic_node_id_from_text("SES-10") == "10"
    assert module._semantic_node_id_from_text("NSS-11") == "11"


def test_view_maps_network_prefers_semantic_ids_over_local_plane_counters(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

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


def test_view_maps_network_prefers_semantic_ids_when_normalizing_rows(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    row = pd.Series(
        {
            "plane_id": 1,
            "plane_label": "uswc_forward_02-S002",
            "source_file": "pipeline/uswc_forward_02-S002_2026-04-01_15-27-48.csv",
        }
    )

    assert module._preferred_node_id_from_row(row) == "2002"


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


def test_view_maps_network_normalizes_and_resolves_node_ids(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    series = pd.Series([1, 2.0, " plane_3 ", None, "nan", "<NA>", "uav_4"])
    normalized = module._normalize_node_id_series(series)
    assert normalized.tolist() == ["1", "2", "plane_3", "", "", "", "uav_4"]

    assert module._normalize_node_id_value(5.0) == "5"
    assert module._normalize_node_id_value("  ") == ""
    assert module._normalize_node_id_value("node_7") == "node_7"

    assert module._candidate_node_ids("plane_3")[:2] == ["plane_3", "3"]
    assert module._resolve_node_id("plane_3", {"3", "node_9"}) == "3"
    assert module._resolve_node_id("missing", {"3"}) is None

    assert module._coerce_list_cell(None) == []
    assert module._coerce_list_cell((1, 2)) == [1, 2]
    assert module._coerce_list_cell("[1, 2, 3]") == [1, 2, 3]


def test_view_maps_network_builds_visible_nodes_and_endpoint_roles(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    alloc_df = pd.DataFrame(
        {
            "source": ["plane_1", "1"],
            "destination": ["2", "2"],
            "path": [[("1", "2"), ("2", "3")], None],
        }
    )
    visible = module._allocation_visible_node_ids(alloc_df)
    assert visible == {"plane_1", "1", "2", "3"}

    roles = module._allocation_endpoint_roles(alloc_df.iloc[[1]])
    assert roles == {"1": "src", "2": "dst"}
    assert module._allocation_endpoint_roles(alloc_df, focus_pair=(8, 9)) == {"8": "src", "9": "dst"}

    assert module._format_node_label("2", roles) == "2 (dst)"
    assert module._format_node_label("  ", roles) == ""


def test_view_maps_network_builds_map_label_layers(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    positions_df = pd.DataFrame(
        {
            "flight_id": ["1", "2", None],
            "long": [1.0, 2.0, 3.0],
            "lat": [10.0, 20.0, 30.0],
        }
    )
    layers = module._build_map_label_layers(positions_df, node_roles={"1": "src"})
    assert [layer.type for layer in layers] == ["TextLayer", "TextLayer"]
    assert layers[0].data == [
        {"flight_id": "1", "long": 1.0, "lat": 10.0, "alt": 0.0, "node_id_text": "1"},
        {"flight_id": "2", "long": 2.0, "lat": 20.0, "alt": 0.0, "node_id_text": "2"},
    ]
    assert layers[1].data == [
        {
            "flight_id": "1",
            "long": 1.0,
            "lat": 10.0,
            "alt": 0.0,
            "node_id_text": "1",
            "node_role": "SRC",
        }
    ]

    assert module._build_map_label_layers(pd.DataFrame()) == []


def test_view_maps_network_filters_and_expands_allocations(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    alloc_df = pd.DataFrame(
        {
            "source": ["1", "1", "1", "4"],
            "destination": ["2", "2", "3", "5"],
            "t_now_s": [5.0, 9.0, 9.0, 9.0],
            "time_index": [1, 2, 2, 2],
            "path": [[("1", "2"), ("2", "3")], [("1", "2")], None, [("4", "5")]],
            "routed": [True, True, False, True],
            "bearers": [[], ["satcom"], ["satcom"], ["satcom"]],
        }
    )

    filtered_by_time = module._filter_allocation_rows_for_selected_nodes(
        alloc_df,
        {"1", "2"},
        sample_time=8.8,
    )
    assert filtered_by_time["t_now_s"].tolist() == [9.0]

    filtered_by_step = module._filter_allocation_rows_for_selected_nodes(
        alloc_df,
        {"1", "2"},
        step_hint=1,
    )
    assert filtered_by_step["time_index"].tolist() == [1]

    fake_path_a = tmp_path / "alloc_a.parquet"
    fake_path_b = tmp_path / "alloc_b.parquet"
    fake_path_a.write_text("a", encoding="utf-8")
    fake_path_b.write_text("b", encoding="utf-8")
    load_map = {fake_path_a: alloc_df, fake_path_b: alloc_df.iloc[[1, 2]].copy()}
    monkeypatch.setattr(module, "load_allocations", lambda path: load_map[path])

    expanded = module._expanded_node_ids_from_allocations(
        {"1", "2"},
        sample_time=9.0,
        allocation_paths=[fake_path_a, fake_path_b],
    )
    assert expanded == {"1", "2"}

    roles = module._endpoint_roles_from_allocations(
        {"1", "2"},
        sample_time=9.0,
        allocation_paths=[fake_path_a],
    )
    assert roles == {"1": "src", "2": "dst"}

    routed_pairs = module._allocation_routed_edge_pairs(
        {"1", "2"},
        sample_time=9.0,
        allocation_paths=[fake_path_a, fake_path_b],
    )
    assert routed_pairs == {("1", "2")}

    missing_pairs = module._allocation_routed_edge_pairs({"1", "2"}, allocation_paths=[tmp_path / "missing.parquet"])
    assert missing_pairs is None


def test_view_maps_network_detects_allocation_files_and_edge_counts(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    base = tmp_path / "alloc_share"
    visible = base / "pipeline"
    hidden = base / ".hidden" / "pipeline"
    visible.mkdir(parents=True)
    hidden.mkdir(parents=True)
    alloc_main = visible / "allocations_steps.parquet"
    alloc_extra = visible / "allocations_extra.jsonl"
    alloc_hidden = hidden / "allocations_steps.csv"
    alloc_main.write_text("main", encoding="utf-8")
    alloc_extra.write_text("extra", encoding="utf-8")
    alloc_hidden.write_text("hidden", encoding="utf-8")

    candidates = module._candidate_allocation_paths([base])
    assert alloc_main in candidates
    assert alloc_extra in candidates
    assert alloc_hidden not in candidates

    assert module._is_baseline_alloc_path(Path("demo_baseline_allocations.parquet"))
    assert module._is_baseline_alloc_path(Path("demo_ilp_allocations.parquet"))
    assert not module._is_baseline_alloc_path(Path("demo_allocations.parquet"))

    df = pd.DataFrame({"satcom_link": ["[(1, 2), (2, 3)]", None]})
    assert module._preview_edge_count(df, "satcom_link") == 2
    assert module._preview_edge_count(df, "missing") == 0


def test_view_maps_network_color_and_link_helpers(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    assert module._parse_rgb_like("rgb(10,20,30)") == (10, 20, 30, 255)
    assert module._parse_rgb_like("rgba(0.1,0.2,0.3,0.5)") == (26, 51, 76, 128)
    assert module._parse_rgb_like("bad") is None

    assert module._color_to_rgb("rgb(4,5,6)") == [4, 5, 6, 255]
    assert module._to_plotly_color([7, 8, 9, 10]) == "rgb(7,8,9)"
    assert module._to_plotly_color("rgba(10,20,30,0.5)") == "rgba(10,20,30,0.502)"
    assert module.hex_to_rgba("#112233") == [17, 34, 51, 255]
    assert module.hex_to_rgba(None) == [136, 136, 136, 255]

    link_df = pd.DataFrame(
        {
            "flight_id": ["1"],
            "long": [1.0],
            "lat": [2.0],
            "satcom_link": ["[(1, 2)]"],
            "custom_link": [[(2, 3)]],
            "noise": ["hello"],
        }
    )
    assert module._detect_link_columns(link_df) == ["satcom_link", "custom_link"]


def test_view_maps_network_parses_edges_and_geomap_layers(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    warnings: list[str] = []
    module.st = SimpleNamespace(
        warning=warnings.append,
        session_state={"show_terrain": False, "show_cloud_heatmap": False, "show_trajectory_traces": False},
    )

    current_positions = pd.DataFrame(
        {
            "flight_id": ["1", "2", "3"],
            "id_col": ["1", "2", "3"],
            "long": [0.0, 1.0, 2.0],
            "lat": [10.0, 11.0, 12.0],
            "alt": [100.0, 200.0, 300.0],
            "color": [[1, 2, 3, 255], [4, 5, 6, 255], [7, 8, 9, 255]],
        }
    )
    df = pd.DataFrame({"flight_id": ["1"], "satcom_link": ["[(1, 2), (2, 3)]"], "long": [0.0], "lat": [10.0], "alt": [100.0]})

    edges = module.create_edges_geomap(df.copy(), "satcom_link", current_positions)
    assert edges.to_dict("records") == [
        {
            "source": [0.0, 10.0, 100.0],
            "target": [1.0, 11.0, 200.0],
            "label": "SAT",
            "midpoint": [0.5, 10.5, 150.0],
        },
        {
            "source": [1.0, 11.0, 200.0],
            "target": [2.0, 12.0, 300.0],
            "label": "SAT",
            "midpoint": [1.5, 11.5, 250.0],
        },
    ]

    assert module.parse_edges(["[(1, 2), (2, 3)]", [(3, 4)]]) == [("1", "2"), ("2", "3"), ("3", "4")]
    assert module.filter_edges(df, ["satcom_link"], {("1", "2")}) == {"satcom_link": [("1", "2")]}

    layers = module.create_layers_geomap(
        ["satcom_link"],
        df.copy(),
        current_positions,
        {"satcom_link": "rgb(10,20,30)"},
        marker_style="Dots",
        show_node_labels=True,
    )
    assert [layer.type for layer in layers] == ["LineLayer", "TextLayer", "PointCloudLayer", "TextLayer"]
    assert warnings == []


def test_view_maps_network_normalizes_allocations_frames_and_finds_latest(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    assert module._pick_ci_column(pd.DataFrame([{"SRC": 1, "dst": 2}]), ("source", "src")) == "SRC"
    assert module._pick_ci_column(pd.DataFrame(), ("source",)) is None

    assert module._parse_allocations_cell("[{'source': 1, 'destination': 2}]") == [{"source": 1, "destination": 2}]
    assert module._parse_allocations_cell({"source": 1}) == [{"source": 1}]
    assert module._parse_allocations_cell(None) == []

    stepped = module._coerce_alloc_time_index(pd.DataFrame({"decision": [1, None, 3]}))
    assert stepped["time_index"].tolist() == [1, 1, 3]

    alloc_frame = pd.DataFrame(
        {
            "decision": [7],
            "time_s": [1.5],
            "allocations": ["[{'src': '1', 'dst': '2', 'routed': True, 'path': [(1, 2)]}]"],
        }
    )
    normalized = module._normalize_allocations_frame(alloc_frame)
    assert normalized.to_dict("records") == [
        {
            "src": "1",
            "dst": "2",
            "routed": True,
            "path": [(1, 2)],
            "time_index": 7,
            "t_now_s": 1.5,
        }
    ]

    jsonl_path = tmp_path / "allocations.jsonl"
    jsonl_path.write_text('{"source": "1", "destination": "2", "time_index": 4}\n', encoding="utf-8")
    loaded = module.load_allocations(jsonl_path)
    assert loaded["time_index"].tolist() == [4]
    assert loaded["source"].tolist() == ["1"]

    nearest = module._nearest_row(pd.DataFrame({"time_s": [1.0, 2.5, 9.0], "value": [1, 2, 3]}), 2.0)
    assert nearest["value"].tolist() == [2]

    latest_root = tmp_path / "latest_allocs"
    latest_root.mkdir()
    older = latest_root / "allocations_steps.csv"
    newer = latest_root / "baseline_allocations_steps.csv"
    older.write_text("a", encoding="utf-8")
    newer.write_text("b", encoding="utf-8")
    newer.touch()
    assert module._find_latest_allocations(latest_root) in {older, newer}
    assert module._find_latest_allocations(latest_root, include=("baseline",)) == newer
