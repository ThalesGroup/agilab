import sys
from pathlib import Path
import pytest

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [0, 1, 3])
async def test_baseworker_mycode_project(mode):
    args = {
        'param1': 0,
        'param2': "some text",
        'param3': 3.14,
        'param4': True
    }
    base_path = Path(__file__).resolve().parents[3]
    src_path = str(base_path / 'apps/mycode_project/src')
    dist_path = str(Path('~/wenv/mycode_worker/dist').expanduser())

    # Add paths at the start of sys.path if not present
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    if dist_path not in sys.path:
        sys.path.insert(0, dist_path)

    from agi_env import AgiEnv
    from agi_node.agi_dispatcher import BaseWorker

    active_app = Path(__file__).resolve().parents[1]
    env = AgiEnv(active_app=active_app, verbose=True)
    with open(env.home_abs / ".local/share/agilab/.agilab-path", 'r') as f:
        agilab_path = Path(f.read().strip())

    node_src = str(agilab_path / "core/node/src")
    if node_src not in sys.path:
        sys.path.insert(0, node_src)

    env_src = str(agilab_path / "core/env/src")
    if env_src not in sys.path:
        sys.path.insert(0, env_src)

    BaseWorker.new('mycode', mode=mode, env=env, verbose=3, args=args)
    result = await BaseWorker.run(mode=mode, args=args)
    print(result)
    assert result is not None
