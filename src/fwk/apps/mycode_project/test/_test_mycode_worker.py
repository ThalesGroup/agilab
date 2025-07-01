import sys
from pathlib import Path
from agi_manager import BaseWorker
from agi_env import AgiEnv
import asyncio

async def main():
    args = {
        'param1': 0,
        'param2': "some text",
        'param3': 3.14,
        'param4': True
    }

    sys.path.insert(0,'/Users/jpm/PycharmProjects/agilab/src/fwk/apps/mycode_project/src')
    sys.path.insert(0,'/Users/jpm/wenv/mycode_worker/dist')


    # BaseWorker.run flight command
    for i in  [0,1,3]: # 2 is working only if you have generate the cython lib before
        env = AgiEnv(install_type=1,active_app="mycode_project",verbose=True)
        with open(env.home_abs / ".local/share/agilab/.fwk-path", 'r') as f:
            fwk_path = Path(f.read().strip())

        path = str(fwk_path / "core/node/src")
        if path not in sys.path:
            sys.path.insert(0, path)

        path = str(fwk_path / "core/env/src")
        if path not in sys.path:
            sys.path.insert(0, path)
        BaseWorker.new('mycode', mode=i, env=env, verbose=3, args=args)
        result = BaseWorker.run(mode=i, args=args)

    print(result)


if __name__ == "__main__":
    asyncio.run(main())