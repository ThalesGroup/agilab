import sys
from pathlib import Path
from agi_manager import BaseWorker
from agi_env import AgiEnv
import asyncio

with open(Path().home() / ".local/share/agilab/.core-path",'r') as f:
    fwk_path = Path(f.read().strip())

path = str(fwk_path / "core/cluster/src")
if path not in sys.path:
    sys.path.insert(0, path)

path = str(fwk_path / "core/node/src")
if path not in sys.path:
    sys.path.insert(0, path)

path = str(fwk_path / "core/env/src")
if path not in sys.path:
    sys.path.insert(0, path)


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

    env = AgiEnv(active_app="flight", install_type=1, verbose=True)
    cmd = f"{env.uv} run python build.py build_ext --packages 'base_worker, polars_worker' -b {env.wenv_abs}"
    await AgiEnv.run(cmd, env.wenv_abs)

    # BaseWorker.run flight command
    for i in  range(4):
        env = AgiEnv(install_type=1,active_app="flight_project",verbose=True)
        BaseWorker.new("flight_project", mode=i, env=env, verbose=3, args=args)
        result = BaseWorker.run(workers={"192.168.137.1":2}, mode=i, args=args)
        print(result)

if __name__ == "__main__":
    asyncio.run(main())