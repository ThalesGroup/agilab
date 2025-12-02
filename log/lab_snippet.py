import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "/Users/agi/PycharmProjects/agilab/src/agilab/apps"
APP = "sb3_trainer_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.run(
        app_env,
        mode=4,
        scheduler="192.168.20.111",
        workers={"192.168.20.130": 1},
        data_source="file",
        data_in="~/clustershare/network_sim/pipeline",
        data_out="~/clustershare/sb3_trainer/pipeline",
        reset_target=False,
    )
    print(res)
    return res

if __name__ == "__main__":
    asyncio.run(main())
