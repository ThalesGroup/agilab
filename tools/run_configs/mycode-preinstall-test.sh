#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode_preinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project/src/mycode_worker/pre_install.py remove_decorators --verbose --worker_path /Users/jpm/wenv/mycode_worker/src/mycode_worker/mycode_worker.py
