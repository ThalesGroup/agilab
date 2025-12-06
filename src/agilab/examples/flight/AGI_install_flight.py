
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

AGILAB_PATH = open(f"{Path.home()}/.local/share/agilab/.agilab-path").read().strip()
APPS_PATH = Path(AGILAB_PATH) / "apps"
APP = "flight_project"

async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)
    res = await AGI.install(app_env, 
                            modes_enabled=15,
                            scheduler="127.0.0.1",
                            workers={'127.0.0.1': 1})
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())