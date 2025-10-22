import sys
from pathlib import Path

# Ensure required packages are importable when the test suite runs in isolation.
ROOT = Path(__file__).resolve()
CORE_ENV = ROOT.parents[3] / "core/agi-env/src"
CORE_NODE = ROOT.parents[3] / "core/node/src"
APP_SRC = ROOT.parents[1] / "src"
for candidate in (CORE_ENV, CORE_NODE, APP_SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

import pytest
from agi_env import AgiEnv
from agi_node.agi_dispatcher import WorkDispatcher
from mycode import Mycode, MycodeArgs


@pytest.fixture
def env(tmp_path, monkeypatch):
    AgiEnv.reset()
    monkeypatch.setenv("AGI_SHARE_DIR", str(tmp_path / "share"))
    apps_dir = ROOT.parents[2]
    environment = AgiEnv(apps_dir=apps_dir, active_app="mycode_project", verbose=0)
    yield environment
    WorkDispatcher.args = {}


def test_mycode_creates_data_dir(env, tmp_path):
    data_dir = tmp_path / "payload"
    args = MycodeArgs(data_uri=data_dir)
    mycode = Mycode(env, args=args)

    assert data_dir.exists()
    assert WorkDispatcher.args["dir_path"] == str(data_dir)
    assert mycode.as_dict()["dir_path"] == str(data_dir)


def test_from_toml_applies_overrides(env, tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text("[args]\nfiles = \"*.json\"\n")

    mycode = Mycode.from_toml(env, settings_path=config, data_uri=str(tmp_path / "another"))

    assert mycode.args.files == "*.json"
    assert Path(mycode.args.data_uri).expanduser().exists()
