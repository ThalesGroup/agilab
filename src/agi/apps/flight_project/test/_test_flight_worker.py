import sys
from agi_manager import BaseWorker
from agi_env import AgiEnv
import asyncio

async def main():
    args = {
        'data_source': "file",
        'path': "data/flight/dataset",
        'files': "csv/*",
        'nfile': 1,
        'nskip': 0,
        'nread': 0,
        'sampling_rate': 10.0,
        'datemin': "2020-01-01",
        'datemax': "2021-01-01",
        'output_format': "csv"
    }

    sys.path.insert(0,'/home/pcm/PycharmProjects/agilab/src/agi/apps/flight_project/src')
    sys.path.insert(0,'/home/pcm/wenv/flight_worker/dist')

    env = AgiEnv(active_app="flight", install_type=1, verbose=True)
    cmd = f"{env.uv} run python build.py build_ext --packages 'base_worker, polars_worker' -b {env.wenv_abs}"
    await AgiEnv.run(cmd, env.wenv_abs)

    # BaseWorker.run flight command
    for i in  range(4):
        env = AgiEnv(install_type=1,active_app="flight_project",verbose=True)
        BaseWorker.new("flight_project", mode=i, env=env, verbose=3, args=args)
        result = BaseWorker.run(workers={"192.168.20.123":2}, mode=i, args=args)
        print(result)

if __name__ == "__main__":
    asyncio.run(main())