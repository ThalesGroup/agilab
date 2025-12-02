import asyncio
from pathlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "/Users/agi/PycharmProjects/agilab/src/agilab/apps"
APP = "sb3_trainer_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    base_export = Path(app_env.AGILAB_EXPORT_ABS).expanduser()
    res = await AGI.run(
        app_env,
        mode=4,
        scheduler="192.168.20.111",
        workers={"192.168.20.130": 1},
        data_source="file",
        data_in=str(base_export / "network_sim" / "pipeline"),
        data_out=str(base_export / "sb3_trainer" / "pipeline"),
        reset_target=False,
    )
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())