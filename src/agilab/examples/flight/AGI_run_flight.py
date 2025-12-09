
import asyncio
from pahtlib import Path
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

AGILAB_PATH = open(f"{Path.home()}/.local/share/agilab/.agilab-path").read().strip()
APPS_PATH = Path(AGILAB_PATH) / "apps"
APP = "flight_project"

async def main():
    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)
    res = await AGI.run(app_env, 
                        mode=15, 
                        scheduler="127.0.0.1",
                        workers={'127.0.0.1': 1},
                        data_source="file", data_in="flight/dataset", data_out="flight/dataframe", files="*", nfile=1, nskip=0, nread=0, sampling_rate=1.0, datemin="2020-01-01", datemax="2021-01-01", output_format="parquet")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())