#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: link_sim AGI.install
cd /Users/jpm/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/examples/link_sim/AGI.install_link_sim.py
