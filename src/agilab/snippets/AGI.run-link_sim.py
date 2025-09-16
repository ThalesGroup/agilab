
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('/Users/jpm/agilab/src/agilab/apps/link_sim_project'), install_type=1, verbose=True) 
    res = await AGI.run(app_env, 
                        mode=None, 
                        scheduler=None, 
                        workers=None, 
                        path="~/data/sat", data_out="data/link_sim/dataframes", data_dir="data/link_sim/dataset", data_flight="flights", data_sat="sat", plane_conf_path="antenna_conf.json", output_format="parquet", cloud_heatmap_IVDL="CloudMapIvdl.npz", cloud_heatmap_sat="CloudMapSat.npz", services_conf_path="service.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())