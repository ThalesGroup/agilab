#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode_postinstall test
cd /Users/example/PycharmProjects/agilab/src/agilab/apps/builtin/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py /Users/example/PycharmProjects/agilab/src/agilab/apps/builtin/mycode_project /Users/example/data/mycode
