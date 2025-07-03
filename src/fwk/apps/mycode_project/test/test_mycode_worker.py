import sys
from pathlib import Path
import pytest

@pytest.mark.parametrize("mode", [0, 1, 3])
def test_baseworker_mycode_project(mode):
    args = {
        'param1': 0,
        'param2': "some text",
        'param3': 3.14,
        'param4': True
    }
    base_path = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(base_path / 'apps/mycode_project/src'))
    sys.path.insert(0, str(Path('~/wenv/mycode_worker/dist').expanduser()))

    from agi_env import AgiEnv
    from agi_dispatcher import BaseWorker

    env = AgiEnv(install_type=1, active_app="mycode_project", verbose=True)
    with open(env.home_abs / ".local/share/agilab/.fwk-path", 'r') as f:
        fwk_path = Path(f.read().strip())

    node_src = str(fwk_path / "core/node/src")
    if node_src not in sys.path:
        sys.path.insert(0, node_src)

    env_src = str(fwk_path / "core/env/src")
    if env_src not in sys.path:
        sys.path.insert(0, env_src)

    BaseWorker.new('mycode', mode=mode, env=env, verbose=3, args=args)
    result = BaseWorker.test(mode=mode, args=args)
    print(result)
    assert result is not None
