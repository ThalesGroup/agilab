
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

APPS_ROOT = Path(__file__).resolve().parents[2] / "apps"

async def main():
    app_env = AgiEnv(apps_dir=APPS_ROOT, active_app='sat_trajectory_project', verbose=True)
    res = await AGI.install(app_env, modes_enabled=0,
                            scheduler=None, workers=None)
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())
