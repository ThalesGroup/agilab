from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd


PAGE_PATH = (
    "src/agilab/apps-pages/view_maps_network/"
    "src/view_maps_network/view_maps_network.py"
)


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
            heatmap if heatmap is not None else np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
            dtype=np.float32,
        ),
        x_min=np.asarray(x_min, dtype=np.float32),
        z_min=np.asarray(z_min, dtype=np.float32),
        step=np.asarray(step, dtype=np.float32),
        center=np.asarray(center, dtype=np.float32),
    )


def _write_traj_csv(path: Path, *, plane_id: int, plane_label: str, lat: float, lon: float) -> None:
    pd.DataFrame(
        [
            {
                "time_s": 0.0,
                "plane_id": plane_id,
                "plane_label": plane_label,
                "latitude": lat,
                "longitude": lon,
                "alt_m": 1200.0,
            }
        ]
    ).to_csv(path, index=False)


def test_view_maps_network_renders_sb3_style_page_state_without_cloud_or_alloc_warnings(
    tmp_path: Path,
    create_temp_app_project,
    run_page_app_test,
) -> None:
    target_name = "demo_sb3_maps"
    share_root = tmp_path / "clustershare"
    traj_dir = share_root / "flight_trajectory" / "pipeline"
    dataset_dir = share_root / "flight_trajectory" / "dataset"
    topology_dir = share_root / "network_sim" / "pipeline"
    routing_dir = share_root / target_name / "pipeline" / "trainer_routing"
    baseline_dir = share_root / target_name / "pipeline" / "trainer_ilp_stepper"
    for directory in (traj_dir, dataset_dir, topology_dir, routing_dir, baseline_dir):
        directory.mkdir(parents=True, exist_ok=True)

    sat_path = dataset_dir / "CloudMapSat.npz"
    ivdl_path = dataset_dir / "CloudMapIvdl.npz"
    _write_heatmap_npz(sat_path)
    _write_heatmap_npz(ivdl_path)

    traj_a = traj_dir / "uswc_forward_01-S001_2026-04-01_15-27-49.csv"
    traj_b = traj_dir / "uswc_forward_02-S002_2026-04-01_15-27-48.csv"
    _write_traj_csv(traj_a, plane_id=0, plane_label="uswc_forward_01-S001", lat=48.0, lon=2.0)
    _write_traj_csv(traj_b, plane_id=1, plane_label="uswc_forward_02-S002", lat=49.0, lon=3.0)

    topology_path = topology_dir / "ilp_topology.gml"
    graph = nx.Graph()
    graph.add_edge("1001", "2002", bearer="ivbl")
    nx.write_gml(graph, topology_path)

    routing_path = routing_dir / "allocations_steps.parquet"
    pd.DataFrame(
        [
            {
                "source": 1001,
                "destination": 2002,
                "time_index": 0,
                "t_now_s": 0.0,
                "routed": True,
            }
        ]
    ).to_parquet(routing_path, index=False)

    baseline_path = baseline_dir / "allocations_steps.json"
    baseline_path.write_text(
        json.dumps(
            [
                {
                    "source": 1001,
                    "destination": 2002,
                    "time_index": 0,
                    "t_now_s": 0.0,
                    "routed": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    app_settings_text = (
        "[pages.view_maps_network]\n"
        f'dataset_custom_base = "{share_root.as_posix()}"\n'
        f'dataset_subpath = "{target_name}"\n'
        'default_traj_globs = ["flight_trajectory/pipeline/*.csv"]\n'
        'default_allocation_globs = ["pipeline/trainer_routing/allocations_steps.parquet"]\n'
        'default_baseline_globs = ["pipeline/trainer_ilp_stepper/allocations_steps.json"]\n'
        'cloudmap_sat_path = "flight_trajectory/dataset/CloudMapSat.npz"\n'
        'cloudmap_ivdl_path = "flight_trajectory/dataset/CloudMapIvdl.npz"\n'
        "\n"
        "[view_maps_network]\n"
        'base_dir_choice = "Custom"\n'
        f'input_datadir = "{share_root.as_posix()}"\n'
        'datadir_rel = "flight_trajectory"\n'
        'file_ext_choice = "all"\n'
        'df_select_mode = "Regex (multi)"\n'
        'df_file_regex = "pipeline/.*\\\\.csv$"\n'
        'df_files = [\n'
        f'  "{traj_a.relative_to(share_root / "flight_trajectory").as_posix()}",\n'
        f'  "{traj_b.relative_to(share_root / "flight_trajectory").as_posix()}",\n'
        ']\n'
        'id_col = "plane_id"\n'
        'time_col = "time_s"\n'
        'edges_file = "network_sim/pipeline/ilp_topology.gml"\n'
        'show_cloud_heatmap = true\n'
        'show_topology_links = true\n'
        'show_trajectory_traces = true\n'
    )
    project_dir = create_temp_app_project(
        f"{target_name}_project",
        package_name=target_name,
        app_settings_text=app_settings_text,
        pyproject_name=f"{target_name.replace('_', '-')}-project",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export", timeout=30)
    for widget in at.text_input:
        if widget.label == "SAT cloud map (.npz)":
            widget.set_value("stale/CloudMapSat.npz")
        elif widget.label == "IVDL cloud map (.npz)":
            widget.set_value("stale/CloudMapIvdl.npz")
    at.run()

    assert not at.exception
    warnings = [warning.value for warning in at.warning]
    infos = [info.value for info in at.info]
    text_inputs = {widget.label: widget.value for widget in at.text_input}
    selectboxes = {widget.label: widget.value for widget in at.selectbox}
    multiselects = {widget.label: widget.value for widget in at.multiselect}
    captions = [caption.value for caption in at.caption]

    assert not any("cloud map unavailable" in message.lower() for message in warnings)
    assert not any("no allocation exports detected" in message.lower() for message in infos)
    assert text_inputs["SAT cloud map (.npz)"] == str(sat_path)
    assert text_inputs["IVDL cloud map (.npz)"] == str(ivdl_path)
    assert selectboxes["Allocations file picker (routing/policy)"] == str(routing_path)
    assert selectboxes["Baseline allocations file picker"] == str(baseline_path)
    assert multiselects["Link columns"] == ["ivbl_link"]
    assert any("Edge counts (preview): ivbl_link=1" in caption for caption in captions)
    assert any("2 / 2 flights shown" in caption for caption in captions)
    assert any(f"Resolved path: {share_root / 'flight_trajectory'}" == caption for caption in captions)


def test_view_maps_network_page_state_drives_pair_overlay_and_timelines(
    tmp_path: Path,
    create_temp_app_project,
    run_page_app_test,
) -> None:
    target_name = "demo_pair_overlay"
    share_root = tmp_path / "clustershare"
    traj_dir = share_root / "flight_trajectory" / "pipeline"
    dataset_dir = share_root / "flight_trajectory" / "dataset"
    topology_dir = share_root / "network_sim" / "pipeline"
    routing_dir = share_root / target_name / "pipeline" / "trainer_routing"
    baseline_dir = share_root / target_name / "pipeline" / "trainer_ilp_stepper"
    for directory in (traj_dir, dataset_dir, topology_dir, routing_dir, baseline_dir):
        directory.mkdir(parents=True, exist_ok=True)

    sat_path = dataset_dir / "CloudMapSat.npz"
    ivdl_path = dataset_dir / "CloudMapIvdl.npz"
    _write_heatmap_npz(sat_path)
    _write_heatmap_npz(ivdl_path)

    traj_a = traj_dir / "uswc_forward_01-S001_2026-04-01_15-27-49.csv"
    traj_b = traj_dir / "uswc_forward_02-S002_2026-04-01_15-27-48.csv"
    pd.DataFrame(
        [
            {
                "time_s": 0.0,
                "plane_id": 0,
                "plane_label": "uswc_forward_01-S001",
                "latitude": 48.0,
                "longitude": 2.0,
                "alt_m": 1200.0,
            },
            {
                "time_s": 1.0,
                "plane_id": 0,
                "plane_label": "uswc_forward_01-S001",
                "latitude": 48.5,
                "longitude": 2.5,
                "alt_m": 1300.0,
            },
        ]
    ).to_csv(traj_a, index=False)
    pd.DataFrame(
        [
            {
                "time_s": 0.0,
                "plane_id": 1,
                "plane_label": "uswc_forward_02-S002",
                "latitude": 49.0,
                "longitude": 3.0,
                "alt_m": 1400.0,
            },
            {
                "time_s": 1.0,
                "plane_id": 1,
                "plane_label": "uswc_forward_02-S002",
                "latitude": 49.5,
                "longitude": 3.5,
                "alt_m": 1500.0,
            },
        ]
    ).to_csv(traj_b, index=False)

    topology_path = topology_dir / "ilp_topology.gml"
    graph = nx.Graph()
    graph.add_edge("1001", "2002", bearer="ivbl")
    nx.write_gml(graph, topology_path)

    routing_path = routing_dir / "allocations_steps.parquet"
    pd.DataFrame(
        [
            {
                "source": 1001,
                "destination": 2002,
                "time_index": 0,
                "t_now_s": 0.0,
                "routed": True,
                "bearers": ["satcom"],
                "delivered_bandwidth": 2.0,
                "latency": 10.0,
            },
            {
                "source": 1001,
                "destination": 2002,
                "time_index": 1,
                "t_now_s": 1.0,
                "routed": True,
                "bearers": ["optical"],
                "delivered_bandwidth": 4.0,
                "latency": 8.0,
            },
        ]
    ).to_parquet(routing_path, index=False)

    baseline_path = baseline_dir / "allocations_steps.json"
    baseline_path.write_text(
        json.dumps(
            [
                {
                    "source": 1001,
                    "destination": 2002,
                    "time_index": 0,
                    "t_now_s": 0.0,
                    "routed": True,
                    "bearers": ["legacy"],
                    "delivered_bandwidth": 1.0,
                    "latency": 12.0,
                },
                {
                    "source": 1001,
                    "destination": 2002,
                    "time_index": 1,
                    "t_now_s": 1.0,
                    "routed": True,
                    "bearers": ["legacy"],
                    "delivered_bandwidth": 3.0,
                    "latency": 9.0,
                },
            ]
        ),
        encoding="utf-8",
    )

    rel_a = traj_a.relative_to(share_root / "flight_trajectory").as_posix()
    rel_b = traj_b.relative_to(share_root / "flight_trajectory").as_posix()
    app_settings_text = (
        "[pages.view_maps_network]\n"
        f'dataset_custom_base = "{share_root.as_posix()}"\n'
        f'dataset_subpath = "{target_name}"\n'
        'default_traj_globs = ["flight_trajectory/pipeline/*.csv"]\n'
        'default_allocation_globs = ["pipeline/trainer_routing/allocations_steps.parquet"]\n'
        'default_baseline_globs = ["pipeline/trainer_ilp_stepper/allocations_steps.json"]\n'
        'cloudmap_sat_path = "flight_trajectory/dataset/CloudMapSat.npz"\n'
        'cloudmap_ivdl_path = "flight_trajectory/dataset/CloudMapIvdl.npz"\n'
        "\n"
        "[view_maps_network]\n"
        'base_dir_choice = "Custom"\n'
        f'input_datadir = "{share_root.as_posix()}"\n'
        'datadir_rel = "flight_trajectory"\n'
        'file_ext_choice = "all"\n'
        'df_select_mode = "Regex (multi)"\n'
        'df_file_regex = "pipeline/.*\\\\.csv$"\n'
        f'df_file = "{rel_a}"\n'
        "sat_heatmap_plot_step_s = 60\n"
        'selected_flights_filter = ["stale-id"]\n'
        'df_files = [\n'
        f'  "{rel_a}",\n'
        f'  "{rel_b}",\n'
        ']\n'
        'id_col = "plane_id"\n'
        'time_col = "time_s"\n'
        'edges_file = "network_sim/pipeline/ilp_topology.gml"\n'
        'show_cloud_heatmap = true\n'
        'show_topology_links = true\n'
        'show_trajectory_traces = true\n'
    )
    project_dir = create_temp_app_project(
        f"{target_name}_project",
        package_name=target_name,
        app_settings_text=app_settings_text,
        pyproject_name=f"{target_name.replace('_', '-')}-project",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export", timeout=30)
    at.checkbox(key="show_metrics").set_value(True).run()
    at.multiselect(key="view_maps_network:selected_flights_filter").set_value(["1001", "2002"]).run()
    at.selectbox(key="alloc_demand_pair_focus").set_value((1001, 2002)).run()
    at.select_slider(key="view_maps_network:alloc_time_index").set_value(1).run()

    assert not at.exception
    infos = [info.value for info in at.info]
    captions = [caption.value for caption in at.caption]
    selectboxes = {widget.label: widget.value for widget in at.selectbox}
    multiselects = {widget.label: widget.value for widget in at.multiselect}

    assert multiselects["Flights / nodes"] == ["1001", "2002"]
    assert selectboxes["Focus demand (optional)"] == (1001, 2002)
    assert selectboxes["SAT cloud plot step (s)"] == 60
    assert any("Bearer switch detected at time indices: 1" in message for message in infos)
    assert any("Routing allocations at this timestep" in caption for caption in captions)
    assert any("Baseline (ILP) allocations at this timestep" in caption for caption in captions)
    assert any("RL vs ILP (delta delivered_bandwidth)" in caption for caption in captions)


def test_view_maps_network_page_handles_static_time_invalid_regex_and_missing_allocations(
    tmp_path: Path,
    create_temp_app_project,
    run_page_app_test,
) -> None:
    target_name = "demo_static_network"
    share_root = tmp_path / "clustershare"
    datadir = share_root / "flight_trajectory"
    datadir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "plane_label": "1001",
                "time_s": None,
                "latitude": 48.0,
                "longitude": 2.0,
                "throughput": '{"satcom_link": 2.0}',
            },
            {
                "plane_label": "2002",
                "time_s": None,
                "latitude": 48.0,
                "longitude": 2.0,
                "throughput": '{"satcom_link": 3.0}',
            },
            {
                "plane_label": "",
                "time_s": None,
                "latitude": 48.0,
                "longitude": 2.0,
                "throughput": '{"satcom_link": 1.0}',
            },
        ]
    ).to_csv(datadir / "network.csv", index=False)
    (datadir / "broken.json").write_text("{broken", encoding="utf-8")

    app_settings_text = (
        "[view_maps_network]\n"
        'base_dir_choice = "Custom"\n'
        f'input_datadir = "{datadir.as_posix()}"\n'
        'datadir_rel = ""\n'
        'file_ext_choice = "bogus"\n'
        'df_select_mode = "Regex (multi)"\n'
        'df_file_regex = "["\n'
        'df_files = ["network.csv", "broken.json"]\n'
        'id_col = "plane_label"\n'
        'time_col = "time_s"\n'
        'selected_flights_filter = ["1001", "2002"]\n'
        'jitter_overlap = true\n'
        'metric_type_select = "missing"\n'
        'allocations_file = "/tmp/missing-routing.parquet"\n'
        'baseline_allocations_file = "/tmp/missing-baseline.json"\n'
        'traj_glob = "/tmp/missing-traj/*.csv"\n'
    )
    project_dir = create_temp_app_project(
        f"{target_name}_project",
        package_name=target_name,
        app_settings_text=app_settings_text,
        pyproject_name=f"{target_name.replace('_', '-')}-project",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export", timeout=30)

    assert not at.exception
    warnings = [warning.value for warning in at.warning]
    infos = [info.value for info in at.info]
    captions = [caption.value for caption in at.caption]
    errors = [error.value for error in at.error]
    selectboxes = {widget.label: widget.value for widget in at.selectbox}
    multiselects = {widget.label: widget.value for widget in at.multiselect}
    text_inputs = {widget.label: widget.value for widget in at.text_input}

    assert any("Invalid regex" in message for message in errors)
    assert any("Some selected files failed to load" in message for message in warnings)
    assert any("No valid timestamps found in 'time_s'" in message for message in warnings)
    assert any("Dropped 1 rows with missing node IDs." in message for message in warnings)
    assert any("Allocations file not found" in message for message in infos)
    assert any("Baseline allocations file not found" in message for message in infos)
    assert any("No allocation rows found for the selected flights/nodes." in message for message in infos)
    assert any("Loaded allocation files:" in caption for caption in captions)
    assert multiselects["Flights / nodes"] == ["1001", "2002"]
    assert selectboxes["Edge width metric (optional)"] == "(none)"
    assert text_inputs["Custom allocations file path"] == "/tmp/missing-routing.parquet"
    assert text_inputs["Custom baseline allocations file path"] == "/tmp/missing-baseline.json"
    assert text_inputs["Custom trajectory glob(s)"] == "/tmp/missing-traj/*.csv"


def test_view_maps_network_page_graph_only_keeps_sparse_nodes_visible(
    tmp_path: Path,
    create_temp_app_project,
    run_page_app_test,
) -> None:
    target_name = "demo_graph_layout"
    share_root = tmp_path / "clustershare"
    datadir = share_root / "flight_trajectory"
    topology_dir = share_root / "network_sim" / "pipeline"
    datadir.mkdir(parents=True, exist_ok=True)
    topology_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {"plane_id": 1, "time_s": 0.0, "latitude": 48.0, "longitude": 2.0},
            {"plane_id": 2, "time_s": 0.0, "latitude": 48.1, "longitude": 2.1},
            {"plane_id": 3, "time_s": 1.0, "latitude": 48.2, "longitude": 2.2},
            {"plane_id": 4, "time_s": 0.0, "latitude": 49.0, "longitude": 3.0},
            {"plane_id": 5, "time_s": 0.0, "latitude": 49.1, "longitude": 3.1},
            {"plane_id": 6, "time_s": 0.0, "latitude": 49.2, "longitude": 3.2},
        ]
    ).to_csv(datadir / "network.csv", index=False)

    graph = nx.Graph()
    for left in ("1", "2", "3"):
        for right in ("4", "5", "6"):
            graph.add_edge(left, right, bearer="satcom")
    topology_path = topology_dir / "ilp_topology.gml"
    nx.write_gml(graph, topology_path)

    app_settings_text = (
        "[view_maps_network]\n"
        'base_dir_choice = "Custom"\n'
        f'input_datadir = "{datadir.as_posix()}"\n'
        'datadir_rel = ""\n'
        'file_ext_choice = "csv"\n'
        'df_select_mode = "Single file"\n'
        'df_file = "network.csv"\n'
        'id_col = "plane_id"\n'
        'time_col = "time_s"\n'
        'edges_file = "network_sim/pipeline/ilp_topology.gml"\n'
        'layout_type_select = "planar"\n'
    )
    project_dir = create_temp_app_project(
        f"{target_name}_project",
        package_name=target_name,
        app_settings_text=app_settings_text,
        pyproject_name=f"{target_name.replace('_', '-')}-project",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export", timeout=30)
    at.checkbox(key="show_map").set_value(False).run()
    at.select_slider(key="view_maps_network:selected_time").set_value(0.0).run()

    assert not at.exception
    warnings = [warning.value for warning in at.warning]
    captions = [caption.value for caption in at.caption]

    filtered_warnings = [message for message in warnings if "Logo could not be loaded" not in message]
    assert not filtered_warnings
    assert any("Edge counts (preview): satcom_link=9" in caption for caption in captions)
    assert any("6 / 6 flights shown" in caption for caption in captions)
