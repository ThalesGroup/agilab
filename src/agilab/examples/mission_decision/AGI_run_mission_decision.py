import asyncio
from pathlib import Path

from agi_cluster.agi_distributor import AGI, RunRequest
from agi_env import AgiEnv


APP = "mission_decision_project"
PYTHON_ONLY_MODE = AGI.PYTHON_MODE


def agilab_apps_path() -> Path:
    marker = Path.home() / ".local/share/agilab/.agilab-path"
    if not marker.is_file():
        raise SystemExit(
            "AGILAB is not initialized. Run the AGILAB installer or "
            "`agilab first-proof --json` before this example."
        )
    return Path(marker.read_text(encoding="utf-8").strip()) / "apps" / "builtin"


async def main():
    app_env = AgiEnv(apps_path=agilab_apps_path(), app=APP, verbose=1)
    request = RunRequest(
        params={
            "data_in": "mission_decision/scenarios",
            "data_out": "mission_decision/results",
            "files": "*.json",
            "nfile": 1,
            "objective": "balanced_mission",
            "adaptation_mode": "auto_replan",
            "failure_kind": "bandwidth_drop",
            "reset_target": True,
        },
        data_in="mission_decision/scenarios",
        data_out="mission_decision/results",
        mode=PYTHON_ONLY_MODE,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
    )
    res = await AGI.run(app_env, request=request)
    print(res)
    return res


if __name__ == "__main__":
    asyncio.run(main())
