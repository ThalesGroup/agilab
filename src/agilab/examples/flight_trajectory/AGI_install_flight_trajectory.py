
import asyncio
from pathlib import Path
from typing import Any, Dict, Tuple

import tomllib

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

APPS_DIR = "/Users/agi/PycharmProjects/agilab/src/agilab/apps"
APP = "flight_trajectory_project"
DEFAULT_SCHEDULER = "192.168.3.86"
DEFAULT_WORKERS: Dict[str, int] = {"192.168.3.84": 1, "192.168.3.86": 1}
DEFAULT_MODES_ENABLED = 15


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
    _, cluster_settings = _load_app_settings(Path(app_env.app_settings_file))

    scheduler = cluster_settings.get("scheduler") or DEFAULT_SCHEDULER
    workers = cluster_settings.get("workers") or DEFAULT_WORKERS
    modes_enabled = cluster_settings.get("modes_enabled", DEFAULT_MODES_ENABLED)

    res = await AGI.install(
        app_env,
        modes_enabled=modes_enabled,
        scheduler=scheduler,
        workers=workers,
    )
    print(res)
    return res


if __name__ == "__main__":
    asyncio.run(main())
