#!/usr/bin/env bash
set -euo pipefail

UV_PREVIEW=(uv --preview-features extra-build-dependencies)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
VERSION_ARG_SET=0
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
    --version) VERSION="$2"; VERSION_ARG_SET=1; shift 2 ;;
    *) usage ;;
  esac
done

verify_testpypi_versions() {
  local show_script="${SCRIPT_DIR}/show_dependencies.py"
  local python_bin="${VENV}/bin/python"
  if [[ ! -x "${python_bin}" ]]; then
    echo "[warn] Skipping version verification; missing Python interpreter at ${python_bin}" >&2
    return 0
  fi
  if [[ ! -f "${show_script}" ]]; then
    echo "[warn] Skipping version verification; show_dependencies.py not found at ${show_script}" >&2
    return 0
  fi

  local -a pkg_array
  read -r -a pkg_array <<< "${PACKAGES}"

  local force_version=""
  if [[ "${VERSION_ARG_SET}" -eq 1 && -n "${VERSION}" ]]; then
    force_version="${VERSION}"
  fi

  FORCE_TESTPYPI_VERSION="${force_version}" "${python_bin}" - "${show_script}" "${pkg_array[@]}" <<'PY'
import json
import os
import pathlib
import re
import subprocess
import sys

show_script = pathlib.Path(sys.argv[1])
packages = sys.argv[2:]
force_version = os.environ.get("FORCE_TESTPYPI_VERSION")

cmd = [sys.executable, str(show_script), "--repo", "testpypi"]
if force_version:
    cmd.extend(["--version", force_version])
cmd.extend(packages)
output = subprocess.check_output(cmd, text=True)
pattern = re.compile(r'^(ag[\w-]+) \(([^)]+)\) dependencies:', re.MULTILINE)
expected = {match.group(1).lower(): match.group(2) for match in pattern.finditer(output)}

pip_cmd = [sys.executable, "-m", "pip", "list", "--format", "json"]
installed_data = json.loads(subprocess.check_output(pip_cmd, text=True))
installed = {pkg["name"].lower(): pkg["version"] for pkg in installed_data}

mismatches = {}
for name, exp_version in expected.items():
    inst_version = installed.get(name)
    if inst_version != exp_version:
        mismatches[name] = (exp_version, inst_version)

if mismatches:
    print("[error] Version mismatch detected between TestPyPI metadata and installed packages:")
    for name, (exp_version, inst_version) in sorted(mismatches.items()):
        installed_label = inst_version if inst_version is not None else "missing"
        print(f"  {name}: expected {exp_version}, installed {installed_label}")
    sys.exit(1)

print("[info] TestPyPI agi* package versions match metadata.")
PY
}

# Deferred: local-source-only path check was here

echo "===================================="
echo " MODE:     ${SOURCE}"
echo " VERSION:  ${VERSION:-<latest>}"
echo "===================================="

# -----------------------------
# AGI_SPACE / venv
# -----------------------------
# moved: uv build --wheel
pushd "$AGI_SPACE" >/dev/null
rm -fr .venv uv.lock
if [ ! -f pyproject.toml ]; then
    uv init --bare --no-workspace
fi
${UV_PREVIEW[@]} sync

# -----------------------------
# Installation modes
# -----------------------------
case "${SOURCE}" in
  local)
  [[ -n "${AGI_INSTALL_PATH:-}" && -d "${AGI_INSTALL_PATH}" ]] || { echo "Error: Missing or invalid install path: ${AGI_INSTALL_PATH}" >&2; exit 1; }
  pushd "${AGI_INSTALL_ROOT}" >/dev/null
  uv build --wheel
  popd >/dev/null
    echo "Installing packages from local source tree..."
    for pkg in ${PACKAGES}; do
      if [[ -d "${AGI_INSTALL_PATH}/core/${pkg}" ]]; then
        ${UV_PREVIEW[@]} pip install --project "." --upgrade --no-deps "${AGI_INSTALL_PATH}/core/${pkg}"
      fi
    done
    ${UV_PREVIEW[@]} pip install --project "." --upgrade --no-deps "${AGI_INSTALL_ROOT}"
    ;;


  pypi)
    echo "Installing from PyPI..."
    if [[ -z "${VERSION}" ]]; then
      ${UV_PREVIEW[@]} pip install --project "." --upgrade ${PACKAGES}
    else
      # shellcheck disable=SC2046
      ${UV_PREVIEW[@]} pip install --project "." --upgrade $(for p in ${PACKAGES}; do printf "%s==%s " "${p}" "${VERSION}"; done)
    fi
    ;;

  testpypi)
    INDEX_URL="https://test.pypi.org/simple"
    EXTRA_INDEX_URL="https://pypi.org/simple"

    ${UV_PREVIEW[@]} pip install packaging

    resolve_common_latest() {
      uv run python - "$@" <<'PY'
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
    ${UV_PREVIEW[@]} pip install \
      --project "." \
      --index "${INDEX_URL}" \
      --extra-index-url "${EXTRA_INDEX_URL}" \
      --index-strategy unsafe-best-match \
      --upgrade --no-cache-dir \
      $(for p in ${PACKAGES}; do printf "%s==%s " "${p}" "${VERSION}"; done)

    if ! verify_testpypi_versions; then
      if [[ -z "${AGI_INSTALL_RETRY:-}" ]]; then
        echo "[warn] Version mismatch detected; retrying install once..." >&2
        if [[ "${VERSION_ARG_SET}" -eq 1 ]]; then
          AGI_INSTALL_RETRY=1 exec "$0" --source "${SOURCE}" --version "${VERSION}"
        else
          AGI_INSTALL_RETRY=1 exec "$0" --source "${SOURCE}"
        fi
      else
        echo "[error] TestPyPI package versions still do not match metadata after retry." >&2
        echo "        Resolve the mismatch (e.g. wait for all packages to publish ${VERSION}) and rerun." >&2
        exit 1
      fi
    fi
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
echo "Installed packages in agi-space/.venv:"
if ! "${VENV}/bin/python" -m pip list | grep -E '^(agilab|agi-)' ; then
  echo "(No agi* packages detected.)"
fi
echo "===================================="
