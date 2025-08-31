#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="$HOME/agi-space"
VENV="$WORKSPACE/.venv"
PACKAGES="agilab agi-env agi-node agi-cluster agi-core"

SOURCE="local"
VERSION=""
CLEAN=false

usage() {
  echo "Usage: $0 [--source local|pypi|testpypi] [--version X.Y.Z] [--clean]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --clean) CLEAN=true; shift ;;
    *) usage ;;
  esac
done

echo "===================================="
echo " MODE:     $SOURCE"
echo " VERSION:  ${VERSION:-<latest>}"
echo " WORKSPACE $WORKSPACE"
echo " CLEAN:    $CLEAN"
echo "===================================="

if $CLEAN; then
  echo "⚠️ Deleting workspace $WORKSPACE"
  rm -rf "$WORKSPACE"
fi

mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

# Create fresh venv
if [[ ! -d "$VENV" ]]; then
  echo "Creating venv at $VENV"
  python3 -m venv "$VENV"
fi

export PATH="$VENV/bin:$PATH"
python -m pip install --upgrade pip uv

# 🔥 Clean stale build artifacts (fix for old sources leaking into wheels)
echo "Cleaning old build artifacts under ~/agilab/src..."
find "$HOME/agilab/src" -type d -name "build" -exec rm -rf {} +
find "$HOME/agilab/src" -type d -name "*.egg-info" -exec rm -rf {} +

case "$SOURCE" in
  local)
    echo "Installing packages from local source tree..."
    for pkg in $PACKAGES; do
      if [[ -d "$HOME/src/agilab/apps/$pkg" ]]; then
        uv pip install -e "$HOME/src/agilab/apps/$pkg"
      elif [[ -d "$HOME/src/agilab/core/$pkg" ]]; then
        uv pip install -e "$HOME/src/agilab/core/$pkg"
      fi
    done
    ;;
  pypi)
    echo "Installing from PyPI..."
    for pkg in $PACKAGES; do
      if [[ -z "$VERSION" ]]; then
        uv pip install --upgrade "$pkg"
      else
        uv pip install --upgrade "$pkg==$VERSION"
      fi
    done
    ;;
    testpypi)
    INDEX_URL="https://test.pypi.org/simple"
    EXTRA_INDEX_URL="https://pypi.org/simple"

    if [[ -z "$VERSION" ]]; then
      echo "Resolving latest TestPyPI version per package..."
      for pkg in $PACKAGES; do
        v=$(curl -s "https://test.pypi.org/pypi/${pkg}/json" | jq -r '.info.version')
        if [[ -z "$v" || "$v" == "null" ]]; then
          echo "ERROR: no version found for $pkg on TestPyPI" >&2
          exit 1
        fi
        echo "  - $pkg → $v"
        uv pip install \
  --index-url "$INDEX_URL" \
  --extra-index-url "$EXTRA_INDEX_URL" \
  --index-strategy unsafe-best-match \
  --upgrade --reinstall \
  "${pkg}==${v}"

      done
    else
      echo "Installing from TestPyPI (forced VERSION=$VERSION for all)…"
      for pkg in $PACKAGES; do
        uv pip install \
          --index-url "$INDEX_URL" \
          --extra-index-url "$EXTRA_INDEX_URL" \
          --upgrade --reinstall \
          "${pkg}==${VERSION}"
      done
    fi
    ;;
  *)
    usage
    ;;
esac

echo "===================================="
echo "Installed packages in venv:"
"$VENV/bin/python" -m pip list | grep -E '^(agilab|agi-)'
echo "===================================="
