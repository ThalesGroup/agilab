#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: app install (local)
cd /Users/example/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/src/agilab/apps/install.py $Prompt:selected app:~/PycharmProjects/agilab/src/agilab/apps/flight_project$ --install-type "1" --verbose 1
