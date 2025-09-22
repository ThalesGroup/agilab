#!/usr/bin/env python3
"""
Run manager/worker test suites. Coverage is DISABLED by default.
Enable it with --with-cov (then XML + optional badge will be produced).
"""
import os
import asyncio
import sys
from pathlib import Path
from agi_env import AgiEnv


# Keep uv from mutating environments while running tests
os.environ.setdefault("UV_NO_SYNC", "1")


async def main() -> None:
    script_dir = Path(__file__).parent
    active_app = script_dir.absolute()  # manager project root (this repo)

    # Heuristic: corresponding worker checkout under ~/wenv/<name with project→worker>
    target_name = active_app.name.replace("_project", "")
    worker_name = target_name +  "_worker"
    worker_repo = Path.home() / "wenv" / worker_name

    env = AgiEnv(active_app=active_app, verbose=True)
    wenv = env.wenv_abs
    build = wenv / 'build.py'

    for cmd in [
        f"uv run --no-sync --project {wenv} {build} bdist_egg --packages base_worker,polars_worker -d {wenv}",
        f"uv run --no-sync --project {wenv} {build} build_ext --packages base_worker,polars_worker -b {wenv}",
        f"uv run --no-sync --project {active_app} {active_app}/test/_test_{target_name}_manager.py",
        f"uv run --no-sync --project {worker_repo} {active_app}/test/_test_{target_name}_worker.py"
    ]:
        await env.run(cmd, wenv)

    print("✅ All done.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
