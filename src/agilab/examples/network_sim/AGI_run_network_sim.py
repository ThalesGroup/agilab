
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "/Users/jpm/PycharmProjects/agilab/src/agilab/apps"
APP = "network_sim_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.run(app_env, 
                        mode=15, 
                        scheduler="192.168.20.111", 
                        workers={'192.168.20.111': 1}, 
                        data_source="file", data_uri="data/flight/dataset", net_size=12, seed=42, topology_filename="topology.gml", summary_filename="topology_summary.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())