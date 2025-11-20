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
from agi_node.agi_dispatcher import BaseWorker


async def _build_worker(mode: int) -> None:
    active_app = ROOT.parents[1]
    env = AgiEnv(apps_dir=ROOT.parents[2], active_app=active_app.name, verbose=1)

    wenv = env.wenv_abs
    build_cmd = f"uv run --project {wenv} python -m agi_node.agi_dispatcher.build --app-path {wenv}"
    await env.run(f"{build_cmd} -q bdist_egg --packages \"agi_dispatcher, polars_worker\" -d '{wenv}'", wenv)
    await env.run(f"{build_cmd} -q build_ext -b '{wenv}'", wenv)

    args = {
        "param1": 0,
        "param2": "some text",
        "param3": 3.14,
        "param4": True,
    }
    BaseWorker._new(mode=mode, env=env, verbose=3, args=args)
    result = await BaseWorker._run(mode=mode, args=args)
    print(result)


async def main() -> None:
    for mode in (0, 1, 3):
        await _build_worker(mode)


if __name__ == "__main__":
    asyncio.run(main())
