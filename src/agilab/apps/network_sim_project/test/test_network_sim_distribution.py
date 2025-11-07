import sys
from pathlib import Path

import pytest

script_path = Path(__file__).resolve()
active_app_path = script_path.parents[1]
src_path = active_app_path / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from network_sim.network_sim import NetworkSimApp, NetworkSimArgs  # noqa: E402


class DummyEnv:
    def __init__(self):
        self._is_managed_pc = False


def _create_flight_files(root: Path, count: int = 20) -> None:
    flights_dir = root / "csv"
    flights_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(count):
        file_path = flights_dir / f"flight_{idx:03d}.csv"
        file_path.write_text("timestamp,plane_id\n0,0\n", encoding="utf-8")


def test_build_distribution_assigns_all_flights(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    _create_flight_files(dataset_root, count=20)

    args = NetworkSimArgs(data_source="file", data_in=dataset_root)
    app = NetworkSimApp(env=DummyEnv(), args=args)

    plan, metadata, partition_key, nb_unit, weight_unit = app.build_distribution(
        {"workerA": 1, "workerB": 1}
    )

    assert partition_key == "flight"
    assert nb_unit == "files"
    assert weight_unit == "bytes"
    assert len(plan) == 2
    assert len(metadata) == 2

    total_tasks = sum(len(worker_plan) for worker_plan in plan)
    assert total_tasks == 20

    for worker_plan, worker_meta in zip(plan, metadata):
        assert len(worker_plan) == len(worker_meta)
        for (payload, deps), (label, weight) in zip(worker_plan, worker_meta):
            assert payload["functions name"] == "work_pool"
            assert isinstance(payload["args"], str)
            assert payload["args"].endswith(".csv")
            assert deps == []
            assert label
            assert weight > 0


def test_build_distribution_requires_flights(tmp_path: Path) -> None:
    args = NetworkSimArgs(data_source="file", data_in=tmp_path)
    app = NetworkSimApp(env=DummyEnv(), args=args)

    with pytest.raises(FileNotFoundError):
        app.build_distribution({"worker": 1})
