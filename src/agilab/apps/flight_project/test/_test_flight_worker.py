import sys
from pathlib import Path
base_path = Path(__file__).resolve()
path = str(base_path.parents[3]  / "core/node/src")
if path not in sys.path:
    sys.path.append(path)
from agi_node.agi_dispatcher import BaseWorker
from agi_env import AgiEnv
import asyncio


async def main():
    args = {
        'data_source': "file",
        'data_uri': "data/flight/dataset",
        'files': "csv/*",
        'nfile': 1,
        'nskip': 0,
        'nread': 0,
        'sampling_rate': 10.0,
        'datemin': "2020-01-01",
        'datemax': "2021-01-01",
        'output_format': "csv"
    }
    active_app_path = base_path.parents[1]
    sys.path.insert(0, active_app_path / 'src')
    sys.path.insert(0, str(Path.home() / 'wenv/flight_worker/dist'))

    apps_dir = base_path.parents[2]
    env = AgiEnv(apps_dir=apps_dir, active_app=active_app_path.name, verbose=True)
    # build the egg using the shared build module
    wenv = env.wenv_abs
    menv = env.wenv_abs
    module_cmd = f"uv run --project {menv} python -m agi_node.agi_dispatcher.build --app-path {menv}"
    cmd = f"{module_cmd} -q bdist_egg --packages \"agi_dispatcher, polars_worker\" -d '{menv}'"
    await env.run(cmd, menv)

    # build cython lib
    cmd = f"{module_cmd} -q build_ext -b '{wenv}'"
    await env.run(cmd, wenv)

    for i in [0, 1, 2, 3]: # 2 is working only if you have generate the cython lib before
        path = str(env.home_abs / "src")
        if path not in sys.path:
            sys.path.insert(0, path)
        BaseWorker._new(mode=i, env=env, verbose=3, args=args)
        result = await BaseWorker._run(mode=i, args=args)
        print(result)

if __name__ == "__main__":
    asyncio.run(main())
