#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight AGI.install
cd /Users/example/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/src/agilab/examples/flight/AGI.install_flight.py
