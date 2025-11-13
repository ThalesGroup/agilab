
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
APP = "flight_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.run(
        app_env,
        mode=13,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 2},
        data_source="file",
        data_in="flight/dataset",
        data_out="flight/dataframe",
        files="*",
        nfile=1,
        nskip=0,
        nread=0,
        sampling_rate=1.0,
        datemin="2020-01-01",
        datemax="2021-01-01",
        output_format="parquet",
    )
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
