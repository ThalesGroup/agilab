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
    flight_src = base_path / "apps/flight_trajectory_project/src"
    flight_dist = Path("~/wenv/flight_trajectory_worker/dist")
    for p in [node_path, flight_src, flight_dist]:
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)

@pytest.fixture(scope="session")
def args():
    return {'path': '~/data/flight_trajectory', 'flight_id': 1, 'data_out':
        '~/data/flight_trajectory/dataframes', 'data_dir':
                '~/data/flight_trajectory/dataset', 'beam_file': 'beams.csv', 'sat_file':
                'satellites.csv', 'waypoints': 'waypoints.geojson', 'yaw_angular_speed':
                1.0, 'roll_angular_speed': 3.0, 'pitch_angular_speed': 2.0,
            'vehicule_acceleration': 5.0, 'max_speed': 900.0, 'max_roll': 30.0,
            'max_pitch': 12.0, 'target_climbup_pitch': 8.0,
            'pitch_enable_speed_ratio': 0.3, 'altitude_loss_speed_treshold': 400.0,
            'landing_speed_target': 200.0, 'descent_pitch_target': -3.0,
            'landing_pitch_target': 3.0, 'cruising_pitch_max': 3.0,
            'descent_alt_treshold_landing': 500, 'max_speed_ratio_while_turining':
                0.8, 'enable_climb': False, 'enable_descent': False,
            'default_alt_value': 4000.0, 'plane_type': 'satellite'}

@pytest.fixture(scope="session")
def env():
    # Local import after sys.path is set
    from agi_env import AgiEnv
    env = AgiEnv(install_type=1, active_app="flight_trajectory_project", verbose=True)
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
    BaseWorker.new("flight_trajectory_project", mode=mode, env=env, verbose=3, args=args)
    result = BaseWorker.test(mode=mode, args=args)
    # You can assert whatever makes sense here, or just print
    print(f"[mode={mode}] {result}")
    # Example assertion (adjust according to your requirements)
    assert result is not None
