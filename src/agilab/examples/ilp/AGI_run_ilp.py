
import asyncio
import os
from pathlib import Path

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv


def _resolve_apps_dir() -> Path:
    apps_dir_env = os.environ.get("APPS_DIR")
    if apps_dir_env:
        return Path(apps_dir_env).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "apps"


APPS_DIR = str(_resolve_apps_dir())
APP = "ilp_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.run(app_env, 
                        mode=11, 
                        scheduler=None, 
                        workers=None, 
                        topology="topo3N", num_demands=3, seed=42, demand_scale=1.0, data_in="data/ilp")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
