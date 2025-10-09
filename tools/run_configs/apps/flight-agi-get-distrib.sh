#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight AGI.get_distrib
cd /Users/jpm/PycharmProjects/agilab/src/agilab/examples/flight
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/examples/flight/AGI.get_distrib_flight.py
