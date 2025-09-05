
import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv, normalize_path
from pathlib import Path

async def main():
    app_env = AgiEnv(active_app=Path('/Users/jpm/agi-space/apps/flight_project'), install_type=1, verbose=True) 
    res = await AGI.run(app_env, 
                        mode=None, 
                        scheduler=None, 
                        workers=None, 
                        data_source="file", path="data/flight/dataset", files="csv/*", nfile=2, nskip=0, nread=0, sampling_rate=1.0, datemin="2020-01-01", datemax="2021-01-01", output_format="csv")
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
            