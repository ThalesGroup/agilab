#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_postinstall test
cd /Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/wenv/flight_worker/src/flight_worker/post_install.py /Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project 1 /Users/example/data/flight
