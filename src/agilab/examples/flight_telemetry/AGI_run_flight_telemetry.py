import asyncio
from pathlib import Path

from agi_cluster.agi_distributor import AGI, RunRequest
from agi_env import AgiEnv

APP = "flight_telemetry_project"
LOCAL_RUN_MODES = AGI.PYTHON_MODE | AGI.DASK_MODE


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
            "data_source": "file",
            "files": "*",
            "nfile": 1,
            "nskip": 0,
            "nread": 0,
            "sampling_rate": 1.0,
            "datemin": "2020-01-01",
            "datemax": "2021-01-01",
            "output_format": "parquet",
        },
        data_in="flight/dataset",
        data_out="flight/dataframe",
        mode=LOCAL_RUN_MODES,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
    )
    res = await AGI.run(app_env, request=request)
    print(res)
    return res


if __name__ == "__main__":
    asyncio.run(main())
