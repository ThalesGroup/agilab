from __future__ import annotations

from pathlib import Path

from agilab.pipeline.pipeline_workflow_insights import build_data_availability


def test_data_availability_uses_separate_input_roots_without_leaking_outputs(tmp_path):
    session_root = tmp_path / "clustershare" / "agi" / "workflows" / "run-1"
    physical_root = tmp_path / "clustershare" / "agi"
    shared_input = physical_root / "uav_relay_queue" / "scenarios"
    shared_output = physical_root / "uav_relay_queue" / "dataframe"
    shared_input.mkdir(parents=True)
    shared_output.mkdir(parents=True)

    report = build_data_availability(
        [
            {
                "data_in": "uav_relay_queue/scenarios",
                "data_out": "uav_relay_queue/dataframe",
            }
        ],
        [0],
        [session_root],
        input_roots=[session_root, physical_root],
    )

    rows = {(row["kind"], row["path"]): row for row in report["rows"]}
    input_row = rows[("input", "uav_relay_queue/scenarios")]
    output_row = rows[("output", "uav_relay_queue/dataframe")]

    assert input_row["status"] == "present"
    assert Path(input_row["resolved_path"]) == shared_input
    assert output_row["status"] == "missing"
    assert output_row["resolved_path"] == ""
