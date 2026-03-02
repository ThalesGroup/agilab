import asyncio
from pathlib import Path

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv


AGILAB_PATH = Path((Path.home() / ".local/share/agilab/.agilab-path").read_text().strip())
APPS_PATH = AGILAB_PATH / "apps"
APP = "mycode_project"


async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)
    res = await AGI.run(
        app_env,
        mode=13,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        data_in="mycode/dataset",
        data_out="mycode/dataframe",
        files="*",
        nfile=1,
    )
    print(res)
    return res


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
