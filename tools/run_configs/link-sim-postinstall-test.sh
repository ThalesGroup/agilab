#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: link_sim_postinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/link_sim_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/wenv/link_sim_worker/src/link_sim_worker/post_install.py /Users/jpm/PycharmProjects/agilab/src/agilab/apps/link_sim_project 1 /Users/jpm/data/link_sim
