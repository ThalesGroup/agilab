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

import argparse
import os
import sys
from pathlib import Path
import streamlit.web.cli as stcli

def check_environment():

    # Check if current directory is acceptable:
    cwd = Path.cwd()
    # For example, accept if the cwd contains 'pyproject.toml'
    if not (cwd / "pyproject.toml").exists() and "agilab/src/agilab/gui" not in str(cwd):
        print("Error: Please run this command from a directory that contains your agilab project (e.g. the project root or agilab/src/agilab/gui).")
        sys.exit(1)

    # Check if the package is installed (optional):
    try:
        import agilab  # or any module from your package
    except ImportError:
        print("Error: The agilab package is not installed in this environment.")
        sys.exit(1)

def main():
    check_environment()

    parser = argparse.ArgumentParser(
        description="Run AGILAB application with custom options."
    )
    parser.add_argument(
        "--cluster-ssh-credentials", type=str, help="Cluster account user:password", default=None
    )
    parser.add_argument(
        "--openai-api-key", type=str, help="OpenAI API key", default=None
    )
    parser.add_argument(
        "--apps-dir", type=str, help="Directory for apps", default=None
    )
    parser.add_argument(
        "--install-type", type=str, help="Install type", default=None
    )
    # Parse known arguments; extra arguments are captured in `unknown`
    args, unknown = parser.parse_known_args()

    # Determine the target script (adjust path if necessary)
    target_script = str(Path(__file__).parent /"AGILAB.py")

    # Build the base argument list for Streamlit.
    new_argv = ["streamlit", "run", target_script]

    # Collect custom arguments.
    custom_args = []
    if args.cluster_ssh_credentials is not None:
        custom_args.extend(["--cluster-ssh-credentials", args.cluster_ssh_credentials])
    if args.openai_api_key is not None:
        custom_args.extend(["--openai-api-key", args.openai_api_key])
    if args.apps_dir is None:
        before, sep, after = __file__.rpartition(".venv")
        args.apps_dir = Path(before) / "apps"
    custom_args.extend(["--apps-dir", args.apps_dir])
    agi_path_storage = Path("~/").expanduser() / ".local/share/agilab/.agi-path"
    if args.install_type is not None:
        agilab_install = None
        custom_args.extend(["--install-type", args.install_type])
        if not args.install_type:
            if agi_path_storage.exists():
                with open(agi_path_storage, "r") as f:
                    agilab_install = f.read()
                    agilab_install = Path(agilab_install)
                    if not agilab_install.exists():
                        agilab_install = None
                    else:
                        print("agilab found in", agilab_install)
        if not agilab_install:
            os.makedirs(agi_path_storage.parent, exist_ok=True)
            with open(agi_path_storage, "w") as f:
                agilab_install = Path(args.apps_dir).parents[2].absolute()
                print("agilab found in", agilab_install)
                f.write(str(agilab_install))
        else:
            print("No agilab installed in", agilab_install)
            sys.exit(1)
    else:
        with open(agi_path_storage, "w") as f:
            f.write(str(Path(__file__).parents[1].absolute() / "agilab"))

    if unknown:
        custom_args.extend(unknown)

    # Only add the double dash and custom arguments if there are any.
    if custom_args:
        new_argv.append("--")
        new_argv.extend(custom_args)

    sys.argv = new_argv
    sys.exit(stcli.main())



if __name__ == "__main__":
    main()