#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode test worker
cd /Users/agi/PycharmProjects/agilab/src/agilab/apps/builtin/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/src/agilab/apps/builtin/mycode_project/test/_test_mycode_worker.py
