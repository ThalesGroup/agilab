#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: apps-pages smoke
cd /Users/jpm/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/tools/smoke_apps_pages.py --active-app /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_project --timeout 20
