import sys
from pathlib import Path
import pytest
import pytest_asyncio
script_path = Path(__file__).resolve()
active_app_path = script_path.parents[1]
apps_dir = script_path.parents[2]
node_src = active_app_path.parents[1] / 'core/agi-node/src'
if str(node_src) not in sys.path:
    sys.path.insert(0, str(node_src))
from agi_node.agi_dispatcher import BaseWorker
from agi_env import AgiEnv


@pytest.fixture(scope='session')
def args():
    return {'data_in': 'flight_clone/dataset', 'data_source': 'file',
        'num_flights': 1, 'beam_file': 'beams.csv', 'sat_file':
        'satellites.csv', 'data_out': 'flight_clone/dataframe', 'waypoints':
        'waypoints.geojson', 'yaw_angular_speed': 1.0, 'roll_angular_speed':
        3.0, 'pitch_angular_speed': 2.0, 'vehicule_acceleration': 5.0,
        'max_speed': 900.0, 'max_roll': 30.0, 'max_pitch': 12.0,
        'target_climbup_pitch': 8.0, 'pitch_enable_speed_ratio': 0.3,
        'altitude_loss_speed_threshold': 400.0, 'landing_speed_target': 
        200.0, 'descent_pitch_target': -3.0, 'landing_pitch_target': 3.0,
        'cruising_pitch_max': 3.0, 'descent_altitude_threshold_landing': 
        500, 'max_speed_ratio_while_turining': 0.8, 'enable_climb': False,
        'enable_descent': False, 'default_alt_value': 4000.0, 'plane_type':
        'satellite', 'output_format': 'json'}


@pytest_asyncio.fixture(scope='session')
async def env():
    environment = AgiEnv(apps_dir=apps_dir, active_app=active_app_path.name,
        verbose=True)
    wenv = environment.wenv_abs
    build_cmd = 'python -m agi_node.agi_dispatcher.build'
    commands = [
        f'uv run --project {wenv} {build_cmd} --app-path {wenv} -q bdist_egg --packages agi_dispatcher,polars_worker -d {wenv}'
        ,
        f'uv run --project {wenv} {build_cmd} --app-path {wenv} -q build_ext -b {wenv}'
        ]
    for command in commands:
        await environment.run(command, wenv)
    src_path = str(environment.home_abs / 'src')
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return environment


@pytest.mark.parametrize('mode', [0, 1, 3])
@pytest.mark.asyncio
async def test_baseworker_modes(mode, args, env):
    BaseWorker._new(mode=mode, env=env, verbose=3, args=args)
    result = await BaseWorker._run(mode=mode, args=args)
    assert result is not None
