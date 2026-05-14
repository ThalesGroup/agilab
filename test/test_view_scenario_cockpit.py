from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

PAGE_PATH = (
    "src/agilab/apps-pages/view_scenario_cockpit/"
    "src/view_scenario_cockpit/view_scenario_cockpit.py"
)


def _write_run(
    artifact_dir: Path,
    stem: str,
    *,
    scenario: str,
    routing_policy: str,
    pdr: float,
    mean_e2e_delay_ms: float,
    mean_queue_wait_ms: float,
    max_queue_depth_pkts: int,
) -> None:
    run_dir = artifact_dir / stem
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{stem}_summary_metrics.json").write_text(
        json.dumps(
            {
                "scenario": scenario,
                "routing_policy": routing_policy,
                "source_rate_pps": 14.0,
                "random_seed": 2026,
                "bottleneck_relay": "relay-a",
                "pdr": pdr,
                "mean_e2e_delay_ms": mean_e2e_delay_ms,
                "mean_queue_wait_ms": mean_queue_wait_ms,
                "max_queue_depth_pkts": max_queue_depth_pkts,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / f"{stem}_queue_timeseries.csv").write_text(
        "time_s,relay,queue_depth_pkts\n0.0,relay-a,2\n0.5,relay-a,4\n",
        encoding="utf-8",
    )
    (run_dir / f"{stem}_packet_events.csv").write_text(
        "packet_id,origin_kind,status,e2e_delay_ms\n1,source,delivered,85.0\n",
        encoding="utf-8",
    )
    (run_dir / f"{stem}_node_positions.csv").write_text(
        "time_s,node,role,y_m\n0.0,relay-a,relay,100\n",
        encoding="utf-8",
    )
    (run_dir / f"{stem}_routing_summary.csv").write_text(
        "relay,packets_delivered,packets_dropped\nrelay-a,18,2\n",
        encoding="utf-8",
    )
    pipeline_dir = run_dir / "pipeline"
    pipeline_dir.mkdir()
    (pipeline_dir / "topology.gml").write_text("graph []\n", encoding="utf-8")
    (pipeline_dir / "allocations_steps.csv").write_text(
        "time_s,source,target\n0.0,uav-1,relay-a\n",
        encoding="utf-8",
    )
    (pipeline_dir / "_trajectory_summary.json").write_text('{"nodes": 1}\n', encoding="utf-8")


def _load_helpers() -> ModuleType:
    source = Path(PAGE_PATH).read_text(encoding="utf-8")
    prefix = source.split('\nst.set_page_config(layout="wide")\n', 1)[0]
    module = ModuleType("view_scenario_cockpit_test_module")
    module.__file__ = str(Path(PAGE_PATH).resolve())
    module.__package__ = None
    exec(compile(prefix, str(Path(PAGE_PATH)), "exec"), module.__dict__)
    return module


def test_view_scenario_cockpit_renders_comparison_and_gate(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_relay_queue_project",
        package_name="uav_relay_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-relay-queue-project",
    )
    artifact_dir = tmp_path / "export" / "uav_relay_queue" / "queue_analysis"
    _write_run(
        artifact_dir,
        "a_shortest_path_seed2026",
        scenario="hotspot-demo",
        routing_policy="shortest_path",
        pdr=0.83,
        mean_e2e_delay_ms=112.8,
        mean_queue_wait_ms=38.4,
        max_queue_depth_pkts=11,
    )
    _write_run(
        artifact_dir,
        "b_queue_aware_seed2026",
        scenario="hotspot-demo",
        routing_policy="queue_aware",
        pdr=0.91,
        mean_e2e_delay_ms=87.4,
        mean_queue_wait_ms=23.1,
        max_queue_depth_pkts=7,
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any(title.value == "Scenario cockpit" for title in at.title)
    assert any(metric.label == "Decision" and metric.value == "promotable" for metric in at.metric)
    assert any(metric.label == "Runs selected" and metric.value == "2" for metric in at.metric)

    comparison_frames = [
        frame.value for frame in at.dataframe if "delta_pdr_vs_baseline" in frame.value.columns
    ]
    assert len(comparison_frames) == 1
    comparison_df = comparison_frames[0]
    candidate = comparison_df.loc[comparison_df["routing_policy"] == "queue_aware"].iloc[0]
    assert candidate["delta_pdr_vs_baseline"] > 0
    assert candidate["delta_delay_ms_vs_baseline"] < 0

    artifact_frames = [frame.value for frame in at.dataframe if "sha256" in frame.value.columns]
    assert len(artifact_frames) == 1
    assert artifact_frames[0]["exists"].all()


def test_view_scenario_cockpit_helpers_build_hashable_evidence_bundle(tmp_path) -> None:
    module = _load_helpers()
    artifact_dir = tmp_path / "queue_analysis"
    _write_run(
        artifact_dir,
        "a_shortest_path_seed2026",
        scenario="hotspot-demo",
        routing_policy="shortest_path",
        pdr=0.83,
        mean_e2e_delay_ms=112.8,
        mean_queue_wait_ms=38.4,
        max_queue_depth_pkts=11,
    )
    _write_run(
        artifact_dir,
        "b_queue_aware_seed2026",
        scenario="hotspot-demo",
        routing_policy="queue_aware",
        pdr=0.91,
        mean_e2e_delay_ms=87.4,
        mean_queue_wait_ms=23.1,
        max_queue_depth_pkts=7,
    )
    summary_files = module._discover_files(artifact_dir, "**/*_summary_metrics.json")
    label_to_path = {module._relative_label(path, artifact_dir): path for path in summary_files}
    baseline_label, candidate_label = list(label_to_path)

    comparison_df = module._build_comparison_frame(label_to_path, artifact_dir, baseline_label)
    gate = module._candidate_gate(comparison_df, candidate_label)
    bundle = module._build_evidence_bundle(
        selected_paths=label_to_path,
        artifact_root=artifact_dir,
        comparison_df=comparison_df,
        baseline_label=baseline_label,
        candidate_label=candidate_label,
    )

    assert gate["status"] == "promotable"
    assert bundle["schema"] == "agilab.scenario_evidence_bundle.v1"
    assert bundle["baseline_run"] == baseline_label
    assert bundle["candidate_run"] == candidate_label
    assert any(record.get("sha256") for record in bundle["artifacts"] if record["exists"])
    json.dumps(bundle)


def test_view_scenario_cockpit_warns_when_artifact_directory_is_missing(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_relay_queue_project",
        package_name="uav_relay_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-relay-queue-project",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any("Artifact directory does not exist yet" in warning.value for warning in at.warning)


def test_view_scenario_cockpit_warns_when_summary_glob_is_empty(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    project_dir = create_temp_app_project(
        "uav_relay_queue_project",
        package_name="uav_relay_queue",
        app_settings_text="[args]\n",
        pyproject_name="uav-relay-queue-project",
    )
    (tmp_path / "export" / "uav_relay_queue" / "queue_analysis").mkdir(parents=True)

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=tmp_path / "export")

    assert not at.exception
    assert any("No summary metrics file found" in warning.value for warning in at.warning)
