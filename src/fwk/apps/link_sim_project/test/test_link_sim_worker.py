import sys
import pytest
import asyncio
from pathlib import Path
path = str(Path(__file__).resolve().parents[3]  / "core/node/src")
if path not in sys.path:
    sys.path.append(path)
from agi_node.agi_dispatcher import BaseWorker
from agi_env import AgiEnv


@pytest.fixture(scope="session", autouse=True)
def setup_sys_path():
    # Setup sys.path before tests
    base_path = Path(__file__).resolve().parents[3]
    node_path = base_path / "core/node/src"
    flight_src = base_path / "apps/link_sim_project/src"
    flight_dist = Path("~/wenv/link_sim_worker/dist")
    for p in [node_path, flight_src, flight_dist]:
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)

@pytest.fixture(scope="session")
def args():
    return {'path': '~/data/link_sim', 'data_out': '~/data/link_sim/dataframes',
            'data_dir': '~/data/link_sim/dataset', 'data_flight': 'flights',
            'data_sat': 'sat', 'plane_conf_path': 'antenna_conf.json', 'cloud_heatmap_IVDL': 'CloudMapIvdl.npz',
            'cloud_heatmap_sat': 'CloudMapSat.npz',
            'services_conf_path': 'service.json',
            'output_format': 'json'}

@pytest.fixture(scope="session")
def env():
    # Local import after sys.path is set
    from agi_env import AgiEnv
    env = AgiEnv(install_type=1, active_app="link_sim_project", verbose=True)
    # build the egg
    wenv = env.wenv_abs
    build = wenv / "build.py"
    menv = env.wenv_abs
    cmd = f"uv run --project {menv} python {build} bdist_egg --packages base_worker, polars_worker -d {menv}"
    env.run(cmd, menv)

    # build cython lib
    cmd = f"uv run --project {wenv} python {build} build_ext --packages base_worker, polars_worker -b {wenv}"
    env.run(cmd, wenv)
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
    from agi_node.agi_dispatcher import BaseWorker
    # Call new and test for each mode
    BaseWorker.new("link_sim_project", mode=mode, env=env, verbose=3, args=args)
    result = BaseWorker.test(mode=mode, args=args)
    # You can assert whatever makes sense here, or just print
    print(f"[mode={mode}] {result}")
    # Example assertion (adjust according to your requirements)
    assert result is not None
