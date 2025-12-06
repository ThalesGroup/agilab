
import asyncio
import os
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

AGILAB_PATH = os.open(f"{Path.home()}/.local/share/agilab/.agilab-path").read().strip()
APPS_PATH = Path(AGILAB_PATH) / "apps"
APP = "link_sim_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_PATH, app=APP, verbose=1)
    res = await AGI.run(app_env, 
                        mode=15, 
                        scheduler="127.0.0.1",
                        workers={'127.0.0.1': 1},
                        data_in="link_sim/dataset", data_out="link_sim/dataframe", data_flight="../../flight_trajectory/dataframe", data_sat="sat", output_format="parquet", plane_conf="plane_conf.json", cloud_heatmap_IVDL="CloudMapIvdl.npz", cloud_heatmap_sat="CloudMapSat.npz", services_conf="service.json", mean_service_duration=20, overlap_service_percent=20, cloud_attenuation=1.0)
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())