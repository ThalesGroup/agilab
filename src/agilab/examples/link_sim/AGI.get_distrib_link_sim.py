
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

APPS_ROOT = Path(__file__).resolve().parents[2] / "apps"

async def main():
    app_env = AgiEnv(apps_dir=APPS_ROOT, active_app='link_sim_project', verbose=True)
    res = await AGI.get_distrib(app_env,
                               scheduler=None, workers=None, path="data/sat", data_out="data/link_sim/dataframe", data_uri="data/link_sim/dataset", data_flight="flights", data_sat="sat", plane_conf="antenna_conf.json", output_format="parquet", cloud_heatmap_IVDL="CloudMapIvdl.npz", cloud_heatmap_sat="CloudMapSat.npz", services_conf="service.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())
