#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: agilab run (dev)
cd /Users/jpm/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run streamlit run /Users/jpm/PycharmProjects/agilab/src/agilab/AGILAB.py -- --install-type 1 --openai-api-key "your-key" --apps-dir /Users/jpm/PycharmProjects/agilab/src/agilab/apps
