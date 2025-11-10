
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "~/PycharmProjects/agilab/src/agilab/apps"
APP = "link_sim_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.install(
        app_env,
        modes_enabled=13,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 2},
    )
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
