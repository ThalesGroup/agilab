
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
APP = "link_sim_project"

async def main():
    app_env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    data_root = Path(os.environ.get("LINK_SIM_DATA", Path.home() / "data/link_sim/dataset")).expanduser()
    res = await AGI.run(
        app_env,
        mode=13,
        scheduler="192.168.20.111",
        workers={'192.168.20.111': 1, '192.168.20.130': 1},
        data_in=str(data_root),
        data_flight="../../flight_trajectory/dataframe",
        data_sat="sat",
        output_format="parquet",
        plane_conf="plane_conf.json",
        cloud_heatmap_IVDL="CloudMapIvdl.npz",
        cloud_heatmap_sat="CloudMapSat.npz",
        services_conf="service.json",
        mean_service_duration=20,
        overlap_service_percent=20,
        cloud_attenuation=1.0,
    )
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
