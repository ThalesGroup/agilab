# import sys
# from agi-core.workers.agi_worker import AgiWorker
# from agi_env import AgiEnv, normalize_path
# args = {'path': '~/data/link_sim', 'data_out': '~/data/link_sim/dataframes',
#     'data_dir': '~/data/link_sim/dataset', 'data_flight': 'flights',
#     'data_sat': 'sat', 'plane_conf_path': 'plane_conf.json','cloud_heatmap_IVDL':'CloudMapIvdl.npz',
#     'cloud_heatmap_sat':'CloudMapSat.npz',
#     'services_conf_path':'service.json',
#     'output_format': 'json'}
# sys.path.insert(0,
#     '/home/agi/PycharmProjects/agilab/src/agilab/apps/link_sim_project/src')
# sys.path.insert(0, '/home/agi/wenv/link_sim_worker/dist')
# # for i in  range(4):
# #     print(f"mode: {i}")
# #     env = AgiEnv(install_type=1, active_app='link_sim_project', verbose=True)
# #     AgiWorker.new('link_sim_project', mode=i, env=env, verbose=3, args=args)
# #     result = AgiWorker.run(workers={'192.168.20.123': 2}, mode=i, args=args)
# #     print(result)
#
# env = AgiEnv(install_type=1, active_app='link_sim_project', verbose=True)
# AgiWorker.new('link_sim_project', mode=3, env=env, verbose=3, args=args)
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
    args = {'path': '~/data/link_sim', 'data_out': '~/data/link_sim/dataframes',
            'data_dir': '~/data/link_sim/dataset', 'data_flight': 'flights',
            'data_sat': 'sat', 'plane_conf_path': 'antenna_conf.json', 'cloud_heatmap_IVDL': 'CloudMapIvdl.npz',
            'cloud_heatmap_sat': 'CloudMapSat.npz',
            'services_conf_path': 'service.json',
            'output_format': 'json'}

    sys.path.insert(0,'/home/agi/PycharmProjects/agilab/src/fwk/apps/link_sim_project/src')
    sys.path.insert(0,'/home/agi/wenv/link_sim_worker/dist')

    # BaseWorker.run flight command
    for i in  [0,1,3]: # 2 is working only if you have generate the cython lib before
        env = AgiEnv(install_type=1,active_app="link_sim_project",verbose=True)
        with open(env.home_abs / ".local/share/agilab/.fwk-path", 'r') as f:
            fwk_path = Path(f.read().strip())

        path = str(env.home_abs / "/src")
        if path not in sys.path:
            sys.path.insert(0, path)
        BaseWorker.new("link_sim_project", mode=i, env=env, verbose=3, args=args)
        result = BaseWorker.test(mode=i, args=args)
        print(result)

if __name__ == "__main__":
    asyncio.run(main())