#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: mycode test manager
cd /Users/example/PycharmProjects/agilab/src/agilab/apps/mycode_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/src/agilab/apps/mycode_project/test/_test_mycode_manager.py
