
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('/Users/jpm/agilab/src/agilab/apps/flight_project'), install_type=1, verbose=True)
    res = await AGI.get_distrib(app_env,
                               scheduler="127.0.0.1", 
                               workers={'127.0.0.1': 2},
                               data_source="file", data_uri="data/flight/dataset", files="csv/*", nfile=10, nskip=0, nread=10, sampling_rate=1.0, datemin="2020-01-01", datemax="2021-01-01", output_format="parquet")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
