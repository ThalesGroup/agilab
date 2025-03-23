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
import tomli
import tomli_w

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
    """
    Updates the 'agi-core' package path in the pyproject.toml file for a given module.

    Args:
        module (str): The module name (using underscore as separator).

    Raises:
        FileNotFoundError: If the pyproject.toml file cannot be found.
        RuntimeError: If an error occurs during reading or writing the TOML file.
    """
    # Locate the AGI installation and construct the root path
    agi_root = AgiEnv.locate_agi_installation()
    # Convert agi_root to POSIX string
    agi_root_str = agi_root.as_posix()

    # Build the module path based on naming conventions (underscores to hyphens)
    module_dirname = f"apps/{module.replace('_', '-')}-project"
    module_path = Path(agi_root_str) / module_dirname
    pyproject_file = module_path / "pyproject.toml"

    if not pyproject_file.exists():
        raise FileNotFoundError(f"pyproject.toml not found in {module_path}")

    try:
        with pyproject_file.open("rb") as f:
            content = tomli.load(f)
    except Exception as e:
        raise RuntimeError(f"Error loading TOML from {pyproject_file}: {e}")

    # On non-Windows, ensure agi_root_str ends with a slash
    if os.name != "nt" and not agi_root_str.endswith("/"):
        agi_root_str += "/"

    # Compute the agi-core path
    agi_core = f"{agi_root_str}fwk/core"

    # Safely retrieve (or create) the nested structure for tool/uv/sources
    sources = content.setdefault("tool", {}).setdefault("uv", {}).setdefault("sources", {})

    # Update the 'agi-core' entry if it exists and is a dict
    if isinstance(sources.get("agi-core"), dict) and "path" in sources["agi-core"]:
        sources["agi-core"]["path"] = agi_core
    else:
        print(f"Warning: 'agi-core' entry not found or invalid in {pyproject_file}; skipping update.")

    try:
        with pyproject_file.open("wb") as f:
            tomli_w.dump(content, f)
    except Exception as e:
        raise RuntimeError(f"Error writing updated TOML to {pyproject_file}: {e}")

    print("Updated", pyproject_file)


async def main():
    """
    Main asynchronous function to resolve paths in pyproject.toml and install a module using AGI.
    """
    try:
        resolve_packages_path_in_toml(module)
    except Exception as e:
        raise Exception("Failed to resolve env and core path in toml") from e

    await AGI.install(module, scheduler="127.0.0.1", verbose=3, modes_enabled= AGI.DASK_MODE | AGI.CYTHON_MODE)

if __name__ == '__main__':
    asyncio.run(main())