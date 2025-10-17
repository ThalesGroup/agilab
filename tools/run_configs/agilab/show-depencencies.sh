#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: show depencencies
cd /Users/jpm/PycharmProjects/agilab
export PYTHONUNBUFFERED='1 PYDEVD_USE_FRAME_EVAL=NO'
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/tools/show_dependencies.py --repo pypi
