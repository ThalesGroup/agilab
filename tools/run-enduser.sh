#!/usr/bin/env bash
set -euo pipefail

pushd "$HOME" >/dev/null
  mkdir -p agi-space || true
  pushd "agi-space" >/dev/null
    rm -fr .venv uv.lock
    uv init --bare --no-workspace
    uv add -p 3.13  --index-url "https://test.pypi.org/simple" --extra-index-url "https://pypi.org/simple" \
      --index-strategy unsafe-best-match --upgrade --force-reinstall agilab agi-core
    uv run agilab --openai-api-key "your-api-key"
  popd >/dev/null
popd >/dev/null