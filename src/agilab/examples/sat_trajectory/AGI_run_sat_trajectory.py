
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "/Users/agi/PycharmProjects/agilab/src/agilab/apps"
APP = "sat_trajectory_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.run(app_env, 
                        mode=0, 
                        data_in="sat_trajectory/dataset", duration_s=86400, step_s=1, number_of_sat=25, input_TLE="TLE", input_antenna="antenna_conf.json", input_sat="sat.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())