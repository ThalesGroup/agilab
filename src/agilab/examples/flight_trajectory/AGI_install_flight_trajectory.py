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
APP = "flight_trajectory_project"
DEFAULT_SCHEDULER = "127.0.0.1"
DEFAULT_WORKERS = {"127.0.0.1": 2}
DEFAULT_MODES_ENABLED = 13


async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.install(
        app_env,
        modes_enabled=DEFAULT_MODES_ENABLED,
        scheduler=DEFAULT_SCHEDULER,
        workers=DEFAULT_WORKERS,
    )
    print(res)
    return res


if __name__ == "__main__":
    asyncio.run(main())
