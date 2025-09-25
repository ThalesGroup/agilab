
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('/Users/jpm/agilab/src/agilab/apps/sat_trajectory_project'), install_type=1, verbose=1) 
    res = await AGI.run(app_env, 
                        mode=4, 
                        scheduler="127.0.0.1", 
                        workers={'127.0.0.1': 2}, 
                        data_uri="/Users/jpm/data/sat_trajectory/dataset", duration_s=86400, step_s=1, number_of_sat=25, input_TLE="TLE", input_antenna="antenna_conf.json", input_sat="sat.json")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())