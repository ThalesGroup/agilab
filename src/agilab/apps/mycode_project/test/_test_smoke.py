from pathlib import Path
import sys

ROOT = Path(__file__).resolve()
CORE_ENV = ROOT.parents[3] / "core/agi-env/src"
CORE_NODE = ROOT.parents[3] / "core/node/src"
for candidate in (CORE_ENV, CORE_NODE):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from agi_env import AgiEnv


def test_env_initializes(tmp_path, monkeypatch):
    AgiEnv.reset()
    monkeypatch.setenv("AGI_SHARE_DIR", str(tmp_path / "share"))
    apps_dir = ROOT.parents[2]
    env = AgiEnv(apps_dir=apps_dir, active_app="mycode_project", verbose=0)
    assert env.app == "mycode_project"
