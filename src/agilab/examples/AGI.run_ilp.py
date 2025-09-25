
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('/Users/jpm/agilab/src/agilab/apps/ilp_project'), install_type=1, verbose=1) 
    res = await AGI.run(app_env, 
                        mode=4, 
                        scheduler="127.0.0.1", 
                        workers={'127.0.0.1': 2}, 
                        topology="topo3N", num_demands=3, seed=42, demand_scale=1.0, data_uri="data/ilp")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())