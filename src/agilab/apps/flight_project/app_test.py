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
    apps_dir = script_dir.parent
    active_app = script_dir.name

    # Heuristic: corresponding worker checkout under ~/wenv/<name with project→worker>
    target_name = script_dir.name.replace("_project", "")
    worker_name = target_name +  "_worker"
    worker_repo = Path.home() / "wenv" / worker_name

    env = AgiEnv(apps_dir=apps_dir, active_app=active_app, verbose=True)
    wenv = env.wenv_abs
    for cmd in [
        f"uv run --no-sync --project {wenv} python -m agi_node.agi_dispatcher.build --app-path {wenv} "
        f"-q bdist_egg --packages agi_dispatcher,polars_worker -d {wenv}",
        f"uv run --no-sync --project {wenv} python -m agi_node.agi_dispatcher.build --app-path {wenv} "
        f"-q build_ext -b {wenv}",
        f"uv run --no-sync --project {script_dir} {script_dir}/test/_test_{target_name}_manager.py",
        f"uv run --no-sync --project {worker_repo} {script_dir}/test/_test_{target_name}_worker.py"
    ]:
        await env.run(cmd, wenv)

    print("✅ All done.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
