#!/usr/bin/env bash
set -euo pipefail

# -----------------------------
# Config
# -----------------------------
WORKSPACE = "$home/../agi-space"
VENV="${WORKSPACE}/.venv"
PACKAGES="agilab agi-env agi-node agi-cluster agi-core"
SOURCE="local"     # local | pypi | testpypi
VERSION=""         # optional, e.g. 1.2.3
AGI_INSTALL_PATH=""

usage() {
  echo "Usage: $0 ---install-path install-path [--source local|pypi|testpypi] [--version X.Y.Z]"
  exit 1
}

# -----------------------------
# Args
# -----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --install-path) AGI_INSTALL_PATH="$2"; shift 2 ;;
    *) usage ;;
  esac
done


echo "===================================="
echo " MODE:     ${SOURCE}"
echo " VERSION:  ${VERSION:-<latest>}"
echo " INSTALL_PATH: ${AGI_INSTALL_PATH}"
echo "===================================="


home=$(pwd)

# Build the main project as a sdist and move it
rm -rf dist
rm -rf build
uv build --wheel
mv dist/*.whl "$home/../agi-space"

# -----------------------------
# Workspace / venv
# -----------------------------
mkdir -p "${WORKSPACE}"

pushd "$WORKSPACE"
rm -fr .venv uv.lock
if [ ! -f pyproject.toml ]; then
    uv init --bare
fi
uv add --upgrade --force-reinstall *.whl
popd > /dev/null

# -----------------------------
# Installation modes
# -----------------------------
case "${SOURCE}" in
  local)
    echo "Installing packages from local source tree..."
    AGI_ROOT=AGI_INSTALL_PATH.remove_suffix('src/agilab')
    uv pip install -e "${AGI_ROOT}/agilab"
    for pkg in ${PACKAGES}; do
      if [[ -d "${AGI_INSTALL_PATH}/core/${pkg}" ]]; then
        uv pip install -e "${AGI_INSTALL_PATH}/core/${pkg}"
      fi
    done
    ;;

  pypi)
    echo "Installing from PyPI..."
    if [[ -z "${VERSION}" ]]; then
      uv pip install --upgrade ${PACKAGES}
    else
      # shellcheck disable=SC2046
      uv pip install --upgrade $(for p in ${PACKAGES}; do printf "%s==%s " "${p}" "${VERSION}"; done)
    fi
    ;;

  testpypi)
    INDEX_URL="https://test.pypi.org/simple"
    EXTRA_INDEX_URL="https://pypi.org/simple"

    # ensure 'packaging' is available for the resolver snippet
    python -m pip install --quiet packaging

    # Helper: resolve a single latest version that exists for *all* packages on TestPyPI
    resolve_common_latest() {
      python - "$@" <<'PY'
import json, sys, urllib.request
from packaging.version import Version

pkgs = sys.argv[1:]

def releases(pkg):
    with urllib.request.urlopen(f"https://test.pypi.org/pypi/{pkg}/json") as r:
        data = json.load(r)
    # only versions that actually have files
    return {v for v, files in data.get("releases", {}).items() if files}

common = None
for pkg in pkgs:
    rs = releases(pkg)
    common = rs if common is None else (common & rs)

if not common:
    # signal "not ready yet"
    print("", end="")
    sys.exit(0)

# pick highest PEP 440 version
latest = str(sorted((Version(v) for v in common))[-1])
print(latest, end="")
PY
    }

    # If no VERSION is provided, compute a common latest with brief retries
    if [[ -z "${VERSION}" ]]; then
      echo "Resolving newest *common* TestPyPI version across: ${PACKAGES}"
      attempt=0
      VERSION=""
      until [[ -n "${VERSION}" || ${attempt} -ge 10 ]]; do
        VERSION="$(resolve_common_latest ${PACKAGES} || true)"
        if [[ -z "${VERSION}" ]]; then
          attempt=$((attempt+1))
          sleep 3
        fi
      done
      if [[ -z "${VERSION}" ]]; then
        echo "ERROR: Could not find a common version for all packages on TestPyPI after retries." >&2
        exit 1
      fi
      echo "✔ Using version ${VERSION} for all packages"
    else
      echo "Installing from TestPyPI (forced VERSION=${VERSION} for all)…"
    fi

    echo "Installing packages: ${PACKAGES} == ${VERSION}"
    # Single resolver run, all pins at once (fast & consistent)
    # shellcheck disable=SC2046
    uv pip install \
      --index-url "${INDEX_URL}" \
      --extra-index-url "${EXTRA_INDEX_URL}" \
      --index-strategy unsafe-best-match \
      --upgrade --reinstall --no-cache-dir \
      $(for p in ${PACKAGES}; do printf "%s==%s " "${p}" "${VERSION}"; done)
    ;;

  *)
    usage
    ;;
esac

# -----------------------------
# Show results
# -----------------------------
echo "===================================="
echo "Installed packages in venv:"
"${VENV}/bin/python" -m pip list | grep -E '^(agilab|agi-)'
echo "===================================="
