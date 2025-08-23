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

import os
import sys
import asyncio
from pathlib import Path
import argparse

node_src = str(Path(__file__).parent.parent / 'core/node/src')
sys.path.insert(0, node_src)
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

# Take the first argument from the command line as the module name
if len(sys.argv) > 1:
    project = sys.argv[1]
    module = project.replace("_project", "").replace('-', '_')
else:
    raise ValueError("Please provide the module name as the first argument.")

print('install module:', module)


async def main():
    """
    Main asynchronous function to resolve paths in pyproject.toml and install a module using AGI.
    """
    try:
        parser = argparse.ArgumentParser(
            description="Run AGILAB application with custom options."
        )

        parser.add_argument("app", type=str, help="Module name")

        parser.add_argument(
            "--install-type", type=str, help="Install type", required=True
        )
        parser.add_argument(
            "--verbose", type=int, default=3, help="Verbosity level (default: 3)"
        )

        args, unknown = parser.parse_known_args()
        # print(args.apps_dir)
        app_env = AgiEnv(Path(args.app), install_type=int(args.install_type),
                     verbose=args.verbose)

    except Exception as e:
        raise Exception("Failed to resolve env and core path in toml") from e

    await AGI.install(
        env=app_env,
        type=int(args.install_type),
        scheduler="127.0.0.1",
        verbose=args.verbose,
        modes_enabled=AGI.DASK_MODE | AGI.CYTHON_MODE
    )


if __name__ == '__main__':
    asyncio.run(main())

