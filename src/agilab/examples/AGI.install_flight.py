
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('/Users/jpm/agilab/src/agilab/apps/flight_project') ,install_type=1, verbose=1)
    res = await AGI.install(app_env, 
                            modes_enabled=4,
                            scheduler="127.0.0.1", 
                            workers={'127.0.0.1': 2})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())