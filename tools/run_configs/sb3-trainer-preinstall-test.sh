#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: sb3_trainer_preinstall test
cd /Users/jpm/PycharmProjects/agilab/src/agilab/apps/sb3_trainer_project
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/src/agilab/apps/sb3_trainer_project/src/sb3_trainer_worker/pre_install.py remove_decorators --verbose --worker_path /Users/jpm/wenv/sb3_trainer_worker/src/sb3_trainer_worker/sb3_trainer_worker.py
