
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('/Users/jpm/agilab/src/agilab/apps/link_sim_project'), install_type=1, verbose=1) 
    res = await AGI.run(app_env, 
                        mode=4, 
                        scheduler="127.0.0.1", 
                        workers={'127.0.0.1': 2}, 
                        data_uri="/Users/jpm/data/link_sim/dataset", data_flight="flights", data_sat="sat", output_format="csv", plane_conf="plane_conf.json", cloud_heatmap_IVDL="CloudMapIvdl.npz", cloud_heatmap_sat="CloudMapSat.npz", services_conf="service.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())