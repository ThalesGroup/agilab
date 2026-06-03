import asyncio
from pathlib import Path

from agi_cluster.agi_distributor import AGI, RunRequest
from agi_env import AgiEnv


APP = "weather_forecast_project"
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
            "data_in": "weather_forecast/dataset",
            "data_out": "weather_forecast/results",
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
        data_in="weather_forecast/dataset",
        data_out="weather_forecast/results",
        mode=PYTHON_ONLY_MODE,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
    )
    res = await AGI.run(app_env, request=request)
    print(res)
    return res


if __name__ == "__main__":
    asyncio.run(main())
