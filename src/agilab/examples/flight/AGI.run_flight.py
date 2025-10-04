import asyncio
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

# Default to repository apps directory and flight project
APPS_DIR = "/Users/jpm/agilab/src/agilab/apps"
APP = "flight_project"

async def main():
    env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)
    res = await AGI.run(
        env,
        mode=0,
        scheduler=None,
        workers=None,
        data_source="file",
        data_uri="data/flight/dataset",
        files="*",
        nfile=1,
        nskip=0,
        nread=0,
        sampling_rate=1.0,
        datemin="2020-01-01",
        datemax="2021-01-01",
        output_format="parquet",
    )
    print(res)
    return res

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

