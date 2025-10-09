#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode_postinstall test
cd /Users/example/PycharmProjects/agilab/src/agilab/apps/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/wenv/mycode_worker/src/mycode_worker/post_install.py /Users/example/PycharmProjects/agilab/src/agilab/apps/mycode_project 1 /Users/example/data/mycode
