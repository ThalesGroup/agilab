import asyncio
from pathlib import Path
from typing import Any, Dict, Tuple

import tomllib

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "~/PycharmProjects/agilab/src/agilab/apps"
APP = "flight_trajectory_project"
DEFAULT_SCHEDULER = "127.0.0.1"
DEFAULT_WORKERS: Dict[str, int] = {"127.0.0.1": 2}
DEFAULT_MODE = 13


def _load_app_settings(settings_path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if settings_path.exists():
        with settings_path.open("rb") as handle:
            doc = tomllib.load(handle)
        args_section = doc.get("args", {})
        cluster_section = doc.get("cluster", {})
        if not isinstance(args_section, dict):
            args_section = {}
        if not isinstance(cluster_section, dict):
            cluster_section = {}
        return args_section, cluster_section
    return {}, {}


async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    args_settings, cluster_settings = _load_app_settings(Path(app_env.app_settings_file))

    scheduler = DEFAULT_SCHEDULER
    workers = DEFAULT_WORKERS
    mode = DEFAULT_MODE

    res = await AGI.run(
        app_env,
        mode=mode,
        scheduler=scheduler,
        workers=workers,
        **args_settings,
    )
    print(res)
    return res


if __name__ == "__main__":
    asyncio.run(main())
