#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode_postinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project /Users/jpm/data/mycode
