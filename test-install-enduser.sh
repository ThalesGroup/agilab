#!/usr/bin/env bash
set -euo pipefail

# -----------------------------
# Config
# -----------------------------
AGI_SPACE="${HOME}/agi-space"
mkdir -p "$AGI_SPACE"
echo "Using AGI_SPACE: ${AGI_SPACE}"

[[ -d "${AGI_SPACE}" ]] || { echo "Error: Missing AGI_SPACE directory: ${AGI_SPACE}" >&2; exit 1; }
VENV="${AGI_SPACE}/.venv"
PACKAGES="agilab agi-env agi-node agi-cluster agi-core"
SOURCE="local"     # local | pypi | testpypi
VERSION=""         # optional, e.g. 1.2.3
AGI_PATH_FILE="$HOME/.local/share/agilab/.agilab-path"
AGI_INSTALL_PATH=""


if [[ -f "$AGI_PATH_FILE" ]]; then
    AGI_INSTALL_PATH="$(cat "$AGI_PATH_FILE")"
    echo "agilab install path: $AGI_INSTALL_PATH"
else
    echo "No saved agilab install path found." >&2
fi

AGI_INSTALL_ROOT="${AGI_INSTALL_PATH%/src/agilab}"

usage() {
  echo "Usage: $0 [--source local|pypi|testpypi] [--version X.Y.Z]"
  exit 1
}

# -----------------------------
# Args
# -----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    *) usage ;;
  esac
done

[[ -n "${AGI_INSTALL_PATH}" && -d "${AGI_INSTALL_PATH}" ]] || { echo "Error: Missing or invalid install path: ${AGI_INSTALL_PATH}" >&2; exit 1; }

echo "===================================="
echo " MODE:     ${SOURCE}"
echo " VERSION:  ${VERSION:-<latest>}"
echo "===================================="

# -----------------------------
# AGI_SPACE / venv
# -----------------------------
uv build --wheel

pushd "$AGI_SPACE" >/dev/null
rm -fr .venv uv.lock
if [ ! -f pyproject.toml ]; then
    uv init --bare --no-workspace
fi
uv sync

# -----------------------------
# Installation modes
# -----------------------------
case "${SOURCE}" in
  local)
    echo "Installing packages from local source tree..."

    uv pip install "${AGI_INSTALL_ROOT}/dist/agilab-"*.whl

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

    python -m pip install --quiet packaging

    resolve_common_latest() {
      python - "$@" <<'PY'
import json, sys, urllib.request
from packaging.version import Version

pkgs = sys.argv[1:]

def releases(pkg):
    with urllib.request.urlopen(f"https://test.pypi.org/pypi/{pkg}/json") as r:
        data = json.load(r)
    return {v for v, files in data.get("releases", {}).items() if files}

common = None
for pkg in pkgs:
    rs = releases(pkg)
    common = rs if common is None else (common & rs)

if not common:
    print("", end="")
    sys.exit(0)

latest = str(sorted((Version(v) for v in common))[-1])
print(latest, end="")
PY
    }

    if [[ -z "${VERSION}" ]]; then
      echo "Resolving newest *common* TestPyPI version across: ${PACKAGES}"
      attempt=0
      until [[ -n "${VERSION}" || ${attempt} -ge 10 ]]; do
        VERSION="$(resolve_common_latest ${PACKAGES} || true)"
        [[ -n "${VERSION}" ]] || { attempt=$((attempt+1)); sleep 3; }
      done
      [[ -n "${VERSION}" ]] || { echo "ERROR: Could not find a common version for all packages on TestPyPI after retries." >&2; exit 1; }
      echo "✔ Using version ${VERSION} for all packages"
    else
      echo "Installing from TestPyPI (forced VERSION=${VERSION} for all)…"
    fi

    echo "Installing packages: ${PACKAGES} == ${VERSION}"
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

popd >/dev/null
# -----------------------------
# Show results
# -----------------------------
echo "===================================="
echo "Installed packages in venv:"
"${VENV}/bin/python" -m pip list | grep -E '^(agilab|agi-)'
echo "===================================="
