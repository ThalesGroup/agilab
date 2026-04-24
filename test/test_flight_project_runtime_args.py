from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agi_node import MutableNamespace


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
