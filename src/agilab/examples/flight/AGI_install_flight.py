
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

APPS_DIR = "/Users/jpm/agilab/src/agilab/apps"
APP = "flight_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.install(app_env, 
                            modes_enabled=0,
                            scheduler=None, 
                            workers=None)
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())