# import sys
# from agi-core.workers.agi_worker import AgiWorker
# from agi_env import AgiEnv, normalize_path
# args = {'path': '~/data/flight_trajectory', 'flight_id': 1, 'data_out':
#     '~/data/flight_trajectory/dataframes', 'data_dir':
#     '~/data/flight_trajectory/dataset', 'beam_file': 'beams.csv', 'sat_file':
#     'satellites.csv', 'waypoints': 'waypoints.geojson', 'yaw_angular_speed':
#     1.0, 'roll_angular_speed': 3.0, 'pitch_angular_speed': 2.0,
#     'vehicule_acceleration': 5.0, 'max_speed': 900.0, 'max_roll': 30.0,
#     'max_pitch': 12.0, 'target_climbup_pitch': 8.0,
#     'pitch_enable_speed_ratio': 0.3, 'altitude_loss_speed_treshold': 400.0,
#     'landing_speed_target': 200.0, 'descent_pitch_target': -3.0,
#     'landing_pitch_target': 3.0, 'cruising_pitch_max': 3.0,
#     'descent_alt_treshold_landing': 500, 'max_speed_ratio_while_turining':
#     0.8, 'enable_climb': False, 'enable_descent': False,
#     'default_alt_value': 4000.0, 'plane_type': 'satellite'}
# sys.path.insert(0,
#     '/home/agi/PycharmProjects/agilab/src/agilab/apps/sat_sim_project/src')
# sys.path.insert(0, '/home/agi/wenv/sat_sim_worker/dist')
#
# for i in range(4):
#     print(f"mode: {i}")
#     env = AgiEnv(install_type=1, active_app='flight_trajectory_project', verbose=True)
#     AgiWorker.new('sat_sim_project', mode=i, env=env, verbose=3, args=args)
#     result = AgiWorker.run(workers={'192.168.20.123': 2}, mode=i, args=args)
#     print(result)

# env = AgiEnv(install_type=1, active_app='flight_trajectory_project', verbose=True)
# AgiWorker.new('sat_sim_project', mode=2, env=env, verbose=3, args=args)
# result = AgiWorker.run(workers={'192.168.20.123': 2}, mode=2, args=args)
# print(result)

import sys
from pathlib import Path
path = str(Path(__file__).resolve().parents[3]  / "core/node/src")
if path not in sys.path:
    sys.path.append(path)
from agi_node.agi_dispatcher import BaseWorker
from agi_env import AgiEnv
import asyncio


async def main():
    args = {'path': '~/data/flight_trajectory', 'flight_id': 1, 'data_out':
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

    sys.path.insert(0,'/home/agi/PycharmProjects/agilab/src/fwk/apps/flight_trajectory_project/src')
    sys.path.insert(0,'/home/agi/wenv/flight_trajectory_worker/dist')

    # BaseWorker.run flight command
    for i in  [0,1,3]: # 2 is working only if you have generate the cython lib before
        env = AgiEnv(install_type=1,active_app="flight_trajectory_project",verbose=True)
        with open(env.home_abs / ".local/share/agilab/.fwk-path", 'r') as f:
            fwk_path = Path(f.read().strip())

        path = str(env.home_abs / "/src")
        if path not in sys.path:
            sys.path.insert(0, path)
        BaseWorker.new("flight_trajectory_project", mode=i, env=env, verbose=3, args=args)
        result = BaseWorker.test(mode=i, args=args)
        print(result)

if __name__ == "__main__":
    asyncio.run(main())