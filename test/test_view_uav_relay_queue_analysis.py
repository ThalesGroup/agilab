from __future__ import annotations

import json
from pathlib import Path


PAGE_PATH = (
    "src/agilab/apps-pages/view_uav_relay_queue_analysis/"
    "src/view_uav_relay_queue_analysis/view_uav_relay_queue_analysis.py"
)


def _write_relay_run(
    artifact_dir: Path,
    stem: str,
    *,
    scenario: str,
    routing_policy: str,
    source_rate_pps: float,
    random_seed: int,
    bottleneck_relay: str,
    pdr: float,
    mean_e2e_delay_ms: float,
    mean_queue_wait_ms: float,
    max_queue_depth_pkts: int,
    notes: str,
) -> None:
    (artifact_dir / f"{stem}_summary_metrics.json").write_text(
        json.dumps(
            {
                "scenario": scenario,
                "routing_policy": routing_policy,
                "source_rate_pps": source_rate_pps,
                "random_seed": random_seed,
                "bottleneck_relay": bottleneck_relay,
                "pdr": pdr,
                "mean_e2e_delay_ms": mean_e2e_delay_ms,
                "mean_queue_wait_ms": mean_queue_wait_ms,
                "max_queue_depth_pkts": max_queue_depth_pkts,
                "notes": notes,
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_queue_timeseries.csv").write_text(
        "time_s,relay,queue_depth_pkts\n"
        "0.0,relay-a,1\n"
        "0.5,relay-a,2\n"
        "0.0,relay-b,3\n"
        "0.5,relay-b,1\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_packet_events.csv").write_text(
        "packet_id,origin_kind,status,e2e_delay_ms\n"
        "1,source,delivered,85.0\n"
        "2,source,delivered,110.5\n"
        "3,background,dropped,\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_node_positions.csv").write_text(
        "time_s,node,role,y_m\n"
        "0.0,relay-a,relay,100\n"
        "0.5,relay-a,relay,101\n"
        "0.0,relay-b,relay,210\n"
        "0.5,relay-b,relay,212\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_routing_summary.csv").write_text(
        "relay,packets_delivered,packets_dropped\n"
        "relay-a,18,2\n"
        "relay-b,24,1\n",
        encoding="utf-8",
    )


def test_view_uav_relay_queue_analysis_renders_exported_artifacts(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_relay_queue_project",
        package_name="uav_relay_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-relay-queue-project",
    )
    artifact_dir = tmp_path / "export" / "uav_relay_queue" / "queue_analysis"
    artifact_dir.mkdir(parents=True)
    stem = "hotspot_queue_aware_seed2026"
    _write_relay_run(
        artifact_dir,
        stem,
        scenario="hotspot-demo",
        routing_policy="queue_aware",
        source_rate_pps=14.0,
        random_seed=2026,
        bottleneck_relay="relay-b",
        pdr=0.91,
        mean_e2e_delay_ms=87.4,
        mean_queue_wait_ms=23.1,
        max_queue_depth_pkts=7,
        notes="Queue-aware relay selection avoids the busiest relay.",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any(title.value == "UAV relay queue analysis" for title in at.title)
    assert any(metric.label == "PDR" for metric in at.metric)
    assert len(at.dataframe) >= 1
    assert len(at.selectbox) >= 1
    assert len(at.text_input) >= 2


def test_view_uav_relay_queue_analysis_compares_multiple_runs(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_relay_queue_project",
        package_name="uav_relay_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-relay-queue-project",
    )
    artifact_dir = tmp_path / "export" / "uav_relay_queue" / "queue_analysis"
    artifact_dir.mkdir(parents=True)
    _write_relay_run(
        artifact_dir,
        "hotspot_queue_aware_seed2026",
        scenario="hotspot-demo",
        routing_policy="queue_aware",
        source_rate_pps=14.0,
        random_seed=2026,
        bottleneck_relay="relay-b",
        pdr=0.91,
        mean_e2e_delay_ms=87.4,
        mean_queue_wait_ms=23.1,
        max_queue_depth_pkts=7,
        notes="Queue-aware relay selection avoids the busiest relay.",
    )
    _write_relay_run(
        artifact_dir,
        "hotspot_shortest_path_seed2027",
        scenario="hotspot-demo",
        routing_policy="shortest_path",
        source_rate_pps=14.0,
        random_seed=2027,
        bottleneck_relay="relay-a",
        pdr=0.83,
        mean_e2e_delay_ms=112.8,
        mean_queue_wait_ms=38.4,
        max_queue_depth_pkts=11,
        notes="Shortest path overloads relay-a earlier.",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    runs_widget = at.multiselect(key="uav_relay_queue_selected_runs")
    assert len(runs_widget.options) == 2

    at = runs_widget.set_value(list(runs_widget.options)).run()

    assert not at.exception
    assert len(at.selectbox) >= 2
    comparison_frames = [frame.value for frame in at.dataframe if "delta_pdr_vs_ref" in frame.value.columns]
    assert len(comparison_frames) == 1
    comparison_df = comparison_frames[0]
    assert set(comparison_df["run_label"]) == set(runs_widget.options)
    assert set(comparison_df["routing_policy"]) == {"queue_aware", "shortest_path"}
    assert any(metric.label == "Runs selected" and metric.value == "2" for metric in at.metric)


def test_view_uav_relay_queue_analysis_reports_missing_peer_artifacts(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_relay_queue_project",
        package_name="uav_relay_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-relay-queue-project",
    )
    artifact_dir = tmp_path / "export" / "uav_relay_queue" / "queue_analysis"
    artifact_dir.mkdir(parents=True)
    stem = "hotspot_queue_aware_seed2026"
    (artifact_dir / f"{stem}_summary_metrics.json").write_text(
        json.dumps(
            {
                "scenario": "hotspot-demo",
                "routing_policy": "queue_aware",
                "source_rate_pps": 14.0,
                "random_seed": 2026,
                "bottleneck_relay": "relay-b",
                "pdr": 0.91,
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_packet_events.csv").write_text(
        "packet_id,origin_kind,status,e2e_delay_ms\n"
        "1,source,delivered,85.0\n",
        encoding="utf-8",
    )
    (artifact_dir / f"{stem}_node_positions.csv").write_text(
        "time_s,node,role,y_m\n"
        "0.0,relay-a,relay,100\n",
        encoding="utf-8",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any(title.value == "UAV relay queue analysis" for title in at.title)
    assert any("Related queue artifacts are missing" in error.value for error in at.error)
    assert len(at.code) >= 1
