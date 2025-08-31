#!/usr/bin/env bash
set -euo pipefail

# -----------------------------
# Config
# -----------------------------
WORKSPACE="${HOME}/agi-space"
VENV="${WORKSPACE}/.venv"
PACKAGES="agilab agi-env agi-node agi-cluster agi-core"
SRCROOT="${HOME}/agilab/src/agilab"

SOURCE="local"     # local | pypi | testpypi
VERSION=""         # optional, e.g. 1.2.3
CLEAN=false

usage() {
  echo "Usage: $0 [--source local|pypi|testpypi] [--version X.Y.Z] [--clean]"
  exit 1
}

# -----------------------------
# Args
# -----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --clean) CLEAN=true; shift ;;
    *) usage ;;
  esac
done

echo "===================================="
echo " MODE:     ${SOURCE}"
echo " VERSION:  ${VERSION:-<latest>}"
echo " WORKSPACE ${WORKSPACE}"
echo " CLEAN:    ${CLEAN}"
echo "===================================="

# -----------------------------
# Workspace / venv
# -----------------------------
if $CLEAN; then
  echo "⚠️ Deleting workspace ${WORKSPACE}"
  rm -rf "${WORKSPACE}"
fi

mkdir -p "${WORKSPACE}"
cd "${WORKSPACE}"

if [[ ! -d "${VENV}" ]]; then
  echo "Creating venv at ${VENV}"
  python3 -m venv "${VENV}"
fi

export PATH="${VENV}/bin:${PATH}"
python -m pip install --upgrade pip uv

# -----------------------------
# Clean local build artifacts (avoid stale wheels)
# -----------------------------
if [[ -d "${HOME}/agilab/src" ]]; then
  echo "Cleaning old build artifacts under ~/agilab/src..."
  find "${HOME}/agilab/src" -type d -name "build" -exec rm -rf {} +
  find "${HOME}/agilab/src" -type d -name "*.egg-info" -exec rm -rf {} +
fi

# -----------------------------
# Installation modes
# -----------------------------
case "${SOURCE}" in
  local)
    echo "Installing packages from local source tree..."
    for pkg in ${PACKAGES}; do
      if [[ -d "${SRCROOT}/apps/${pkg}" ]]; then
        uv pip install -e "${SRCROOT}/apps/${pkg}"
      elif [[ -d "${SRCROOT}/core/${pkg}" ]]; then
        uv pip install -e "${SRCROOT}/core/${pkg}"
      else
        echo "WARN: ${pkg} not found under apps/ or core/ in ${SRCROOT}" >&2
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
