
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('~/agilab/src/agilab/apps/sb3_trainer_project'), install_type=1, verbose=False) 
    res = await AGI.run(app_env, 
                        mode=0,
                        scheduler=None, 
                        workers=None, 
                        data_uri="data/sat/dataset", data_flight="flights", data_sat="sat", plane_conf="antenna_conf.json", output_format="parquet", cloud_heatmap_IVDL="CloudMapIvdl.npz", cloud_heatmap_sat="CloudMapSat.npz", services_conf="service.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())
