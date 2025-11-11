# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
# OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import sys
import asyncio
from pathlib import Path
import argparse
import errno
import getpass

core_root = Path(__file__).parents[1]
node_src = str(core_root / 'core/node/src')
env_src = core_root / 'core/agi-env/src'
sys.path.insert(0, node_src)
if env_src.exists():
    sys.path.insert(0, str(env_src))
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

# Take the first argument from the command line as the module name
if len(sys.argv) > 1:
    project = sys.argv[1]
    module = project.replace("_project", "").replace('-', '_')
else:
    raise ValueError("Please provide the module name as the first argument.")

print('install module:', module)


def ensure_data_storage(env: AgiEnv) -> None:
    """Guarantee the app data directory is available before invoking AGI installers."""

    data_root = (env.home_abs / env.data_rel).expanduser()
    try:
        data_root.mkdir(parents=True, exist_ok=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Required data directory {data_root} is unavailable. "
            "Verify the data URI share is mounted before running install."
        ) from exc
    except OSError as exc:
        if exc.errno in {
            errno.ENOENT,
            errno.EHOSTDOWN,
            errno.ESTALE,
            errno.ENOTCONN,
            errno.EIO,
        }:
            raise RuntimeError(
                f"Unable to reach data directory {data_root} ({exc.strerror or exc}). "
                "Verify the data URI share is mounted before running install."
            ) from exc
        raise


async def main():
    """
    Main asynchronous function to resolve paths in pyproject.toml and install a module using AGI.
    """
    try:
        parser = argparse.ArgumentParser(
            description="Run AGILAB application with custom options."
        )

        parser.add_argument("active_app", type=str, help="Path to the app project (e.g. src/agilab/apps/flight_project)")

        parser.add_argument(
            "--verbose", type=int, default=1, help="Verbosity level (1-3 default: 1)"
        )

        args, unknown = parser.parse_known_args()

        app_path = Path(args.active_app).expanduser()
        app_env = AgiEnv(
            apps_dir=app_path.parent,
            app=app_path.name,
            verbose=args.verbose,
        )

    except Exception as e:
        raise Exception("Failed to resolve env and core path in toml") from e

    try:
        ensure_data_storage(app_env)
    except RuntimeError as err:
        print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    await AGI.install(
        env=app_env,
        scheduler="127.0.0.1",
        verbose=args.verbose,
        modes_enabled=AGI.DASK_MODE | AGI.CYTHON_MODE
    )

    local_user = getpass.getuser()
    ssh_user = (app_env.user or "").strip()
    if ssh_user and ssh_user != local_user:
        repo_root = Path(__file__).resolve().parents[3]
        agi_core_dist = repo_root / "src/agilab/core/agi-core/dist"
        install_hint = f"sudo uv add {agi_core_dist}/*.whl"
        print(
            f"[INFO] Current user '{local_user}' differs from cluster SSH user '{ssh_user}'. "
            "Ask the 'agi' login to run:\n"
            "  uv init --bare --no-workspace\n"
            f"  {install_hint}"
        )
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
