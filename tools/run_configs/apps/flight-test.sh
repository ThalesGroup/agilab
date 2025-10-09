#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight test
cd /Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project/app_test.py
