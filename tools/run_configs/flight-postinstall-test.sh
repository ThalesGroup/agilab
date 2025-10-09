#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_postinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/wenv/flight_worker/src/flight_worker/post_install.py /Users/jpm/PycharmProjects/agilab/src/agilab/apps/flight_project 1 /Users/jpm/data/flight
