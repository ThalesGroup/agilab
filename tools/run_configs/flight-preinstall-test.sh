#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight_preinstall test
cd /Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/src/agilab/apps/flight_project/src/flight_worker/pre_install.py remove_decorators --verbose --worker_path /Users/example/wenv/flight_worker/src/flight_worker/flight_worker.py
