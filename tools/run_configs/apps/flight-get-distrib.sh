#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: flight get_distrib
cd /Users/example/PycharmProjects/agilab/src/agilab/examples/flight
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/src/agilab/examples/flight/AGI_get_distrib_flight.py
