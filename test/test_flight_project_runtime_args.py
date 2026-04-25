from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import polars as pl
from agi_node import MutableNamespace
from agi_node.reduction import ReduceArtifact


def _import_flight_modules(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    app_src = repo_root / "src" / "agilab" / "apps" / "builtin" / "flight_project" / "src"
    monkeypatch.syspath_prepend(str(app_src))
    from flight.flight import Flight
    from flight_worker.flight_worker import FlightWorker

    return Flight, FlightWorker


class _FakeEnv:
    verbose = 0
    _is_managed_pc = False

    def __init__(self, share_root: Path) -> None:
        self.share_root = share_root
        self.home_abs = share_root.parent
        self.agi_share_path_abs = share_root
        self.agi_share_path = share_root
        self.AGI_LOCAL_SHARE = str(share_root)
        self.target = "flight"

    def share_root_path(self):
        return self.share_root

    def resolve_share_path(self, value):
        path = Path(value)
        if path.is_absolute():
            return path
        return self.share_root / path


def test_flight_manager_ignores_agi_step_list_args(monkeypatch, tmp_path):
    Flight, _ = _import_flight_modules(monkeypatch)
    env = _FakeEnv(tmp_path / "share")

    flight = Flight(
        env,
        args=[{"name": "uav_graph_routing_ppo", "args": {"seed": 0}}],
        data_in="network_sim/pipeline",
        data_out="uav_graph_routing/pipeline",
        reset_target=False,
    )

    assert flight.args.data_source == "file"
    assert flight.args.data_in == tmp_path / "share" / "network_sim" / "pipeline"
    assert flight.args.data_out == tmp_path / "share" / "uav_graph_routing" / "pipeline"


def test_flight_worker_defaults_missing_data_source(monkeypatch, tmp_path):
    _, FlightWorker = _import_flight_modules(monkeypatch)
    worker = object.__new__(FlightWorker)
    worker.args = MutableNamespace(
        data_in="network_sim/pipeline",
        data_out="uav_graph_routing/pipeline",
        reset_target=False,
    )
    worker.verbose = 0
    worker._worker_id = 0
    worker.env = _FakeEnv(tmp_path / "share")
    worker.pool_vars = {}

    def fake_setup_data_directories(**_kwargs):
        return SimpleNamespace(normalized_input=str(tmp_path / "share" / "network_sim" / "pipeline"))

    worker.setup_data_directories = fake_setup_data_directories

    worker.start()

    assert worker.args.data_source == "file"
    assert worker.args.output_format == "parquet"
    assert worker.pool_vars["args"] is worker.args


def test_flight_reduce_contract_merges_trajectory_partials(monkeypatch):
    _import_flight_modules(monkeypatch)
    from flight.reduction import (
        REDUCE_ARTIFACT_NAME,
        REDUCER_NAME,
        build_reduce_artifact,
        partial_from_flight_frame,
    )

    first = pl.DataFrame(
        {
            "aircraft": ["A1", "A1"],
            "date": ["2021-01-01 00:00:00", "2021-01-01 00:01:00"],
            "speed": [0.0, 100.0],
            "source_file": ["01_track.csv", "01_track.csv"],
        }
    ).with_columns(pl.col("date").str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S"))
    second = pl.DataFrame(
        {
            "aircraft": ["B2"],
            "date": ["2021-01-01 00:02:00"],
            "speed": [50.0],
            "source_file": ["02_track.csv"],
        }
    ).with_columns(pl.col("date").str.strptime(pl.Datetime, format="%Y-%m-%d %H:%M:%S"))

    artifact = build_reduce_artifact(
        (
            partial_from_flight_frame(
                first,
                partial_id="first",
                output_files=["A1.parquet"],
                output_format="parquet",
            ),
            partial_from_flight_frame(
                second,
                partial_id="second",
                output_files=["B2.parquet"],
                output_format="parquet",
            ),
        )
    )

    assert artifact.name == REDUCE_ARTIFACT_NAME
    assert artifact.reducer == REDUCER_NAME
    assert artifact.partial_count == 2
    assert artifact.payload["flight_run_count"] == 2
    assert artifact.payload["row_count"] == 3
    assert artifact.payload["source_file_count"] == 2
    assert artifact.payload["source_files"] == ["01_track.csv", "02_track.csv"]
    assert artifact.payload["aircraft_count"] == 2
    assert artifact.payload["aircraft"] == ["A1", "B2"]
    assert artifact.payload["output_file_count"] == 2
    assert artifact.payload["output_formats"] == ["parquet"]
    assert artifact.payload["mean_speed_m"] == 50.0
    assert artifact.payload["max_speed_m"] == 100.0
    assert artifact.payload["time_start"] == "2021-01-01T00:00:00"
    assert artifact.payload["time_end"] == "2021-01-01T00:02:00"


def test_flight_worker_emits_reduce_artifact(monkeypatch, tmp_path):
    _, FlightWorker = _import_flight_modules(monkeypatch)
    from flight.reduction import REDUCE_ARTIFACT_NAME, REDUCER_NAME, reduce_artifact_path

    monkeypatch.setenv("HOME", str(tmp_path))
    share_root = tmp_path / "share"
    source_root = share_root / "flight" / "dataset"
    source_root.mkdir(parents=True)
    source = source_root / "01_track.csv"
    source.write_text(
        "\n".join(
            [
                "aircraft,date,lat,long",
                "A1,2021-01-01 00:00:00,48.0000,2.0000",
                "A1,2021-01-01 00:01:00,48.0005,2.0005",
                "A1,2021-01-01 00:02:00,48.0010,2.0010",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    worker = FlightWorker()
    worker.env = _FakeEnv(share_root)
    worker.args = {
        "data_in": "flight/dataset",
        "data_out": "flight/dataframe",
        "reset_target": True,
        "output_format": "parquet",
    }
    worker._worker_id = 0
    worker.worker_id = 0
    worker.verbose = 0
    worker.start()

    result = worker.work_pool(str(source.relative_to(tmp_path)))
    assert "source_file" in result.columns

    worker.work_done(result)

    result_root = Path(worker.data_out)
    artifact_path = reduce_artifact_path(result_root, 0)
    artifact = ReduceArtifact.from_dict(json.loads(artifact_path.read_text(encoding="utf-8")))

    assert (result_root / "A1.parquet").is_file()
    assert artifact.name == REDUCE_ARTIFACT_NAME
    assert artifact.reducer == REDUCER_NAME
    assert artifact.partial_count == 1
    assert artifact.partial_ids == ("flight_worker_0",)
    assert artifact.payload["flight_run_count"] == 1
    assert artifact.payload["row_count"] == 3
    assert artifact.payload["source_files"] == ["01_track.csv"]
    assert artifact.payload["aircraft"] == ["A1"]
    assert artifact.payload["output_files"] == ["A1.parquet"]
    assert artifact.payload["output_formats"] == ["parquet"]
    assert artifact.payload["mean_speed_m"] > 0.0
    assert artifact.payload["max_speed_m"] > 0.0
