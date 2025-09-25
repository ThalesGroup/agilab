#!/usr/bin/env bash
set -euo pipefail

# Resolve repository root regardless of the invocation directory.
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PY_SCRIPT="$REPO_ROOT/docs/gen-docs.py"

if [[ ! -f "$PY_SCRIPT" ]]; then
  echo "[gen-docs] Missing generator at $PY_SCRIPT" >&2
  exit 1
fi

UV_RUN=(uv --preview-features extra-build-dependencies run)

"${UV_RUN[@]}" python "$PY_SCRIPT"
