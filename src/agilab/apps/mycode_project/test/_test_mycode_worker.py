import sys
from pathlib import Path
from agi_node.agi_dispatcher import BaseWorker
from agi_env import AgiEnv
import asyncio

async def main():
    args = {
        'param1': 0,
        'param2': "some text",
        'param3': 3.14,
        'param4': True
    }
    base_path = Path(__file__).resolve().parents[3]
    sys.path.insert(0, base_path/ 'apps/mycode_project/src')
    sys.path.insert(0,'~/wenv/mycode_worker/dist')

    active_app = Path(__file__).resolve().parents[1]
    env = AgiEnv(active_app=active_app, verbose=True)
    # build the egg
    wenv = env.wenv_abs
    build = wenv / "build.py"
    menv = env.wenv_abs
    cmd = f"uv run --project {menv} python {build} bdist_egg --packages 'base_worker, dag_worker' -d '{menv}'"
    await env.run(cmd, menv)

    # build cython lib
    cmd = f"uv run --project {wenv} python {build} build_ext --packages base_worker, dag_worker -b '{wenv}'"
    await env.run(cmd, wenv)

    # BaseWorker.run flight command
    for i in  [0,1,3]: # 2 is working only if you have generate the cython lib before
        with open(env.home_abs / ".local/share/agilab/.agilab-path", 'r') as f:
            agilab_path = Path(f.read().strip())

        path = str(agilab_path / "core/node/src")
        if path not in sys.path:
            sys.path.insert(0, path)

        path = str(agilab_path / "core/env/src")
        if path not in sys.path:
            sys.path.insert(0, path)
        BaseWorker.new('mycode', mode=i, env=env, verbose=3, args=args)
        result = await BaseWorker.run(mode=i, args=args)

    print(result)


if __name__ == "__main__":
    asyncio.run(main())