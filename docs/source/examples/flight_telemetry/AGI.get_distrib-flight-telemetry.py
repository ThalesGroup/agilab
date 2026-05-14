import asyncio
from pathlib import Path

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv


APP = "flight_telemetry_project"


def agilab_apps_path() -> Path:
    marker = Path.home() / ".local/share/agilab/.agilab-path"
    if not marker.is_file():
        raise SystemExit(
            "AGILAB is not initialized. Run the AGILAB installer or "
            "`agilab first-proof --json` before this example."
        )
    return Path(marker.read_text(encoding="utf-8").strip()) / "apps"


async def main():
    app_env = AgiEnv(apps_path=agilab_apps_path(), app=APP, verbose=1)
    res = await AGI.get_distrib(
        app_env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        data_source="file",
        data_in="flight/dataset",
        data_out="flight/dataframe",
        files="*",
        nfile=1,
    )
    print(res)
    return res


if __name__ == "__main__":
    asyncio.run(main())
