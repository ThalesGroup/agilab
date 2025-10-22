import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve()
CORE_ENV = ROOT.parents[3] / "core/agi-env/src"
CORE_NODE = ROOT.parents[3] / "core/node/src"
for candidate in (CORE_ENV, CORE_NODE):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from agi_env import AgiEnv
from agi_node.agi_dispatcher import BaseWorker


async def main() -> None:
    env = AgiEnv(apps_dir=ROOT.parents[2], active_app="mycode_project", verbose=1)
    args = {
        "param1": 0,
        "param2": "some text",
        "param3": 3.14,
        "param4": True,
    }
    BaseWorker._new(env=env, mode=0, verbose=3, args=args)
    res = await BaseWorker._run(env=env, mode=0, workers={"127.0.0.1": 1}, args=args)
    print(res)


if __name__ == "__main__":
    asyncio.run(main())
