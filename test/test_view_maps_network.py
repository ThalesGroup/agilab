from __future__ import annotations

import importlib.util
import math
import tomllib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import warnings

import networkx as nx
import numpy as np
import pytest
from streamlit.runtime.scriptrunner_utils.script_requests import RerunData

from agi_env import AgiEnv
import pandas as pd

MODULE_PATH = Path(
    "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py"
)
APP_SETTINGS_PATH = Path("src/agilab/apps/builtin/flight_telemetry_project/src/app_settings.toml")


def _suppress_page_import_warnings() -> None:
    warnings.filterwarnings(
        "ignore",
        message=r".*ast\.Num is deprecated and will be removed in Python 3\.14.*",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"Theme names and color schemes are lowercase in IPython 9\.0 use nocolor instead",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"'oneOf' deprecated - use 'one_of'",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"'parseString' deprecated - use 'parse_string'",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"'resetCache' deprecated - use 'reset_cache'",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"'enablePackrat' deprecated - use 'enable_packrat'",
        category=DeprecationWarning,
    )


def _load_view_maps_network_module(monkeypatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("view_maps_network_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    active_app = Path("src/agilab/apps/builtin/flight_telemetry_project").resolve()
    argv = [MODULE_PATH.name, "--active-app", str(active_app)]
    AgiEnv.reset()
    with warnings.catch_warnings():
        _suppress_page_import_warnings()
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

    assert settings["dataset_base_choice"] == "AGI_CLUSTER_SHARE"
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
                    "dataset_base_choice": "AGI_CLUSTER_SHARE",
                    "df_file": None,
                    "df_files": ["export.csv", None],
                }
            }
        }
    )

    module._persist_app_settings(SimpleNamespace(app_settings_file=settings_path))

    written = settings_path.read_text(encoding="utf-8")
    assert "view_maps_network" in written
    assert 'dataset_base_choice = "AGI_CLUSTER_SHARE"' in written
    parsed = tomllib.loads(written)
    assert parsed["__meta__"] == {"schema": "agilab.app_settings.v1", "version": 1}
    assert parsed["view_maps_network"]["df_file"] == ""
    assert parsed["view_maps_network"]["df_files"] == ["export.csv", ""]


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

    at = run_page_app_test(str(MODULE_PATH), project_dir, export_root=tmp_path / "export", timeout=60)

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


def test_view_maps_network_unexpected_semantic_label_errors_propagate(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_strip_export_suffix", lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("bad strip")))

    with pytest.raises(TypeError, match="bad strip"):
        module._semantic_node_id_from_text("SES-10")


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

    monkeypatch.setattr(
        module,
        "_load_cloud_heatmap_points",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("bad loader")),
    )
    with pytest.raises(TypeError, match="bad loader"):
        module._cloud_heatmap_layers()

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


