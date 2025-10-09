#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight test manager
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_project/test/_test_flight_manager.py
