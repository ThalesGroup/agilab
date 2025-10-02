
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv
from pathlib import Path

APPS_ROOT = Path(__file__).resolve().parents[2] / "apps"


async def main():
    app_env = AgiEnv(apps_dir=APPS_ROOT, active_app="sat_trajectory_project", verbose=1)
    res = await AGI.get_distrib(app_env,
                               scheduler="127.0.0.1", 
                               workers={'127.0.0.1': 2},
                               data_uri="data/sat_trajectory/dataset", duration_s=86400, step_s=1, number_of_sat=25, input_TLE="TLE", input_antenna="antenna_conf.json", input_sat="sat.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
