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


def _detect_repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "agilab").is_dir():
            return candidate
    return None


def _running_from_uvx() -> bool:
    """Detect uvx or other uv tool environments that should not touch the source tree."""
    # `uv run` sets this; honour it so developers keep their standard workflow.
    if os.environ.get("UV_RUN_RECURSION_DEPTH"):
        return False

    prefix = Path(sys.prefix).resolve()
    uv_roots = [
        Path.home() / ".cache" / "uv",
        Path.home() / ".local" / "share" / "uv",
    ]
    return any(root == prefix or root in prefix.parents for root in uv_roots)


def _guard_against_uvx_in_source_tree() -> None:
    repo_root = _detect_repo_root(Path.cwd())
    if repo_root and _running_from_uvx():
        message = (
            "agilab: running inside the source checkout via `uvx` is not supported.\n"
            f"Current checkout: {repo_root}\n"
            "Use `uv run agilab` or the generated run-config wrappers instead."
        )
        raise SystemExit(message)

def main():
    _guard_against_uvx_in_source_tree()

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
        "--apps-dir", type=str, help="Where you store your apps (default is ./)",
                        default=None
    )

    # Parse known arguments; extra arguments are captured in `unknown`
    args, unknown = parser.parse_known_args()

    # Determine the target script (adjust path if necessary)
    target_script = str(Path(__file__).parent /"AGILAB.py")

    # Build the base argument list for Streamlit.
    new_argv = ["streamlit", "run", target_script]

    # Collect custom arguments (only pass what is provided).
    custom_args = []

    # SSH credentials are optional at wrapper level; pass through if provided.
    if args.cluster_ssh_credentials:
        custom_args.extend(["--cluster-ssh-credentials", args.cluster_ssh_credentials])

    # OpenAI API key is optional at wrapper level; pass through if provided.
    if args.openai_api_key:
        custom_args.extend(["--openai-api-key", args.openai_api_key])

    if args.apps_dir:
        custom_args.extend(["--apps-dir", Path.home() / "apps"])

    if unknown:
        custom_args.extend(unknown)

    # Only add the double dash and custom arguments if there are any.
    new_argv.append("--")
    new_argv.extend(custom_args)

    sys.argv = new_argv
    sys.exit(stcli.main())

if __name__ == "__main__":
    main()
