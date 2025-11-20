#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: app install (local)
cd /Users/agi/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/agi/PycharmProjects/agilab/src/agilab/apps/install.py $Prompt:selected app:~/PycharmProjects/agilab/src/agilab/apps/builtin/flight_project$ --install-type "1" --verbose 1
