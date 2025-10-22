import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve()
CORE_ENV = ROOT.parents[3] / "core/agi-env/src"
CORE_NODE = ROOT.parents[3] / "core/node/src"
APP_SRC = ROOT.parents[1] / "src"
for candidate in (CORE_ENV, CORE_NODE, APP_SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from agi_env import AgiEnv
from mycode import Mycode, MycodeArgs


def _build_env() -> AgiEnv:
    return AgiEnv(apps_dir=ROOT.parents[2], active_app="mycode_project", verbose=1)


async def main() -> None:
    env = _build_env()
    mycode = Mycode(env, args=MycodeArgs())
    workers = {"worker1": 1, "worker2": 2}
    result = mycode.build_distribution(workers)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
