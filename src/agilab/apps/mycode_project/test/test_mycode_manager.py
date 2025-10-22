from pathlib import Path

import pytest

from agi_env import AgiEnv
from mycode import Mycode, MycodeArgs


@pytest.fixture
def env(tmp_path, monkeypatch):
    AgiEnv.reset()
    monkeypatch.setenv("AGI_SHARE_DIR", str(tmp_path / "share"))
    apps_dir = Path(__file__).resolve().parents[2]
    return AgiEnv(apps_dir=apps_dir, active_app="mycode_project", verbose=0)


def test_mycode_initialises_and_builds_distribution(env, tmp_path):
    data_dir = tmp_path / "data"
    args = MycodeArgs(data_uri=data_dir)
    mycode = Mycode(env, args=args)

    workers = {"worker1": 1, "worker2": 2}
    plan, metadata, part, unit, weight = mycode.build_distribution(workers)

    assert plan == []
    assert metadata == []
    assert part == "id"
    assert unit == "nb_fct"
    assert weight == ""
    assert data_dir.exists()
