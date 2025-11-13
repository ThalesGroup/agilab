#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: link_sim_preinstall test
cd /Users/agi/PycharmProjects/agilab/src/agilab/apps/link_sim_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/pre_install.py remove_decorators --verbose --worker_path /Users/agi/wenv/link_sim_worker/src/link_sim_worker/link_sim_worker.py
