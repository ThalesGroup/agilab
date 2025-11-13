#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: link_sim test worker
cd /Users/agi/PycharmProjects/agilab/src/agilab/apps/link_sim_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/src/agilab/apps/link_sim_project/test/_test_link_sim_worker.py
