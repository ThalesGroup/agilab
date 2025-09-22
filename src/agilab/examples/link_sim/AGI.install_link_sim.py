
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('~/agilab/src/agilab/apps/link_sim_project') ,install_type=1, verbose=True)
    res = await AGI.install(app_env, modes_enabled=0,
                            scheduler=None, workers=None)
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())
            