#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: lab_run test
cd /Users/example/agi-workspace/
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/example/agi-workspace/.venv/lib/python3.12/site-packages/agilab/lab_run.py --openai-api-key "your-key"
