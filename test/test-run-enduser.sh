#!/usr/bin/env bash
set -euo pipefail

push agi-space
rm -fr .venv uv.lock || true
mkdir -f agi-space && cd agi-space
uv init --bare --no-workspace
uv add -p 3.13  --index-url "https://test.pypi.org/simple" --extra-index-url "https://pypi.org/simple" \
  --index-strategy unsafe-best-match --upgrade --force-reinstall agilab agi-core
uv run agilab --openai-api-key "your-api-key"
popd >/dev/null