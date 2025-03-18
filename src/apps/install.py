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
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
import sys
import asyncio
from pathlib import Path
import toml

core_src = str(Path(__file__).parent.parent / 'fwk/core/src')
sys.path.insert(0, core_src)
from agi_core.managers.agi_runner import AGI

from agi_env.agi_env import AgiEnv

# Take the first argument from the command line as the module name
if len(sys.argv) > 1:
    project = sys.argv[1]
    module = project.replace("-project", "").replace('-', '_')
else:
    raise ValueError("Please provide the module name as the first argument.")

print('install module:', module)
project_root = AgiEnv(module).apps_root


def resolve_packages_path_in_toml(module):
    agi_root = AgiEnv.locate_agi_installation() / "agi"
    agi_root = agi_root.as_posix()
    module_path = agi_root / Path("apps/" + module.replace("_", "-") + "-project")
    pyproject_file = module_path / "pyproject.toml"

    if not pyproject_file.exists():
        raise FileNotFoundError("pyproject.toml not found in", module_path)

    content = toml.load(pyproject_file)

    if os.name != "nt":
        agi_root = str(agi_root) + "/"

    agi_core = f"{agi_root}fwk/core"

    if "path" in content["tool"]["uv"]["sources"]["agi-core"]:
        content["tool"]["uv"]["sources"]["agi-core"]["path"] = agi_core

    with pyproject_file.open("w") as f:
        toml.dump(content, f)

    print("Updated", pyproject_file)


async def main():
    """
    Main asynchronous function to remove pdm lock file and install a module using Agi.

    Raises:
        FileNotFoundError: If the pdm lock file does not exist.
        OSError: If there is an issue removing the pdm lock file.
        Exception: If there is an error during module installation.
    """
    try:
        resolve_packages_path_in_toml(module)
    except:
        raise Exception("Failed to resolve env and core path in toml")

    await AGI.install(module, verbose=3, modes_enabled=0b0110)


if __name__ == '__main__':
    asyncio.run(main())