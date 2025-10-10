#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: testpypi publish
cd /Users/example/PycharmProjects/agilab
export PYTHONUNBUFFERED='1 PYDEVD_USE_FRAME_EVAL=NO'
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/tools/pypi_publish.py --repo testpypi --leave-most-recent --verbose --git-commit-version --git-reset-on-failure --cleanup $Prompt:Cleanup credentials$
