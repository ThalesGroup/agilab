import sys
from pathlib import Path
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

    sys.path.insert(0,'/Users/jpm/PycharmProjects/agilab/src/fwk/apps/flight_project/src')
    sys.path.insert(0,'/Users/jpm/wenv/flight_worker/dist')

    # BaseWorker.run flight command
    for i in  [0,1,3]: # 2 is working only if you have generate the cython lib before
        env = AgiEnv(install_type=1,active_app="flight_project",verbose=True)
        with open(env.home_abs / ".local/share/agilab/.core-path", 'r') as f:
            fwk_path = Path(f.read().strip())

        path = str(env.home_abs / "/src")
        if path not in sys.path:
            sys.path.insert(0, path)
        BaseWorker.new("flight_project", mode=i, env=env, verbose=3, args=args)
        result = BaseWorker.run(mode=i, args=args)
        print(result)

if __name__ == "__main__":
    asyncio.run(main())