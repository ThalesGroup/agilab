"""Quick smoke test to invoke the flight trajectory worker locally."""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve()
NODE_SRC = BASE_DIR.parents[3] / 'core/agi-node/src'
if str(NODE_SRC) not in sys.path:
    sys.path.insert(0, str(NODE_SRC))
from agi_node.agi_dispatcher import BaseWorker
from agi_env import AgiEnv
DEFAULT_ARGS: dict[str, object] = {'data_in': 'flight_clone/dataset',
    'num_flights': 1, 'beam_file': 'beams.csv', 'sat_file':
    'satellites.csv', 'waypoints': 'waypoints.geojson', 'yaw_angular_speed':
    1.0, 'roll_angular_speed': 3.0, 'pitch_angular_speed': 2.0,
    'vehicule_acceleration': 5.0, 'max_speed': 900.0, 'max_roll': 30.0,
    'max_pitch': 12.0, 'target_climbup_pitch': 8.0,
    'pitch_enable_speed_ratio': 0.3, 'altitude_loss_speed_threshold': 400.0,
    'landing_speed_target': 200.0, 'descent_pitch_target': -3.0,
    'landing_pitch_target': 3.0, 'cruising_pitch_max': 3.0,
    'descent_altitude_threshold_landing': 500,
    'max_speed_ratio_while_turining': 0.8, 'enable_climb': False,
    'enable_descent': False, 'default_alt_value': 4000.0, 'plane_type':
    'satellite', 'dataset_format': 'csv'}


async def main() ->None:
    apps_dir = BASE_DIR.parents[2]
    env = AgiEnv(apps_dir=apps_dir, active_app=BASE_DIR.parents[1].name,
        verbose=True)
    BaseWorker._new(env=env, mode=0, verbose=3, args=DEFAULT_ARGS)
    result = await BaseWorker._run(mode=0, args=DEFAULT_ARGS)
    print(result)


if __name__ == '__main__':
    asyncio.run(main())
