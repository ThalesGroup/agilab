#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: apps-pages smoke
cd /Users/example/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/tools/smoke_apps_pages.py --active-app /Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project --timeout 20
