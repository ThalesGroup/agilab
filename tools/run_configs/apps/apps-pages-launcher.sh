#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: apps-pages launcher
cd /Users/agi/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/tools/apps_pages_launcher.py --active-app /Users/agi/PycharmProjects/agilab/src/agilab/apps/builtin/flight_project