def test_view_maps_network_loaders_and_bearer_helpers(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    parquet_path = tmp_path / "edges.parquet"
    pd.DataFrame(
        [
            {"src": "1", "dst": "2", "link_type": "satcom"},
            {"src": "2", "dst": "3", "link_type": "optical"},
        ]
    ).to_parquet(parquet_path)
    assert module.load_edges_file(parquet_path) == {
        "satcom_link": [("1", "2")],
        "optical_link": [("2", "3")],
    }

    bad_csv = tmp_path / "traj_bad.csv"
    bad_csv.write_bytes("col\n\xff\n".encode("latin-1"))
    loaded_bad = module._load_traj_file(str(bad_csv))
    assert not loaded_bad.empty

    assert module._bearer_path_label(["SAT", "OPT"]) == "SAT → OPT"
    assert module._bearer_path_label("['SAT', 'OPT']") == "SAT → OPT"
    assert module._bearer_tokens("SAT -> OPT") == ["SAT", "OPT"]
    assert module._bearer_tokens(("LEG", "IVDL")) == ["LEG", "IVDL"]
    assert module._canonical_bearer_state("optical", True) == "OPT"
    assert module._canonical_bearer_state("satcom", True) == "SAT"
    assert module._canonical_bearer_state("legacy", True) == "Legacy"
    assert module._canonical_bearer_state(None, False) == "Not routed"


def test_view_maps_network_selected_node_bearer_timeline_and_allocation_layers(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    timeline_df = pd.DataFrame(
        {
            "time_index": [1, 2, 3],
            "source": ["1", "1", "3"],
            "destination": ["2", "3", "2"],
            "bearers": [["satcom"], "optical", None],
            "routed": [True, True, False],
        }
    )
    timeline = module._selected_node_bearer_timeline(timeline_df, {"1", "2"}, "alloc")
    assert timeline.to_dict("records") == [
        {"method": "alloc", "node_id": "1", "time_index": 1, "bearer_path": "SAT", "peers": "2", "row_label": "alloc | 1"},
        {"method": "alloc", "node_id": "1", "time_index": 2, "bearer_path": "OPT", "peers": "3", "row_label": "alloc | 1"},
        {"method": "alloc", "node_id": "2", "time_index": 1, "bearer_path": "SAT", "peers": "1", "row_label": "alloc | 2"},
        {"method": "alloc", "node_id": "2", "time_index": 3, "bearer_path": "Not routed", "peers": "3", "row_label": "alloc | 2"},
    ]

    positions = pd.DataFrame(
        {
            "flight_id": ["1", "2", "3"],
            "long": [0.0, 1.0, 2.0],
            "lat": [10.0, 11.0, 12.0],
            "alt": [100.0, 200.0, 300.0],
        }
    )
    alloc_df = pd.DataFrame(
        [
            {
                "source": "1",
                "destination": "2",
                "bandwidth": 5.0,
                "delivered_bandwidth": 10.0,
                "path": [("1", "2"), ("2", "3")],
                "bearers": ["satcom", "optical"],
            },
            {
                "source": "1",
                "destination": "3",
                "bandwidth": 1.0,
                "delivered_bandwidth": 0.0,
                "path": None,
                "bearers": ["legacy"],
            },
        ]
    )
    layers = module.build_allocation_layers(alloc_df, positions, color=[10, 20, 30])
    assert len(layers) == 1
    assert layers[0].type == "LineLayer"
    assert len(layers[0].data) == 3
    assert {row["demand"] for row in layers[0].data} == {"1→2", "1→3"}


def test_view_maps_network_bearer_plot_and_map_layer_wrapper(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    empty_fig = module._plot_selected_node_bearer_timeline(pd.DataFrame())
    assert len(empty_fig.data) == 0
    assert empty_fig.layout.height == 220

    timeline_df = pd.DataFrame(
        [
            {"method": "alloc", "node_id": "1", "time_index": 1, "bearer_path": "SAT", "peers": "2", "row_label": "alloc | 1"},
            {"method": "alloc", "node_id": "2", "time_index": 1, "bearer_path": "OPT", "peers": "1", "row_label": "alloc | 2"},
        ]
    )
    fig = module._plot_selected_node_bearer_timeline(timeline_df)
    assert len(fig.data) == 2
    assert fig.layout.legend.title.text == "Bearer"
    assert fig.layout.yaxis.categoryarray == ("alloc | 2", "alloc | 1")

    warnings: list[str] = []
    module.st = SimpleNamespace(
        warning=warnings.append,
        session_state={"show_terrain": False},
    )
    monkeypatch.setattr(module, "_cloud_heatmap_layers", lambda: [])
    monkeypatch.setattr(module, "_trajectory_trace_layers", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "_topology_link_layers", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(module, "_build_map_label_layers", lambda *_args, **_kwargs: ["labels"])

    missing_layers = module.create_layers_geomap(
        ["satcom_link"],
        pd.DataFrame({"flight_id": ["1"], "long": [0.0]}),
        pd.DataFrame(),
        {},
    )
    assert missing_layers == []
    assert warnings == ["Missing required columns for map view: ['lat', 'alt']."]

    current_positions = pd.DataFrame(
        {
            "flight_id": ["1"],
            "id_col": ["1"],
            "long": [0.0],
            "lat": [10.0],
            "alt": [100.0],
            "bearing_deg": [45.0],
            "color": [[1, 2, 3, 255]],
        }
    )
    df = current_positions.copy()
    plane_layers = module.create_layers_geomap(
        ["satcom_link"],
        df,
        current_positions,
        {"satcom_link": "rgb(1,2,3)"},
        marker_style="Plane",
        show_node_labels=True,
    )
    assert plane_layers[-2].type == "IconLayer"
    assert plane_layers[-1] == "labels"


def test_view_maps_network_layout_and_tuple_helpers(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    warnings: list[str] = []
    module.st = SimpleNamespace(warning=warnings.append)

    spiral = module.spiral_layout(module.nx.path_graph(["A", "B", "C"]), scale=2.0, center=(1.0, 2.0))
    assert set(spiral) == {"A", "B", "C"}
    assert spiral["A"] == (1.0, 2.0)

    spring_layout = module.get_fixed_layout(pd.DataFrame({"flight_id": ["A", "B", "C"]}), layout="spring")
    assert set(spring_layout) == {"A", "B", "C"}
    with pytest.raises(ValueError, match="Unsupported layout type"):
        module.get_fixed_layout(pd.DataFrame({"flight_id": ["A"]}), layout="unknown")

    assert module.convert_to_tuples("[(1, 2), (2, 3)]") == [(1, 2), (2, 3)]
    assert module.convert_to_tuples((1, 2)) == [(1, 2)]
    assert module.convert_to_tuples([(1, 2), (2, 3)]) == [(1, 2), (2, 3)]
    assert module.convert_to_tuples("not-a-list") == []
    assert module.convert_to_tuples(123) == []
    assert len(warnings) == 2


def test_view_maps_network_handles_settings_and_active_app_error_paths(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    errors: list[str] = []

    def stop_now():
        raise RuntimeError("stop")

    module.st = SimpleNamespace(error=errors.append, stop=stop_now, session_state={})
    monkeypatch.setattr(module.sys, "argv", [MODULE_PATH.name, "--active-app", str(tmp_path / "missing_app")])

    with pytest.raises(RuntimeError, match="stop"):
        module._resolve_active_app()

    assert any("Provided --active-app path not found" in message for message in errors)

    invalid_settings = tmp_path / "invalid.toml"
    invalid_settings.write_text("[broken", encoding="utf-8")
    module.st = SimpleNamespace(session_state={})
    module._ensure_app_settings_loaded(SimpleNamespace(app_settings_file=invalid_settings))
    assert module.st.session_state["app_settings"] == {}

    module.st = SimpleNamespace(session_state={"app_settings": {"view_maps_network": "bad"}})
    assert module._get_view_maps_settings() == {}
    assert module.st.session_state["app_settings"]["view_maps_network"] == {}

    persist_path = tmp_path / "persist.toml"
    module.st = SimpleNamespace(session_state={"app_settings": "bad"})
    module._persist_app_settings(SimpleNamespace(app_settings_file=persist_path))
    assert not persist_path.exists()

    warnings: list[str] = []
    module.st = SimpleNamespace(session_state={"app_settings": {"view_maps_network": {}}})
    monkeypatch.setattr(module.logger, "warning", lambda message: warnings.append(message))
    monkeypatch.setattr(
        module,
        "_dump_toml",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cannot write")),
    )
    module._persist_app_settings(SimpleNamespace(app_settings_file=tmp_path / "nested" / "persist.toml"))
    assert any("Unable to persist app_settings" in message for message in warnings)


def test_view_maps_network_unexpected_helper_errors_propagate(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        "[view_maps_network]\n"
        'dataset_base_choice = "AGI_CLUSTER_SHARE"\n',
        encoding="utf-8",
    )

    module.st = SimpleNamespace(session_state={})
    monkeypatch.setattr(
        module.tomllib,
        "load",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("bad load")),
    )
    with pytest.raises(TypeError, match="bad load"):
        module._ensure_app_settings_loaded(SimpleNamespace(app_settings_file=settings_path))

    warnings: list[str] = []
    module.st = SimpleNamespace(session_state={"app_settings": {"view_maps_network": {}}})
    monkeypatch.setattr(module.logger, "warning", lambda message: warnings.append(message))
    monkeypatch.setattr(
        module,
        "_dump_toml",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad dump")),
    )
    module._persist_app_settings(SimpleNamespace(app_settings_file=tmp_path / "persist.toml"))
    assert any("Unable to persist app_settings" in message and "bad dump" in message for message in warnings)

    class _BadBase:
        def exists(self) -> bool:
            raise TypeError("bad exists")

    with pytest.raises(TypeError, match="bad exists"):
        module._list_subdirectories(_BadBase())


def test_view_maps_network_heatmap_loader_error_paths(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    with pytest.raises(FileNotFoundError):
        module._load_cloud_heatmap_points(str(tmp_path / "missing.npz"))
    with pytest.raises(FileNotFoundError):
        module._load_cloud_heatmap_grid(str(tmp_path / "missing.npz"))

    no_heatmap = tmp_path / "no_heatmap.npz"
    np.savez(no_heatmap, x_min=np.asarray(0.0), z_min=np.asarray(0.0), step=np.asarray(1.0), center=np.asarray([0.0, 0.0]))
    with pytest.raises(ValueError, match="Missing 'heatmap'"):
        module._load_cloud_heatmap_points(str(no_heatmap))
    with pytest.raises(ValueError, match="Missing 'heatmap'"):
        module._load_cloud_heatmap_grid(str(no_heatmap))

    missing_step = tmp_path / "missing_step.npz"
    np.savez(
        missing_step,
        heatmap=np.asarray([[1.0]], dtype=np.float32),
        x_min=np.asarray(0.0),
        z_min=np.asarray(0.0),
        center=np.asarray([0.0, 0.0]),
    )
    with pytest.raises(ValueError, match="Missing required key"):
        module._load_cloud_heatmap_points(str(missing_step))
    with pytest.raises(ValueError, match="Missing required key"):
        module._load_cloud_heatmap_grid(str(missing_step))

    bad_shape = tmp_path / "bad_shape.npz"
    np.savez(
        bad_shape,
        heatmap=np.asarray([1.0, 2.0], dtype=np.float32),
        x_min=np.asarray(0.0),
        z_min=np.asarray(0.0),
        step=np.asarray(1.0),
        center=np.asarray([0.0, 0.0]),
    )
    with pytest.raises(ValueError, match="Expected 2D heatmap"):
        module._load_cloud_heatmap_points(str(bad_shape))
    with pytest.raises(ValueError, match="Expected 2D heatmap"):
        module._load_cloud_heatmap_grid(str(bad_shape))

    bad_center = tmp_path / "bad_center.npz"
    np.savez(
        bad_center,
        heatmap=np.asarray([[1.0]], dtype=np.float32),
        x_min=np.asarray(0.0),
        z_min=np.asarray(0.0),
        step=np.asarray(1.0),
        center=np.asarray([0.0]),
    )
    with pytest.raises(ValueError, match="Invalid center"):
        module._load_cloud_heatmap_points(str(bad_center))
    with pytest.raises(ValueError, match="Invalid center"):
        module._load_cloud_heatmap_grid(str(bad_center))

    zero_heatmap = tmp_path / "zero_heatmap.npz"
    _write_heatmap_npz(zero_heatmap, heatmap=np.zeros((2, 2), dtype=np.float32))
    assert module._load_cloud_heatmap_points(str(zero_heatmap), min_weight=0.1).empty

    invalid_coords = tmp_path / "invalid_coords.npz"
    _write_heatmap_npz(
        invalid_coords,
        heatmap=np.asarray([[3.0]], dtype=np.float32),
        center=(module.EARTH_RADIUS_M * 4.0, module.EARTH_RADIUS_M * 4.0),
    )
    assert module._load_cloud_heatmap_points(str(invalid_coords), stride=1, min_weight=0.0).empty


def test_view_maps_network_heatmap_stats_and_timeline_edge_cases(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    monkeypatch.setattr(
        module,
        "_load_cloud_heatmap_grid",
        lambda _path: (_ for _ in ()).throw(RuntimeError("broken grid")),
    )
    failed_stats = module._sample_cloud_heatmap_stats("broken.npz", 0.0, 0.0)
    assert all(math.isnan(value) for value in failed_stats.values())

    monkeypatch.setattr(
        module,
        "_load_cloud_heatmap_grid",
        lambda _path: {
            "heatmap": np.asarray([[1.0]], dtype=np.float32),
            "x_min": 0.0,
            "z_min": 0.0,
            "step": 1.0,
            "center_x": 0.0,
            "center_z": 0.0,
        },
    )
    out_of_bounds = module._sample_cloud_heatmap_stats("grid.npz", 45.0, 45.0)
    assert all(math.isnan(value) for value in out_of_bounds.values())

    samples = module._decision_time_samples(
        pd.DataFrame(),
        pd.DataFrame(),
        ["bad", 1],
    )
    assert samples.to_dict("records") == [{"time_index": 1, "sample_time_s": 1.0}]

    assert module._selected_nodes_heatmap_timeline(
        pd.DataFrame({"id_col": ["A"]}),
        "unused.npz",
        {"A"},
    ).empty

    fallback_timeline = pd.DataFrame(
        {
            "node_id": ["A", "A", "A"],
            "map_time": ["bad", "still-bad", "again"],
            "heatmap_value": [1.0, 2.0, 3.0],
        }
    )
    downsampled = module._downsample_heatmap_timeline(fallback_timeline, step_s=2)
    assert downsampled["map_time"].tolist() == ["again", "still-bad"]

    empty_fig = module._plot_selected_nodes_heatmap_timeline(pd.DataFrame(), "SAT")
    assert empty_fig.layout.height == 240

    three_nodes = pd.DataFrame(
        {
            "node_id": ["A", "B", "C"],
            "map_time": [0, 1, 2],
            "heatmap_value": [1.0, 2.0, 3.0],
            "raw_heatmap_value": [1.0, 2.0, 3.0],
            "local_mean": [1.0, 2.0, 3.0],
            "local_max": [1.0, 2.0, 3.0],
            "lat": [10.0, 11.0, 12.0],
            "long": [20.0, 21.0, 22.0],
        }
    )
    multi_fig = module._plot_selected_nodes_heatmap_timeline(three_nodes, "SAT")
    assert "selected planes" in multi_fig.layout.title.text


def test_view_maps_network_layer_helpers_cover_disabled_and_empty_paths(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    warnings: list[str] = []
    module.st = SimpleNamespace(
        session_state={
            "show_cloud_heatmap": False,
            "show_trajectory_traces": False,
            "show_topology_links": False,
        },
        sidebar=SimpleNamespace(warning=warnings.append),
    )

    assert module._cloud_heatmap_layers() == []
    assert module._trajectory_trace_layers(pd.DataFrame({"id_col": ["A"], "long": [1.0], "lat": [2.0]})) == []
    assert module._topology_link_layers(["satcom_link"], pd.DataFrame(), pd.DataFrame(), {}) == []

    module.st = SimpleNamespace(
        session_state={
            "show_cloud_heatmap": True,
            "cloud_heatmap_stride": 1,
            "cloud_heatmap_min_weight": 0.0,
            "cloud_heatmap_sat_path": "sat_map.npz",
            "cloud_heatmap_ivdl_path": "",
            "show_trajectory_traces": True,
            "show_topology_links": True,
        },
        sidebar=SimpleNamespace(warning=warnings.append),
    )
    monkeypatch.setattr(module, "_load_cloud_heatmap_points", lambda *args, **kwargs: pd.DataFrame())
    assert module._cloud_heatmap_layers() == []

    long_track = pd.DataFrame(
        {
            "id_col": ["A"] * 700,
            "time_col": list(range(700)),
            "long": [float(i) for i in range(700)],
            "lat": [float(i) for i in range(700)],
        }
    )
    trace_layers = module._trajectory_trace_layers(long_track)
    assert len(trace_layers) == 1
    assert len(trace_layers[0].data[0]["path"]) == 600

    monkeypatch.setattr(module, "create_edges_geomap", lambda *args, **kwargs: pd.DataFrame())
    assert module._topology_link_layers(["satcom_link"], pd.DataFrame(), pd.DataFrame(), {}) == []
    assert module._svg_data_url("<svg />").startswith("data:image/svg+xml")
    assert module._label_for_link("custom_link") == "CUSTOM"
    assert module._coerce_slider_value(["alpha", "beta"], object()) == "alpha"


def test_view_maps_network_declared_path_and_position_fallbacks(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    base = tmp_path / "share"
    base.mkdir()
    existing_default = base / "existing_default.txt"
    existing_default.write_text("ok", encoding="utf-8")

    assert module._choose_existing_declared_path("missing.txt", "existing_default.txt", [base]) == str(existing_default)
    assert module._choose_existing_declared_path("current_only.txt", "", [base]) == str(base / "current_only.txt")
    assert module._choose_existing_declared_path("", "fallback_only.txt", [base]) == str(base / "fallback_only.txt")
    assert module._choose_existing_declared_path("", "", [base]) == ""
    assert module._resolve_edges_file_path("", [base]) is None

    semantic_from_source = pd.Series({"source_file": str(tmp_path / "uswc_forward_04-S004.csv")})
    assert module._preferred_node_id_from_row(semantic_from_source) == "4004"
    assert module._preferred_node_id_from_row(pd.Series({"node_id": 7})) == "7"
    assert module._preferred_node_id_from_row(pd.Series({}), source_path="plain_name.csv") == ""

    raw_traj = tmp_path / "plain_name.csv"
    pd.DataFrame(
        [
            {"time_s": 0.0, "latitude": 10.0, "longitude": 20.0},
            {"time_s": 1.0, "latitude": 11.0, "longitude": 21.0},
        ]
    ).to_csv(raw_traj, index=False)

    positions = module.load_positions_at_time(str(raw_traj), 0.4)
    assert positions["flight_id"].tolist() == ["plain_name"]
    assert positions["time_s"].tolist() == [0.0]
    assert module.load_positions_at_time("", 0.0).empty


def test_view_maps_network_allocation_and_edge_loader_branches(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    alloc_dict_path = tmp_path / "alloc_dict.json"
    alloc_dict_path.write_text('{"source": "1", "destination": "2", "time_index": 5}', encoding="utf-8")
    loaded_dict = module.load_allocations(alloc_dict_path)
    assert loaded_dict["time_index"].tolist() == [5]
    assert loaded_dict["source"].tolist() == ["1"]

    broken_csv = tmp_path / "broken.csv"
    broken_csv.write_text("source,destination\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(module.pd, "read_csv", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("csv boom")))
    assert module.load_allocations(broken_csv).empty

    broken_parquet = tmp_path / "broken.parquet"
    broken_parquet.write_text("parquet", encoding="utf-8")
    monkeypatch.setattr(module.pd, "read_parquet", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("parquet boom")))
    assert module.load_allocations(broken_parquet).empty

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-json}", encoding="utf-8")
    assert module.load_allocations(bad_json).empty
    assert module.load_allocations(tmp_path / "missing.json").empty

    legacy_ndjson = tmp_path / "edges.ndjson"
    legacy_ndjson.write_text(
        '{"from": "1", "to": "2", "type": "legacy"}\n'
        '{"from": "2", "to": "3", "type": "ivdl"}\n'
        '{"from": "", "to": "4", "type": "satcom"}\n',
        encoding="utf-8",
    )
    assert module.load_edges_file(legacy_ndjson) == {
        "legacy_link": [("1", "2")],
        "ivbl_link": [("2", "3")],
    }

    gml_like_json = tmp_path / "topology.json"
    graph = nx.Graph()
    graph.add_edge("A", "B")
    graph.add_edge("B", "C", bearer="leg")
    nx.write_gml(graph, gml_like_json)
    assert module.load_edges_file(gml_like_json) == {
        "link": [("A", "B")],
        "legacy_link": [("B", "C")],
    }
    assert module.load_edges_file(tmp_path / "missing_edges.json") == {}


def test_view_maps_network_allocation_pair_preview_and_layer_fallback_branches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    alloc_path = tmp_path / "alloc_steps.parquet"
    alloc_path.write_text("alloc", encoding="utf-8")
    allocation_rows = pd.DataFrame(
        [
            {"source": "1", "destination": "2", "routed": "off", "path": [("1", "2")]},
            {"source": "1", "destination": "2", "routed": False, "path": [("1", "2")]},
            {"source": "1", "destination": "2", "routed": 0, "path": [("1", "2")]},
            {"source": "1", "destination": "2", "routed": True, "path": [("1",)]},
            {"source": "1", "destination": "1", "routed": True, "path": [("1", "1")]},
            {"source": "1", "destination": "2", "routed": True, "bearers": []},
            {"source": "2", "destination": "3", "routed": True, "path": [("2", "3")]},
            {"source": "1", "destination": "2", "routed": True, "bearers": ["satcom"]},
        ]
    )
    monkeypatch.setattr(module, "load_allocations", lambda _path: allocation_rows)
    monkeypatch.setattr(
        module,
        "_filter_allocation_rows_for_selected_nodes",
        lambda df, *_args, **_kwargs: df,
    )

    assert module._allocation_routed_edge_pairs({"1", "2", "3"}, allocation_paths=[alloc_path]) == {
        ("1", "2"),
        ("2", "3"),
    }

    assert module._preview_edge_count(pd.DataFrame({"edge_col": [None, np.nan, " "]}), "edge_col") == 0
    monkeypatch.setattr(
        module,
        "convert_to_tuples",
        lambda _value: (_ for _ in ()).throw(ValueError("bad tuples")),
    )
    assert module._preview_edge_count(pd.DataFrame({"edge_col": ["[(1, 2)]"]}), "edge_col") == 0

    assert module.build_allocation_layers(pd.DataFrame(), pd.DataFrame({"flight_id": []})) == []

    positions = pd.DataFrame(
        {
            "flight_id": ["1", "2"],
            "long": [1.0, 2.0],
            "lat": [10.0, 20.0],
            "alt": [100.0, 200.0],
        }
    )
    ivdl_layers = module.build_allocation_layers(
        pd.DataFrame(
            [
                {
                    "source": "1",
                    "destination": "2",
                    "bandwidth": 3.0,
                    "delivered_bandwidth": 0.0,
                    "bearers": ["ivdl"],
                }
            ]
        ),
        positions,
    )
    assert len(ivdl_layers) == 1
    assert ivdl_layers[0].data[0]["color"] == [255, 140, 0]
    assert ivdl_layers[0].data[0]["width"] == 2


def test_view_maps_network_pair_timeline_plot_and_graph_metric_branches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    assert module._selected_pair_bearer_timeline(pd.DataFrame(), {"1", "2"}, "RL").empty
    assert module._selected_pair_bearer_timeline(pd.DataFrame({"time_index": [1]}), {"1", "2"}, "RL").empty

    pair_df = pd.DataFrame(
        [
            {
                "time_index": 1,
                "source": "1",
                "destination": "2",
                "bearers": ["satcom"],
                "routed": True,
                "delivered_bandwidth": 3.0,
                "latency": 10.0,
            },
            {
                "time_index": 1,
                "source": "1",
                "destination": "2",
                "bearers": ["optical"],
                "routed": True,
                "delivered_bandwidth": 2.0,
                "latency": 20.0,
            },
            {
                "time_index": 2,
                "source": "1",
                "destination": "2",
                "bearers": None,
                "routed": False,
                "delivered_bandwidth": 0.0,
                "latency": 30.0,
            },
            {
                "time_index": np.nan,
                "source": "1",
                "destination": "2",
                "bearers": ["satcom"],
                "routed": True,
            },
            {
                "time_index": 3,
                "source": "",
                "destination": "2",
                "bearers": ["satcom"],
                "routed": True,
            },
        ]
    )
    timeline = module._selected_pair_bearer_timeline(pair_df, {"1", "2"}, "RL")
    assert timeline.to_dict("records") == [
        {
            "method": "RL",
            "pair_label": "1 → 2",
            "time_index": 1,
            "bearer_state": "SAT",
            "bearer_path": "optical | satcom",
            "routed": True,
            "delivered_bandwidth": 5.0,
            "latency": 15.0,
            "series_label": "RL | 1 → 2",
        },
        {
            "method": "RL",
            "pair_label": "1 → 2",
            "time_index": 2,
            "bearer_state": "Not routed",
            "bearer_path": "",
            "routed": False,
            "delivered_bandwidth": 0.0,
            "latency": 30.0,
            "series_label": "RL | 1 → 2",
        },
    ]

    focus_df = pd.DataFrame(
        [{"time_index": 4, "source": "3", "destination": "4", "delivered_bandwidth": 7.0, "latency": 9.0}]
    )
    focus_timeline = module._selected_pair_bearer_timeline(focus_df, {"3"}, "custom", focus_pair=(3, 4))
    assert focus_timeline.to_dict("records") == [
        {
            "method": "custom",
            "pair_label": "3 → 4",
            "time_index": 4,
            "bearer_state": "Routed",
            "bearer_path": "",
            "routed": True,
            "delivered_bandwidth": 7.0,
            "latency": 9.0,
            "series_label": "custom | 3 → 4",
        }
    ]

    empty_fig = module._plot_selected_pair_bearer_timeline(pd.DataFrame())
    assert empty_fig.layout.height == 240

    single_pair_fig = module._plot_selected_pair_bearer_timeline(timeline)
    assert single_pair_fig.layout.title.text == "Bearer switching for 1 → 2 over decision steps"

    multi_pair_fig = module._plot_selected_pair_bearer_timeline(pd.concat([timeline, focus_timeline], ignore_index=True))
    assert len(multi_pair_fig.data) == 2
    assert multi_pair_fig.layout.title.text == "Bearer switching for selected source-destination pairs"
    assert multi_pair_fig.layout.legend.title.text == "Method / demand"
    assert multi_pair_fig.data[1].line.color == "#666"
    assert "Routed" in tuple(multi_pair_fig.layout.yaxis.ticktext)

    metrics_df = pd.DataFrame(
        {
            "metric": [
                None,
                np.nan,
                "{'satcom_link': [1, 'bad', 2.5], 'optical_link': 4}",
                {"ivbl_link": {5, "skip"}, "legacy_link": "bad"},
                "not-a-dict",
            ]
        }
    )
    assert module.extract_metrics(metrics_df, "missing") == {}
    assert module.extract_metrics(metrics_df, "metric") == {
        "satcom_link": [1.0, 2.5],
        "optical_link": [4.0],
        "ivbl_link": [5.0],
    }

    graph_df = pd.DataFrame(
        {
            "satcom_link": ["[(1, 2)]"],
            "capacity_metric": [{"satcom_link": [4.0]}],
        }
    )
    pos = {"1": (0.0, 0.0), "2": (1.0, 1.0)}
    fig = module.create_network_graph(
        graph_df,
        pos,
        True,
        True,
        ["satcom_link"],
        "capacity_metric",
        color_map={"1": "rgb(1,2,3)", "2": [4, 5, 6, 255]},
        symbol_map={"1": "triangle-up", "2": "circle"},
        link_color_map={"satcom_link": "rgb(10,20,30)"},
        node_roles={"1": "src", "2": "dst"},
        show_node_labels=True,
        allowed_edge_pairs={("1", "2")},
    )
    assert any(trace.name == "SAT" for trace in fig.data)
    assert any(annotation["text"] == "<b>src</b>" for annotation in fig.layout.annotations)
    assert any(annotation["text"] == "<b>dst</b>" for annotation in fig.layout.annotations)

    monkeypatch.setattr(module, "normalize_values", lambda _metrics: {"satcom_link": ["bad"]})
    fallback_width_fig = module.create_network_graph(
        graph_df,
        pos,
        False,
        True,
        ["satcom_link"],
        "capacity_metric",
        link_color_map={"satcom_link": "rgb(10,20,30)"},
    )
    assert fallback_width_fig.data[0].line.width == 5.0


def test_view_maps_network_layout_color_and_shift_time_branches(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    layout_df = pd.DataFrame({"flight_id": ["A", "B", "C"]})
    for layout_name in ("bipartite", "circular", "planar", "random", "rescale", "shell", "spiral"):
        layout = module.get_fixed_layout(layout_df, layout=layout_name)
        assert set(layout) == {"A", "B", "C"}

    assert module._color_to_rgb("red")[:3] == [255, 0, 0]
    monkeypatch.setattr(
        module.mcolors,
        "to_rgba",
        lambda _color: (_ for _ in ()).throw(ValueError("bad color")),
    )
    fallback_color = module._color_to_rgb("not-a-real-color", idx=3)
    assert len(fallback_color) == 4
    assert fallback_color[-1] == 255

    module.st = SimpleNamespace(session_state={})
    module._shift_selected_time(+1)
    assert module.st.session_state == {}

    module.st = SimpleNamespace(
        session_state={
            module.TIME_OPTIONS_KEY: [10, 20, 30],
            module.TIME_VALUE_KEY: 20,
        }
    )
    module._shift_selected_time(+1)
    assert module.st.session_state[module.TIME_INDEX_KEY] == 2
    assert module.st.session_state[module.TIME_VALUE_KEY] == 30

    module.st = SimpleNamespace(
        session_state={
            module.TIME_OPTIONS_KEY: [10, 20, 30],
            module.TIME_VALUE_KEY: "missing",
        }
    )
    module._shift_selected_time(-1)
    assert module.st.session_state[module.TIME_INDEX_KEY] == 1
    assert module.st.session_state[module.TIME_VALUE_KEY] == 20


def test_view_maps_network_graph_path_and_state_helper_edge_branches(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    graph_df = pd.DataFrame(
        {
            "satcom_link": ["[(1, 1), (1, 99), (1, 2)]"],
            "capacity_metric": [{"satcom_link": [4.0]}],
        }
    )
    fig = module.create_network_graph(
        graph_df,
        {"1": (0.0, 0.0), "2": (1.0, 1.0)},
        True,
        True,
        ["optical_link", "satcom_link"],
        "capacity_metric",
        color_map={"1": "#123456", "2": "#654321"},
        symbol_map={"1": "circle", "2": "circle"},
        link_color_map={"satcom_link": "#abcdef", "optical_link": "#000000"},
    )
    sat_traces = [trace for trace in fig.data if trace.name == "SAT"]
    assert len(sat_traces) == 1

    metrics_df = pd.DataFrame(
        {
            "metric": [
                ["not", "a", "dict"],
                {"satcom_link": None, "optical_link": [1, "bad", 2]},
                {"legacy_link": float("nan")},
            ]
        }
    )
    assert module.extract_metrics(metrics_df, "metric") == {"optical_link": [1.0, 2.0]}
    assert module.normalize_values({}) == {}

    module.st = SimpleNamespace(
        session_state={
            module.TIME_OPTIONS_KEY: [10, 20, 30],
            module.TIME_VALUE_KEY: 20,
            "widget_value": "copied",
        }
    )
    module.increment_time()
    module.decrement_time()
    module.update_var("copied_value", "widget_value")
    assert module.st.session_state[module.TIME_INDEX_KEY] == 1
    assert module.st.session_state[module.TIME_VALUE_KEY] == 20
    assert module.st.session_state["copied_value"] == "copied"


def test_view_maps_network_path_fallback_and_resolution_exception_branches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    duplicate_file = tmp_path / "allocations_steps.json"
    duplicate_file.write_text("{}", encoding="utf-8")

    cloud_root = tmp_path / "cloud_root"
    cloud_file = cloud_root / "dataset" / "sat_map.npz"
    cloud_file.parent.mkdir(parents=True, exist_ok=True)
    _write_heatmap_npz(cloud_file)

    original_resolve = Path.resolve
    original_iterdir = Path.iterdir

    def _patched_resolve(self: Path, strict: bool = False):
        if self == duplicate_file or self == cloud_file:
            raise RuntimeError("resolve failure")
        if self.name == "pipeline" and self.parent == tmp_path / "alloc_base":
            raise RuntimeError("resolve failure")
        return original_resolve(self, strict=strict)

    def _patched_iterdir(self: Path):
        if self == cloud_root:
            raise RuntimeError("iterdir failure")
        return original_iterdir(self)

    monkeypatch.setattr(Path, "resolve", _patched_resolve)
    monkeypatch.setattr(Path, "iterdir", _patched_iterdir)

    assert module._candidate_files_from_globs([str(duplicate_file), str(duplicate_file)]) == [duplicate_file]
    assert module._candidate_cloudmap_paths([cloud_root], ("sat_map.npz",)) == [cloud_file]

    alloc_base = tmp_path / "alloc_base"
    alloc_base.mkdir()
    preferred_root, roots = module._allocation_search_roots(
        base_path=alloc_base,
        datadir_path=alloc_base,
        export_base=alloc_base,
        local_share_root=tmp_path,
        target_name="",
    )
    assert preferred_root == alloc_base
    assert roots
    assert len(roots) == len({str(path) for path in roots})

    assert module._semantic_node_id_from_text("node_" + ("9" * 5000)) is None


def test_view_maps_network_traj_heatmap_and_edge_geomap_fallback_branches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    current_positions = pd.DataFrame(
        {
            "flight_id": ["1", "2"],
            "long": [0.0, 1.0],
            "lat": [10.0, 11.0],
            "alt": [100.0, 200.0],
        }
    )
    assert module.create_edges_geomap(pd.DataFrame({"flight_id": ["1"]}), "satcom_link", current_positions).empty

    geomap_df = pd.DataFrame(
        {
            "flight_id": ["1", "1", "1"],
            "satcom_link": [None, "not-a-list", ("1", "2")],
            "long": [0.0, 0.0, 0.0],
            "lat": [10.0, 10.0, 10.0],
            "alt": [100.0, 100.0, 100.0],
        }
    )
    assert module.create_edges_geomap(
        geomap_df.copy(),
        "satcom_link",
        current_positions,
        allowed_edge_pairs={("2", "3")},
    ).empty

    monkeypatch.setattr(
        module,
        "_sample_cloud_heatmap_stats",
        lambda *_args, **_kwargs: {
            "raw_value": 1.0,
            "proxy_value": 2.0,
            "local_mean": 1.5,
            "local_max": 2.5,
        },
    )
    assert module._selected_nodes_heatmap_timeline(
        pd.DataFrame({"id_col": ["A"], "time_col": [0], "lat": [1.0], "long": [2.0]}),
        "heatmap.npz",
        {"missing"},
    ).empty
    assert module._selected_nodes_heatmap_timeline(
        pd.DataFrame({"id_col": ["A"], "time_col": [0], "lat": ["bad"], "long": [2.0]}),
        "heatmap.npz",
        {"A"},
    ).empty

    many_points = pd.DataFrame(
        {
            "id_col": ["A"] * 25,
            "time_col": list(range(25)),
            "lat": [float(i) for i in range(25)],
            "long": [float(i) for i in range(25)],
        }
    )
    sampled = module._selected_nodes_heatmap_timeline(
        many_points,
        "heatmap.npz",
        {"A"},
        max_points_per_node=20,
    )
    assert len(sampled) == 20

    assert module._load_traj_file(str(tmp_path / "missing.csv")).empty

    broken_parquet = tmp_path / "broken.parquet"
    broken_parquet.write_text("broken", encoding="utf-8")
    monkeypatch.setattr(
        module.pd,
        "read_parquet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broken parquet")),
    )
    assert module._load_traj_file(str(broken_parquet)).empty

    broken_csv = tmp_path / "broken.csv"
    broken_csv.write_text("col\n1\n", encoding="utf-8")
    monkeypatch.setattr(
        module.pd,
        "read_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broken csv")),
    )
    assert module._load_traj_file(str(broken_csv)).empty


def test_view_maps_network_allocation_normalization_branches(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    assert module._coerce_alloc_time_index(pd.DataFrame()).empty

    no_step = module._coerce_alloc_time_index(pd.DataFrame({"value": [1, 2]}))
    assert no_step["time_index"].tolist() == [0, 0]

    non_numeric = module._coerce_alloc_time_index(pd.DataFrame({"time_index": ["bad", "still-bad"]}))
    assert non_numeric["time_index"].tolist() == [0, 1]

    assert module._normalize_allocations_frame(pd.DataFrame()).empty

    normalized = module._normalize_allocations_frame(
        pd.DataFrame(
            {
                "SRC": ["1"],
                "DST": ["2"],
                "Time": ["3.5"],
            }
        )
    )
    assert normalized["source"].tolist() == ["1"]
    assert normalized["destination"].tolist() == ["2"]
    assert normalized["t_now_s"].tolist() == [3.5]


def test_view_maps_network_misc_state_and_picker_helpers(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    module.st = SimpleNamespace(
        session_state={
            "df_file": "stale.csv",
            "csv_files": ["stale.csv"],
            "datadir_widget": "/tmp/data",
        }
    )
    module.update_datadir("datadir", "datadir_widget")
    assert module.st.session_state["datadir"] == "/tmp/data"
    assert "df_file" not in module.st.session_state
    assert "csv_files" not in module.st.session_state

    assert module._coerce_slider_value([1, 5, 9], "4") == 5
    assert module._coerce_slider_value([1, "bad"], 4) == 1
    assert module._coerce_slider_value(
        [pd.Timestamp("2024-01-01"), "bad"],
        "2024-01-03",
    ) == pd.Timestamp("2024-01-01")

    assert module._quick_share_edges_paths(tmp_path / "missing_share") == []

    share_root = tmp_path / "share_root"
    visible_root = share_root / "network_sim" / "pipeline"
    hidden_root = share_root / ".hidden" / "pipeline"
    visible_root.mkdir(parents=True)
    hidden_root.mkdir(parents=True)
    visible_topology = visible_root / "topology.json"
    hidden_topology = hidden_root / "topology.json"
    visible_topology.write_text("{}", encoding="utf-8")
    hidden_topology.write_text("{}", encoding="utf-8")
    quick_paths = module._quick_share_edges_paths(share_root)
    assert visible_topology in quick_paths
    assert hidden_topology not in quick_paths

    positions = pd.DataFrame(
        {
            "flight_id": ["1", "2"],
            "long": [0.0, 1.0],
            "lat": [10.0, 11.0],
            "alt": [100.0, 200.0],
        }
    )
    skipped_layers = module.build_allocation_layers(
        pd.DataFrame(
            [
                {"source": "1", "destination": "2", "path": "[['1']]", "bearers": "['legacy']"},
                {"source": "1", "destination": "9", "bandwidth": 1.0, "delivered_bandwidth": 2.0},
            ]
        ),
        positions,
    )
    assert skipped_layers == []


def test_view_maps_network_settings_and_directory_fallback_branches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    fake_module_path = (
        tmp_path
        / "repo"
        / "src"
        / "agilab"
        / "apps-pages"
        / "view_maps_network"
        / "view_maps_network.py"
    )
    fake_module_path.parent.mkdir(parents=True)
    fake_module_path.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(fake_module_path))
    monkeypatch.setattr(module.sys, "path", [])
    module._ensure_repo_on_path()
    assert str(fake_module_path.parents[3]) in module.sys.path
    assert str(fake_module_path.parents[4]) in module.sys.path

    broken_settings = tmp_path / "broken.toml"
    broken_settings.write_text("{ not = toml", encoding="utf-8")
    module.st = SimpleNamespace(session_state={})
    module._ensure_app_settings_loaded(SimpleNamespace(app_settings_file=broken_settings))
    assert module.st.session_state["app_settings"] == {}

    module.st = SimpleNamespace(
        session_state={"app_settings": {"view_maps_network": "bad", "pages": "bad"}},
    )
    assert module._get_view_maps_settings() == {}
    assert module._get_view_maps_page_settings() == {}
    assert module._coerce_str_list(123) == ["123"]
    assert module._get_setting_list([{"paths": "a"}, "ignored"], "paths") == ["a"]

    warnings: list[str] = []
    module.st = SimpleNamespace(
        session_state={},
        sidebar=SimpleNamespace(warning=warnings.append),
    )
    scan_root = tmp_path / "scan_root"
    scan_root.mkdir()
    monkeypatch.setattr(
        type(scan_root),
        "iterdir",
        lambda self: (_ for _ in ()).throw(OSError("scan failed")),
        raising=False,
    )
    assert module._list_subdirectories(scan_root) == []
    assert warnings == [f"Unable to list directories under {scan_root}: scan failed"]


def test_view_maps_network_visual_helper_fallback_branches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    warnings: list[str] = []
    module.st = SimpleNamespace(
        session_state={
            "show_cloud_heatmap": False,
            "show_trajectory_traces": False,
        },
        sidebar=SimpleNamespace(warning=warnings.append),
    )
    assert module._cloud_heatmap_layers() == []

    module.st.session_state.update(
        {
            "show_cloud_heatmap": True,
            "cloud_heatmap_stride": 2,
            "cloud_heatmap_min_weight": 0.1,
            "cloud_heatmap_sat_path": "",
            "cloud_heatmap_ivdl_path": "ivdl_map.npz",
        }
    )
    monkeypatch.setattr(
        module,
        "_load_cloud_heatmap_points",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )
    assert module._cloud_heatmap_layers() == []
    assert warnings == []

    invalid_stats = module._sample_cloud_heatmap_stats("missing.npz", float("nan"), 0.0)
    assert all(math.isnan(value) for value in invalid_stats.values())

    monkeypatch.setattr(
        module,
        "_load_cloud_heatmap_grid",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broken grid")),
    )
    broken_grid_stats = module._sample_cloud_heatmap_stats("broken.npz", 0.0, 0.0)
    assert all(math.isnan(value) for value in broken_grid_stats.values())

    monkeypatch.setattr(
        module,
        "_load_cloud_heatmap_grid",
        lambda *_args, **_kwargs: {
            "heatmap": np.ones((1, 1), dtype=np.float32),
            "x_min": 0.0,
            "z_min": 0.0,
            "step": 1.0,
            "center_x": 0.0,
            "center_z": 0.0,
        },
    )
    out_of_bounds_stats = module._sample_cloud_heatmap_stats("grid.npz", 90.0, 180.0)
    assert all(math.isnan(value) for value in out_of_bounds_stats.values())

    monkeypatch.setattr(
        module,
        "_load_cloud_heatmap_grid",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("bad grid")),
    )
    with pytest.raises(TypeError, match="bad grid"):
        module._sample_cloud_heatmap_stats("grid.npz", 0.0, 0.0)

    assert module._selected_nodes_heatmap_timeline(None, "heatmap.npz", {"A"}).empty
    assert module._selected_nodes_heatmap_timeline(
        pd.DataFrame({"id_col": ["A"], "time_col": [0], "lat": [np.nan], "long": [1.0]}),
        "heatmap.npz",
        {"A"},
    ).empty

    no_time_df = pd.DataFrame({"node_id": ["A"], "value": [1]})
    assert module._downsample_heatmap_timeline(no_time_df, step_s=3).equals(no_time_df)

    text_timeline = pd.DataFrame(
        {
            "node_id": ["A", "A"],
            "map_time": ["t0", "t1"],
            "heatmap_value": [1.0, 2.0],
            "raw_heatmap_value": [1.0, 2.0],
            "local_mean": [1.0, 1.5],
            "local_max": [1.0, 2.0],
            "lat": [1.0, 1.1],
            "long": [2.0, 2.1],
        }
    )
    downsampled_text = module._downsample_heatmap_timeline(text_timeline, step_s=2)
    assert downsampled_text["map_time"].tolist() == ["t0"]

    single_plane_fig = module._plot_selected_nodes_heatmap_timeline(text_timeline, "SAT")
    assert single_plane_fig.layout.title.text == "SAT cloud intensity proxy at plane A over trajectory time"

    multi_plane_timeline = pd.concat(
        [
            text_timeline.iloc[[0]].assign(node_id="A"),
            text_timeline.iloc[[0]].assign(node_id="B"),
            text_timeline.iloc[[0]].assign(node_id="C"),
        ],
        ignore_index=True,
    )
    multi_plane_fig = module._plot_selected_nodes_heatmap_timeline(multi_plane_timeline, "IVDL")
    assert multi_plane_fig.layout.title.text == "IVDL cloud intensity proxy at selected planes over trajectory time"

    assert module._trajectory_trace_layers(pd.DataFrame({"id_col": ["A"], "long": [1.0], "lat": [2.0]})) == []
    module.st.session_state["show_trajectory_traces"] = True
    assert module._trajectory_trace_layers(pd.DataFrame({"id_col": ["A"]})) == []
    assert module._trajectory_trace_layers(
        pd.DataFrame({"id_col": ["A"], "time_col": [0], "long": ["bad"], "lat": [2.0]})
    ) == []
    assert module._trajectory_trace_layers(
        pd.DataFrame({"id_col": ["A"], "time_col": [0], "long": [1.0], "lat": [2.0]})
    ) == []
    traces = module._trajectory_trace_layers(
        pd.DataFrame(
            {
                "id_col": ["A", "A"],
                "long": [1.0, 2.0],
                "lat": [3.0, 4.0],
            }
        )
    )
    assert len(traces) == 1
    assert traces[0].type == "PathLayer"


def test_view_maps_network_path_resolution_fallback_branches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    assert module._candidate_edges_paths([tmp_path / "missing"]) == []

    share_root = tmp_path / "share"
    (share_root / "pipeline").mkdir(parents=True)
    topology_path = share_root / "pipeline" / "topology.gml"
    topology_path.write_text("graph", encoding="utf-8")
    edge_candidates = module._candidate_edges_paths([share_root])
    assert topology_path in edge_candidates

    quick_root = tmp_path / "quick"
    (quick_root / "pipeline").mkdir(parents=True)
    quick_topology = quick_root / "pipeline" / "topology.gml"
    quick_topology.write_text("graph", encoding="utf-8")
    monkeypatch.setattr(
        type(quick_root),
        "iterdir",
        lambda self: (_ for _ in ()).throw(OSError("cannot scan")),
        raising=False,
    )
    assert module._quick_share_edges_paths(quick_root) == [quick_topology]

    data_dir = tmp_path / "data_dir"
    data_dir.mkdir()
    csv_path = tmp_path / "points.csv"
    csv_path.write_text("x\n1\n", encoding="utf-8")
    matched = module._candidate_files_from_globs([str(tmp_path / "*"), str(csv_path)])
    assert csv_path in matched
    assert data_dir not in matched

    expanded = module._expand_glob_patterns([" ", "data/*.csv", "data/*.csv"], [tmp_path])
    assert expanded == [str(tmp_path / "data/*.csv")]

    datetime_calls: list[Any] = []

    def _raise_datetime(*args, **kwargs):
        datetime_calls.append((args, kwargs))
        raise ValueError("bad datetime")

    monkeypatch.setattr(module.pd, "to_datetime", _raise_datetime)
    assert module._coerce_slider_value([pd.Timestamp("2024-01-01")], "2024-01-02") == pd.Timestamp("2024-01-01")
    assert len(datetime_calls) >= 1

    calls = iter([object(), ""])
    monkeypatch.setattr(module, "_resolve_declared_path", lambda *_args, **_kwargs: next(calls))
    assert module._choose_existing_declared_path("broken", "", [share_root]) == ""

    monkeypatch.setattr(module, "_resolve_declared_path", lambda *_args, **_kwargs: object())
    assert module._resolve_edges_file_path("broken", [share_root]) is None


def test_view_maps_network_misc_helper_fallback_branches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    warnings: list[str] = []
    module.st = SimpleNamespace(
        warning=warnings.append,
        sidebar=SimpleNamespace(warning=warnings.append),
        session_state={},
    )

    assert module._candidate_node_ids("") == []
    assert module._coerce_list_cell("(1, 2)") == [1, 2]
    assert module._allocation_visible_node_ids(pd.DataFrame()) == set()
    assert module._allocation_endpoint_roles(
        pd.DataFrame({"source": ["1", "2"], "destination": ["3", "4"]}),
        pd.DataFrame({"other": [1]}),
    ) == {}
    assert module._format_node_label("7") == "7"
    assert module._build_map_label_layers(
        pd.DataFrame({"flight_id": [" "], "long": [1.0], "lat": [2.0], "alt": [0.0]})
    ) == []
    assert module._coerce_numeric_float(float("inf")) is None
    assert module._coerce_numeric_int("bad") is None
    assert module._filter_allocation_rows_for_selected_nodes(pd.DataFrame(), {"1"}).empty
    assert module._filter_allocation_rows_for_selected_nodes(
        pd.DataFrame({"source": ["1"], "destination": ["2"], "time_index": [0]}),
        {"9"},
    ).empty

    alloc_path = tmp_path / "allocations.parquet"
    alloc_path.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(module, "load_allocations", lambda _path: pd.DataFrame())
    assert module._expanded_node_ids_from_allocations({"1"}, allocation_paths=[alloc_path]) == {"1"}
    assert module._endpoint_roles_from_allocations({"1"}, allocation_paths=[alloc_path]) == {}

    monkeypatch.setattr(
        module,
        "load_allocations",
        lambda _path: pd.DataFrame({"source": ["1"], "destination": ["2"], "time_index": [0]}),
    )
    assert module._allocation_routed_edge_pairs({"9"}, allocation_paths=[alloc_path]) == set()

    assert module._candidate_allocation_paths([tmp_path / "missing"]) == []
    assert module._parse_rgb_like(123) is None
    assert module._parse_rgb_like("rgba(10,20,30,200)") == (10, 20, 30, 200)
    monkeypatch.setattr(
        module.mcolors,
        "to_rgba",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad color")),
    )
    assert module._to_plotly_color(object()) == "#888"
    assert module.hex_to_rgba("") == [136, 136, 136, 255]
    assert module.hex_to_rgba("#zzzzzz") == [136, 136, 136, 255]

    assert module.convert_to_tuples("{'bad': 'shape'}") == []
    assert module.convert_to_tuples(5) == []

    class _BoomStr:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    assert module.parse_edges([[(1, 2, 3)], [(_BoomStr(), 2)]]) == []
    assert module.filter_edges(pd.DataFrame({"other": [[(1, 2)]]}), ["missing"]) == {}

    assert module._parse_allocations_cell(({"source": 1},)) == [{"source": 1}]
    assert module._parse_allocations_cell(5) == []
    assert module._drop_index_levels_shadowing_columns(pd.DataFrame()).empty

    blank_jsonl = tmp_path / "allocations.jsonl"
    blank_jsonl.write_text('\n{"source": 1, "destination": 2}\n', encoding="utf-8")
    assert not module.load_allocations(blank_jsonl).empty
    assert module._nearest_row(pd.DataFrame(), 0.0).empty
    assert module._nearest_row(pd.DataFrame({"time_s": ["bad"]}), 0.0).empty
    assert module._find_latest_allocations(tmp_path / "missing_root") is None

    filtered_root = tmp_path / "filtered_root"
    filtered_root.mkdir()
    (filtered_root / "allocations_steps.csv").write_text("source,destination\n1,2\n", encoding="utf-8")
    assert module._find_latest_allocations(filtered_root, include=("baseline",)) is None

    bad_edges = tmp_path / "bad_edges.json"
    bad_edges.write_text('[{"source": "1"}]', encoding="utf-8")
    assert module.load_edges_file(bad_edges) == {}

    custom_edges = tmp_path / "custom_edges.jsonl"
    custom_edges.write_text('{"source": "1", "target": "2", "bearer": "mesh link"}\n', encoding="utf-8")
    assert module.load_edges_file(custom_edges) == {"mesh_link": [("1", "2")]}

    bad_positions = tmp_path / "bad_positions.csv"
    bad_positions.write_text("time_s,flight_id\n0,1\n", encoding="utf-8")
    assert module.load_positions_at_time(str(bad_positions), 0.0).empty

    no_time_positions = tmp_path / "no_time_positions.csv"
    no_time_positions.write_text("time_s,latitude,longitude\nbad,1.0,2.0\n", encoding="utf-8")
    assert module.load_positions_at_time(str(no_time_positions), 0.0).empty

    broken_csv = tmp_path / "encoding.csv"
    broken_csv.write_text("col\n1\n", encoding="utf-8")
    read_csv_calls = {"count": 0}

    def _broken_read_csv(*_args, **_kwargs):
        read_csv_calls["count"] += 1
        if read_csv_calls["count"] == 1:
            raise UnicodeDecodeError("utf-8", b"x", 0, 1, "bad")
        raise RuntimeError("still broken")

    monkeypatch.setattr(module.pd, "read_csv", _broken_read_csv)
    assert module._load_traj_file(str(broken_csv)).empty

    positions = pd.DataFrame({"flight_id": ["1"], "long": [0.0], "lat": [1.0], "alt": [2.0]})
    alloc_df = pd.DataFrame(
        [
            {
                "source": "1",
                "destination": "9",
                "path": '["(\'1\', \'9\')"]',
                "bearers": "['SAT']",
            }
        ]
    )
    assert module.build_allocation_layers(alloc_df, positions) == []

    assert module._bearer_path_label(("SAT", "OPT")) == "SAT → OPT"
    assert module._bearer_tokens(None) == []
    assert module._bearer_tokens("('SAT', 'IVDL')") == ["SAT", "IVDL"]
    assert module._canonical_bearer_state("   ", True) == "Routed"
    assert module._canonical_bearer_state("ivdl", True) == "IVDL"
    assert module._canonical_bearer_state("mesh", True) == "MESH"

    assert module._selected_node_bearer_timeline(pd.DataFrame(), {"1"}, "alloc").empty
    assert module._selected_node_bearer_timeline(
        pd.DataFrame({"time_index": [1]}),
        {"1"},
        "alloc",
    ).empty
    assert module._selected_node_bearer_timeline(
        pd.DataFrame({"time_index": [None], "source": ["1"], "destination": ["2"]}),
        {"1"},
        "alloc",
    ).empty

    assert len(warnings) >= 2


def test_view_maps_network_helper_skip_and_error_branches(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    module.st = SimpleNamespace(
        warning=lambda *_args, **_kwargs: None,
        sidebar=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
        session_state={},
    )

    share_root = tmp_path / "share"
    topology = share_root / "pipeline" / "topology.gml"
    topology.parent.mkdir(parents=True)
    topology.write_text("graph", encoding="utf-8")

    path_type = type(share_root)
    original_iterdir = path_type.iterdir
    original_resolve = path_type.resolve

    def _iterdir_with_duplicate(self):
        if self == share_root:
            return iter([share_root])
        return original_iterdir(self)

    def _resolve_with_failure(self, strict=False):
        if self == topology:
            raise OSError("bad resolve")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(path_type, "iterdir", _iterdir_with_duplicate, raising=False)
    monkeypatch.setattr(path_type, "resolve", _resolve_with_failure, raising=False)
    assert module._quick_share_edges_paths(share_root) == [topology]

    class _BadSeries:
        def head(self, _count):
            raise RuntimeError("boom")

    class _BadFrame:
        columns = ["edge_col"]

        def __getitem__(self, key):
            assert key == "edge_col"
            return _BadSeries()

    assert module._preview_edge_count(_BadFrame(), "edge_col") == 0

    edge_df = pd.DataFrame(
        {
            "satcom_link": [[("1001", "9999")]],
            "flight_id": ["1001"],
            "long": [2.0],
            "lat": [48.0],
            "alt": [1000.0],
        }
    )
    current_positions = pd.DataFrame(
        {
            "flight_id": ["1001"],
            "long": [2.0],
            "lat": [48.0],
            "alt": [1000.0],
        }
    )
    assert module.create_edges_geomap(edge_df, "satcom_link", current_positions).empty

    scalar_alloc = tmp_path / "scalar.json"
    scalar_alloc.write_text("1", encoding="utf-8")
    assert module.load_allocations(scalar_alloc).empty

    row_error_path = tmp_path / "row_error.json"
    row_error_path.write_text("[]", encoding="utf-8")

    class _BadRow:
        def __getitem__(self, _key):
            raise RuntimeError("row access failed")

    class _FakeEdgesFrame:
        columns = ["source", "target", "bearer"]

        def iterrows(self):
            yield 0, _BadRow()

    monkeypatch.setattr(module.pd, "read_json", lambda *_args, **_kwargs: _FakeEdgesFrame())
    assert module.load_edges_file(row_error_path) == {}

    bad_positions = tmp_path / "bad_positions.csv"
    bad_positions.write_text("time_s,flight_id\n0,1\n", encoding="utf-8")
    good_positions = tmp_path / "good_positions.csv"
    good_positions.write_text(
        "time_s,flight_id,latitude,longitude,alt_m\n0,2,48.0,2.0,1000.0\n",
        encoding="utf-8",
    )
    positions = module.load_positions_at_time(f"{bad_positions};{good_positions}", 0.0)
    assert positions["flight_id"].tolist() == ["2"]

    pair_df = pd.DataFrame(
        {
            "source": ["1"],
            "destination": ["2"],
            "time_index": [0],
            "bearers": [["satcom"]],
            "routed": [True],
        }
    )
    assert module._selected_pair_bearer_timeline(pair_df, {"9", "10"}, "RL").empty
    assert module._selected_pair_bearer_timeline(pair_df, {"1", "2"}, "RL", focus_pair=(3, 4)).empty


def test_view_maps_network_main_handles_errors_and_propagates_reruns(monkeypatch, tmp_path: Path) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)

    errors: list[str] = []
    codes: list[str] = []
    module.st = SimpleNamespace(
        error=errors.append,
        caption=lambda _message: None,
        code=lambda message, **_kwargs: codes.append(message),
    )

    def _raise_runtime():
        raise RuntimeError("boom")

    module.page = _raise_runtime
    module.main()

    assert errors == ["An error occurred: boom"]
    assert len(codes) == 1
    assert "RuntimeError: boom" in codes[0]

    module.page = lambda: (_ for _ in ()).throw(module.RerunException(RerunData()))
    with pytest.raises(module.RerunException):
        module.main()


def test_view_maps_network_helper_covers_remaining_fallback_branches(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_view_maps_network_module(monkeypatch, tmp_path)
    module.st = SimpleNamespace(
        warning=lambda *_args, **_kwargs: None,
        sidebar=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
        session_state={
            "show_trajectory_traces": True,
        },
    )

    npz_path = tmp_path / "CloudMapSat.npz"
    _write_heatmap_npz(npz_path)

    original_sort_values = module.pd.DataFrame.sort_values

    def _sort_values_with_selected_failures(self, by=None, *args, **kwargs):
        if by == "time_col":
            raise TypeError("bad timeline sort")
        if by == ["id_col", "time_col"]:
            raise TypeError("bad trajectory sort")
        return original_sort_values(self, by=by, *args, **kwargs)

    monkeypatch.setattr(module.pd.DataFrame, "sort_values", _sort_values_with_selected_failures, raising=False)

    traj_df = pd.DataFrame(
        [
            {"id_col": "1001", "time_col": 1.0, "lat": 48.1, "long": 2.1},
            {"id_col": "1001", "time_col": 0.0, "lat": 48.0, "long": 2.0},
        ]
    )
    timeline = module._selected_nodes_heatmap_timeline(
        traj_df,
        npz_path,
        {"1001"},
        neighborhood_radius_cells=1,
    )
    assert not timeline.empty

    assert module._trajectory_trace_layers(pd.DataFrame()) == []

    layers = module._trajectory_trace_layers(
        pd.DataFrame(
            [
                {"id_col": "1001", "time_col": 1.0, "long": 2.1, "lat": 48.1},
                {"id_col": "1001", "time_col": 0.0, "long": 2.0, "lat": 48.0},
            ]
        )
    )
    assert layers

    empty_alloc_path = tmp_path / "allocations_empty.json"
    empty_alloc_path.write_text("[]", encoding="utf-8")
    assert module._allocation_routed_edge_pairs(
        {"1001", "2002"},
        allocation_paths=[empty_alloc_path],
    ) == set()

    jsonl_alloc_path = tmp_path / "allocations.jsonl"
    jsonl_alloc_path.write_text('\n{"source": 1001, "destination": 2002, "time_index": 0}\n', encoding="utf-8")
    alloc_df = module.load_allocations(jsonl_alloc_path)
    assert alloc_df["source"].tolist() == [1001]

    empty_positions = tmp_path / "positions_empty.csv"
    good_positions = tmp_path / "positions_good.csv"
    empty_positions.write_text("empty", encoding="utf-8")
    good_positions.write_text("good", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_load_traj_file",
        lambda fname: pd.DataFrame()
        if "empty" in str(fname)
        else pd.DataFrame(
            [
                {
                    "time_s": 0.0,
                    "flight_id": "2002",
                    "latitude": 48.0,
                    "longitude": 2.0,
                    "alt_m": 1000.0,
                }
            ]
        ),
    )
    positions = module.load_positions_at_time(f"{empty_positions};{good_positions}", 0.0)
    assert positions["flight_id"].tolist() == ["2002"]

    assert module._canonical_bearer_state("   ", routed=True) == "Routed"
