#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: builtin/mycode_postinstall test
cd "$REPO_ROOT/src/agilab/apps/builtin/mycode_project"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
uv run python $REPO_ROOT/src/agilab/core/agi-node/src/agi_node/agi_dispatcher/post_install.py $REPO_ROOT/src/agilab/apps/builtin/mycode_project $HOME/data/builtin/mycode
