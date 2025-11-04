
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "/Users/jpm/PycharmProjects/agilab/src/agilab/apps"
APP = "link_sim_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.run(app_env, 
                        mode=13, 
                        scheduler="192.168.20.111", 
                        workers={'192.168.20.111': 1, '192.168.20.130': 1}, 
                        data_uri="/Users/jpm/data/link_sim/dataset", data_flight="../../flight_trajectory/dataframe", data_sat="sat", output_format="parquet", plane_conf="plane_conf.json", cloud_heatmap_IVDL="CloudMapIvdl.npz", cloud_heatmap_sat="CloudMapSat.npz", services_conf="service.json", mean_service_duration=20, overlap_service_percent=20, cloud_attenuation=1.0)
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())