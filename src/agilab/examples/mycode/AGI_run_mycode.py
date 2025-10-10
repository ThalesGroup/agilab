
import asyncio
from pathlib import Path

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = Path(__file__).resolve().parents[3] / "apps"
APP = "mycode_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.run(
        app_env,
        mode=0,
        scheduler=None,
        workers=None,
    )
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
