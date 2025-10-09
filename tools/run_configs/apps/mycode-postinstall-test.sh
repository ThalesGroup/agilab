#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode_postinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/wenv/mycode_worker/src/mycode_worker/post_install.py /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project 1 /Users/jpm/data/mycode
