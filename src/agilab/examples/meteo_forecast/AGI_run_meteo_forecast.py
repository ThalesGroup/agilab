import asyncio
from pathlib import Path

from agi_cluster.agi_distributor import AGI, RunRequest
from agi_env import AgiEnv


AGILAB_PATH = open(f"{Path.home()}/.local/share/agilab/.agilab-path").read().strip()
APPS_PATH = Path(AGILAB_PATH) / "apps"
APP = "meteo_forecast_project"


async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)
    request = RunRequest(
        params={
            "data_in": "meteo_forecast/dataset",
            "data_out": "meteo_forecast/results",
            "files": "*.csv",
            "nfile": 1,
            "station": "Paris-Montsouris",
            "target_column": "tmax_c",
            "lags": 7,
            "horizon_days": 7,
            "validation_days": 9,
            "n_estimators": 100,
            "random_state": 42,
            "reset_target": True,
        },
        data_in="meteo_forecast/dataset",
        data_out="meteo_forecast/results",
        mode=AGI.PYTHON_MODE,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
    )
    res = await AGI.run(app_env, request=request)
    print(res)
    return res


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
