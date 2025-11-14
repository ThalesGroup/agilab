#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode_preinstall test
cd /Users/example/PycharmProjects/agilab/src/agilab/apps/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path /Users/example/wenv/mycode_worker/src/mycode_worker/mycode_worker.py
