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


async def main() -> None:
    apps_dir = ROOT.parents[2]
    env = AgiEnv(apps_dir=apps_dir, active_app="mycode_project", verbose=1)
    print(f"AgiEnv initialized for app: {env.app}")


if __name__ == "__main__":
    asyncio.run(main())
