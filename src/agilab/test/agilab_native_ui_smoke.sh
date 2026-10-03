#!/usr/bin/env bash
set -euo pipefail

# This diagnostic checks the native host entrypoint and exits without a server.
# Pass uv run options such as --no-sync when inspecting an existing environment.
AGILAB_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec uv --preview-features extra-build-dependencies run \
  --project "$AGILAB_REPO_ROOT" --extra ui "$@" \
  python -m agi_web.react_python_host --help
