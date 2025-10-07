#!/usr/bin/env bash
set -euo pipefail

# Resolve repository root regardless of the invocation directory.
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
STUB_SCRIPT="$REPO_ROOT/docs/gen_stubs.py"
OUTPUT_DIR="$REPO_ROOT/docs/stubs"

if [[ ! -f "$STUB_SCRIPT" ]]; then
  echo "[gen-docs] Missing stub generator at $STUB_SCRIPT" >&2
  exit 1
fi

echo "[gen-docs] Generating API stubs …"
uv run python "$STUB_SCRIPT" --clean --output "$OUTPUT_DIR"

# Attempt to build the HTML documentation if a Sphinx configuration is present.
if [[ -f "$REPO_ROOT/docs/conf.py" ]]; then
  echo "[gen-docs] Building documentation via Sphinx (docs/conf.py) …"
  uv run sphinx-build -b html "$REPO_ROOT/docs" "$REPO_ROOT/docs/html"
elif [[ -f "$REPO_ROOT/docs/source/conf.py" ]]; then
  echo "[gen-docs] Building documentation via Sphinx (docs/source/conf.py) …"
  uv run sphinx-build -b html "$REPO_ROOT/docs/source" "$REPO_ROOT/docs/html"
else
  echo "[gen-docs] No Sphinx configuration found (docs/conf.py or docs/source/conf.py). Skipping HTML build." >&2
fi
