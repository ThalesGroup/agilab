#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: apps-pages smoke
cd /Users/agi/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/tools/smoke_preinit.py --active-app /Users/agi/PycharmProjects/agilab/src/agilab/apps/flight_project --timeout 20
