
import asyncio
import os
from pathlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv


AGILAB_PATH = os.open(f"{Path.home()}/.local/share/agilab/.agilab-path").read().strip()
APPS_PATH = Path(AGILAB_PATH) / "apps"
APP = "network_sim_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_PATH, app=APP, verbose=1)
    res = await AGI.run(
        app_env,
        mode=13,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        data_source="file",
        data_in="data/flight/dataset",
        net_size=12,
        seed=42,
        topology_filename="topology.gml",
        summary_filename="topology_summary.json",
    )
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
