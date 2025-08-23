import sys
from pathlib import Path
import pytest
import pytest_asyncio

# Ajouter core/node/src au sys.path pour agi_dispatcher
app_abs = Path(__file__).resolve().parents[1]
node_src = app_abs.parents[1] / 'core/node/src'
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
    env = AgiEnv(active_app=app_abs, verbose=True)
    wenv = env.wenv_abs
    build = wenv / 'build.py'

    for cmd in [
        f'uv run --project {wenv} python {build} bdist_egg --packages base_worker,polars_worker -d {wenv}',
        f'uv run --project {wenv} python {build} build_ext --packages base_worker,polars_worker -b {wenv}'
    ]:
        await env.run(cmd, wenv)

    return env

@pytest.fixture(scope="session", autouse=True)
def build_worker_libs(env):
    # Build eggs and Cython (only once per session)
    wenv = env.wenv_abs
    build = wenv / "build.py"
    # Build egg
    cmd = f"uv run --project {wenv} python {build} bdist_egg --packages base_worker,polars_worker -d {wenv}"
    env.run(cmd, wenv)
    # Build cython
    cmd = f"uv run --project {wenv} python {build} build_ext --packages base_worker,polars_worker -b {wenv}"
    env.run(cmd, wenv)
    # Add src to sys.path
    src_path = str(env.home_abs / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

@pytest.mark.parametrize("mode", [0, 1, 2, 3])
@pytest.mark.asyncio
async def test_baseworker_modes(mode, args, env, build_worker_libs):
    BaseWorker.new("flight_project", mode=mode, env=env, verbose=3, args=args)
    result = await BaseWorker.run(mode=mode, args=args)
    print(f"[mode={mode}] {result}")
    assert result is not None
