from pathlib import Path

from agi_env import AgiEnv


def test_env_smoke(tmp_path, monkeypatch):
    AgiEnv.reset()
    monkeypatch.setenv("AGI_SHARE_DIR", str(tmp_path / "share"))
    apps_dir = Path(__file__).resolve().parents[2]
    env = AgiEnv(apps_dir=apps_dir, active_app="mycode_project", verbose=0)
    assert env.app == "mycode_project"
