import asyncio
from pathlib import Path

from agi_cluster.agi_distributor import AGI, RunRequest
from agi_env import AgiEnv


AGILAB_PATH = open(f"{Path.home()}/.local/share/agilab/.agilab-path").read().strip()
APPS_PATH = Path(AGILAB_PATH) / "apps"
APP = "data_io_2026_project"


async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)
    request = RunRequest(
        params={
            "data_in": "data_io_2026/scenarios",
            "data_out": "data_io_2026/results",
            "files": "*.json",
            "nfile": 1,
            "objective": "balanced_mission",
            "adaptation_mode": "auto_replan",
            "failure_kind": "bandwidth_drop",
            "reset_target": True,
        },
        data_in="data_io_2026/scenarios",
        data_out="data_io_2026/results",
        mode=AGI.PYTHON_MODE,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
    )
    res = await AGI.run(app_env, request=request)
    print(res)
    return res


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
