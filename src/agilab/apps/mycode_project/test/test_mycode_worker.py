import sys
from pathlib import Path
import pytest
import pytest_asyncio

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [0, 1, 3])
async def test_baseworker_mycode_project(mode):
    args = {
        'param1': 0,
        'param2': "some text",
        'param3': 3.14,
        'param4': True
    }
    script_path = Path(__file__).resolve()
    active_app_path = script_path.parents[1]
    src_path = str(active_app_path / 'src')

    # Add paths at the start of sys.path if not present
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    from agi_env import AgiEnv
    from agi_node.agi_dispatcher import BaseWorker

    env = AgiEnv(apps_dir=active_app_path.parent, active_app=active_app_path.name, verbose=True)
    dist_path = str(env.wenv_abs / 'dist')
    if dist_path not in sys.path:
        sys.path.insert(0, dist_path)
    with open(env.home_abs / ".local/share/agilab/.agilab-path", 'r') as f:
        agilab_path = Path(f.read().strip())

    node_src = str(agilab_path / "core/node/src")
    if node_src not in sys.path:
        sys.path.insert(0, node_src)

    env_src = str(agilab_path / "core/env/src")
    if env_src not in sys.path:
        sys.path.insert(0, env_src)

    BaseWorker._new(mode=mode, env=env, verbose=3, args=args)
    result = await BaseWorker._run(mode=mode, args=args)
    print(result)
    assert result is not None
