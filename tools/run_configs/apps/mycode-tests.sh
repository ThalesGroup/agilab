#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode tests
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/apps/mycode_project/app_test.py
