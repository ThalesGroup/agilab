
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

APPS_ROOT = Path(__file__).resolve().parents[2] / "apps"

async def main():
    app_env = AgiEnv(apps_dir=APPS_ROOT, active_app='sat_trajectory_project', verbose=True)
    res = await AGI.run(app_env, 
                        mode=0,
                        scheduler=None, 
                        workers=None, 
                        path="~/data/sat", data_out="data/sat_trajectory/dataframe", data_uri="data/sat_trajectory/dataset", input_TLE="TLE", duration_s=86400, step_s=1, number_of_sat=25, input_antenna="antenna_conf.json", input_sat="sat.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
