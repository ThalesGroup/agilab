#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight install
cd /Users/example/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/log/execute/flight/AGI_install_flight.py
