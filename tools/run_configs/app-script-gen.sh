#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: app_script gen
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/PycharmProjects/agilab/pycharm/gen_app_script.py $Prompt:Enter app manager name:flight$
