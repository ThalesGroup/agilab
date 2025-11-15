import sys
from pathlib import Path
base_path = Path(__file__).resolve()
path = str(base_path.parents[3] / 'core/node/src')
if path not in sys.path:
    sys.path.append(path)
from agi_node.agi_dispatcher import BaseWorker
from agi_env import AgiEnv
import asyncio


async def main():
    active_app = Path(__file__).expanduser().parents[1]
    args = {'data_in': 'flight_clone/dataset', 'num_flights': 1,
        'beam_file': 'beams.csv', 'sat_file': 'satellites.csv', 'waypoints':
        'waypoints.geojson', 'yaw_angular_speed': 1.0, 'roll_angular_speed':
        3.0, 'pitch_angular_speed': 2.0, 'vehicule_acceleration': 5.0,
        'max_speed': 900.0, 'max_roll': 30.0, 'max_pitch': 12.0,
        'target_climbup_pitch': 8.0, 'pitch_enable_speed_ratio': 0.3,
        'altitude_loss_speed_threshold': 400.0, 'landing_speed_target': 
        200.0, 'descent_pitch_target': -3.0, 'landing_pitch_target': 3.0,
        'cruising_pitch_max': 3.0, 'descent_altitude_threshold_landing': 
        500, 'max_speed_ratio_while_turining': 0.8, 'enable_climb': False,
        'enable_descent': False, 'default_alt_value': 4000.0, 'plane_type':
        'satellite'}
    active_app = base_path.parents[1]
    sys.path.insert(0, str(active_app / 'src'))
    sys.path.insert(0, str(Path.home() / 'wenv/flight_clone_worker/dist'))
    active_app = Path(__file__).expanduser().parents[1]
    env = AgiEnv(active_app=active_app, verbose=True)
    wenv = env.wenv_abs
    menv = env.wenv_abs
    cmd = (
        f'uv run --no-sync --project {menv} python -m agi_node.agi_dispatcher.build --app-path {menv} -q bdist_egg --packages agi_dispatcher,polars_worker -d {menv}'
        )
    await env.run(cmd, menv)
    cmd = (
        f'uv run --no-sync --project {wenv} python -m agi_node.agi_dispatcher.build --app-path {wenv} -q build_ext -b {wenv}'
        )
    await env.run(cmd, wenv)
    for i in [0, 1, 3]:
        with open(env.home_abs / '.local/share/agilab/.agilab-path', 'r') as f:
            agilab_path = Path(f.read().strip())
        path = str(env.home_abs / 'src')
        if path not in sys.path:
            sys.path.insert(0, path)
        BaseWorker._new(env=env, mode=i, verbose=3, args=args)
        result = await BaseWorker._run(mode=i, args=args)
        print(result)


if __name__ == '__main__':
    asyncio.run(main())
