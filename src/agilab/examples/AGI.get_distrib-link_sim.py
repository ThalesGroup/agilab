
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('~/agilab/src/agilab/apps/link_sim_project'), install_type=1, verbose=True)
    res = await AGI.get_distrib(app_env,
                               scheduler=None, workers=None, path="data/sat", data_out="data/link_sim/dataframe", data_uri="data/link_sim/dataset", data_flight="flights", data_sat="sat", plane_conf="antenna_conf.json", output_format="parquet", cloud_heatmap_IVDL="CloudMapIvdl.npz", cloud_heatmap_sat="CloudMapSat.npz", services_conf="service.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())
