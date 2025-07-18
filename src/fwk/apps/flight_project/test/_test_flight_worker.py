import sys
from pathlib import Path
base_path = Path(__file__).resolve().parents[3]
path = str(base_path  / "core/node/src")
if path not in sys.path:
    sys.path.append(path)
from agi_node.agi_dispatcher import BaseWorker
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

    sys.path.insert(0, base_path / 'apps/flight_project/src')
    sys.path.insert(0,'~/wenv/flight_worker/dist')

    for i in [0, 1, 2, 3]: # 2 is working only if you have generate the cython lib before
        env = AgiEnv(install_type=1,active_app="flight_project",verbose=True)
        # build the egg
        wenv = env.wenv_abs
        build = wenv /"build.py"
        menv = env.wenv_abs
        cmd = f"uv run --project {menv} python {build} bdist_egg --packages base_worker, polars_worker -d {menv}"
        env.run(cmd, menv)

        # build cython lib
        cmd = f"uv run --project {wenv} python {build} build_ext --packages base_worker, polars_worker -b {wenv}"
        env.run(cmd, wenv)

        path = str(env.home_abs / "/src")
        if path not in sys.path:
            sys.path.insert(0, path)
        BaseWorker.new("flight_project", mode=i, env=env, verbose=3, args=args)
        result = BaseWorker.test(mode=i, args=args)
        print(result)

if __name__ == "__main__":
    asyncio.run(main())