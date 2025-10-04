import sys
from pathlib import Path
import pytest
import pytest_asyncio

# Ajouter core/node/src au sys.path pour agi_dispatcher
script_path = Path(__file__).resolve()
active_app_path = script_path.parents[1]
apps_dir = script_path.parents[2]
node_src = active_app_path.parents[1] / 'core/node/src'
if str(node_src) not in sys.path:
    sys.path.insert(0, str(node_src))

from agi_node.agi_dispatcher import BaseWorker
from agi_env import AgiEnv



@pytest.fixture(scope="session")
def args():
    return {
        'data_source': 'file',
        'datemin': '2020-01-01',
        'datemax': '2021-01-01',
        'files': 'csv/*',
        'nfile': 1,
        'nread': 0,
        'nskip': 0,
        'output_format': 'parquet',
        'path': 'data/flight/dataset',
        'sampling_rate': 10.0,
        'verbose': True
    }


@pytest_asyncio.fixture(scope="session")
async def env():
    env = AgiEnv(apps_dir=apps_dir, active_app=active_app_path.name, verbose=True)
    wenv = env.wenv_abs
    commands = [
        f"uv run --project {wenv} python -m agi_node.agi_dispatcher.build --app-path {wenv} "
        f"-q bdist_egg --packages agi_dispatcher,polars_worker -d {wenv}",
        f"uv run --project {wenv} python -m agi_node.agi_dispatcher.build --app-path {wenv} "
        f"-q build_ext -b {wenv}"
    ]
    for cmd in commands:
        await env.run(cmd, wenv)

    return env

@pytest.fixture(scope="session", autouse=True)
async def build_worker_libs(env):
    # Build eggs and Cython (only once per session)
    wenv = env.wenv_abs
    build_cmd = "python -m agi_node.agi_dispatcher.build"
    # Build egg
    cmd = (
        f"uv run --project {wenv} {build_cmd} --app-path {wenv} "
        f"-q bdist_egg --packages agi_dispatcher,polars_worker -d {wenv}"
    )
    await env.run(cmd, wenv)
    # Build cython
    cmd = (
        f"uv run --project {wenv} {build_cmd} --app-path {wenv} "
        f"-q build_ext -b {wenv}"
    )
    await env.run(cmd, wenv)
    # Add src to sys.path
    src_path = str(env.home_abs / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

@pytest.mark.parametrize("mode", [0, 1, 2, 3])
@pytest.mark.asyncio
async def test_baseworker_modes(mode, args, env, build_worker_libs):
    BaseWorker._new(mode=mode, env=env, verbose=3, args=args)
    result = await BaseWorker._run(mode=mode, args=args)
    print(f"[mode={mode}] {result}")
    assert result is not None
