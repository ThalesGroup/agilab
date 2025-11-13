#!/usr/bin/env bash
set -euo pipefail

UV_PREVIEW=(uv --preview-features extra-build-dependencies)
warn() {
  echo "[warn] $*" >&2
}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -----------------------------
# Config
# -----------------------------
AGI_SPACE="${HOME}/agi-space"
mkdir -p "$AGI_SPACE"
echo "Using AGI_SPACE: ${AGI_SPACE}"

APPS_ROOT="${AGI_SPACE}/apps"
mkdir -p "${APPS_ROOT}"

[[ -d "${AGI_SPACE}" ]] || { echo "Error: Missing AGI_SPACE directory: ${AGI_SPACE}" >&2; exit 1; }
VENV="${AGI_SPACE}/.venv"
PACKAGES="agilab agi-env agi-node agi-cluster agi-core"
SOURCE="local"     # local | pypi | testpypi
VERSION=""         # optional, e.g. 1.2.3
VERSION_ARG_SET=0
AGI_PATH_FILE="$HOME/.local/share/agilab/.agilab-path"
AGI_INSTALL_PATH=""
AGI_INSTALL_ROOT=""
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_SRC_DIR="${REPO_ROOT}/src/agilab"
ENV_FILE="$HOME/.agilab/.env"
FORCE_REBUILD="${FORCE_REBUILD:-0}"  # NEW: Allow forcing rebuild
SKIP_OFFLINE="${SKIP_OFFLINE:-0}"    # NEW: Skip offline deps for faster installs


if [[ -f "$AGI_PATH_FILE" ]]; then
    AGI_INSTALL_PATH="$(cat "$AGI_PATH_FILE")"
    echo "agilab install path: $AGI_INSTALL_PATH"
else
    echo "No saved agilab install path found." >&2
fi

usage() {
  echo "Usage: $0 [--source local|pypi|testpypi] [--version X.Y.Z] [--force-rebuild] [--skip-offline]"
  echo ""
  echo "Options:"
  echo "  --source         Installation source (local, pypi, testpypi)"
  echo "  --version        Specific version to install"
  echo "  --force-rebuild  Force rebuild even if venv exists"
  echo "  --skip-offline   Skip offline assistant (torch, transformers) for faster install"
  exit 1
}

persist_env_var() {
  local key="$1"
  local value="$2"
  local env_file="$3"
  python3 - "$env_file" "$key" "$value" <<'PY'
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]

if not env_path.parent.exists():
    env_path.parent.mkdir(parents=True, exist_ok=True)

lines: list[str]
if env_path.exists():
    lines = env_path.read_text(encoding="utf-8").splitlines()
else:
    lines = []

updated = False
for idx, line in enumerate(lines):
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    name, sep, _ = line.partition("=")
    if sep and name.strip() == key:
        lines[idx] = f"{key}={value}"
        updated = True
        break

if not updated:
    lines.append(f"{key}={value}")

env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

# -----------------------------
# Args
# -----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --version) VERSION="$2"; VERSION_ARG_SET=1; shift 2 ;;
    --force-rebuild) FORCE_REBUILD=1; shift ;;
    --skip-offline) SKIP_OFFLINE=1; shift ;;
    *) usage ;;
  esac
done

if [[ "$SOURCE" == "local" ]]; then
  if [[ -z "${AGI_INSTALL_PATH}" || ! -d "${AGI_INSTALL_PATH}" ]]; then
    if [[ -d "${REPO_SRC_DIR}" ]]; then
      AGI_INSTALL_PATH="${REPO_SRC_DIR}"
      echo "[info] Local source auto-detected at ${AGI_INSTALL_PATH}"
    else
      echo "Error: Unable to locate local source checkout (expected ${REPO_SRC_DIR})." >&2
      exit 1
    fi
  elif [[ "${AGI_INSTALL_PATH}" == */wenv/* ]]; then
    if [[ -d "${REPO_SRC_DIR}" ]]; then
      echo "[warn] Saved local install path (${AGI_INSTALL_PATH}) points to a worker environment; using ${REPO_SRC_DIR} instead."
      AGI_INSTALL_PATH="${REPO_SRC_DIR}"
    fi
  fi

  if [[ "${AGI_INSTALL_PATH}" != "${REPO_SRC_DIR}" && -d "${REPO_SRC_DIR}" ]]; then
    echo "[info] Persisting local install path to ${REPO_SRC_DIR}"
    AGI_INSTALL_PATH="${REPO_SRC_DIR}"
  fi

  printf '%s\n' "${AGI_INSTALL_PATH}" > "${AGI_PATH_FILE}"

  if [[ "${AGI_INSTALL_PATH}" == "${REPO_SRC_DIR}" ]]; then
    AGI_INSTALL_ROOT="${REPO_ROOT}"
  else
    AGI_INSTALL_ROOT="${AGI_INSTALL_PATH%/src/agilab}"
    if [[ -z "${AGI_INSTALL_ROOT}" || "${AGI_INSTALL_ROOT}" == "${AGI_INSTALL_PATH}" ]]; then
      AGI_INSTALL_ROOT="${AGI_INSTALL_PATH}"
    fi
  fi
fi

persist_env_var "APPS_DIR" "${APPS_ROOT}" "${ENV_FILE}"

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

echo "===================================="
echo " MODE:           ${SOURCE}"
echo " VERSION:        ${VERSION:-<latest>}"
echo " FORCE REBUILD:  ${FORCE_REBUILD}"
echo " SKIP OFFLINE:   ${SKIP_OFFLINE}"
echo "===================================="

# -----------------------------
# AGI_SPACE / venv
# -----------------------------
pushd "$AGI_SPACE" >/dev/null

# OPTIMIZATION 1: Only delete venv if forced or doesn't exist
if [[ "${FORCE_REBUILD}" -eq 1 ]]; then
  echo "[info] Force rebuild requested - removing existing venv and lock file"
  rm -fr .venv uv.lock
elif [[ ! -d .venv ]]; then
  echo "[info] No existing venv found - creating new one"
  rm -f uv.lock  # Remove stale lock file if venv is missing
else
  echo "[info] Using existing venv (use --force-rebuild to recreate)"
fi

if [ ! -f pyproject.toml ]; then
    uv init --bare --no-workspace
fi

# OPTIMIZATION 2: Use uv sync which respects lock files
${UV_PREVIEW[@]} sync

# Ensure pip is available inside the venv for any tooling that shells out to python -m pip
${UV_PREVIEW[@]} run python -m ensurepip --upgrade || true

# -----------------------------
# Installation modes
# -----------------------------
case "${SOURCE}" in
  local)
    if [[ -z "${AGI_INSTALL_ROOT:-}" ]]; then
      if [[ "${AGI_INSTALL_PATH}" == "${REPO_SRC_DIR}" ]]; then
        AGI_INSTALL_ROOT="${REPO_ROOT}"
      else
        AGI_INSTALL_ROOT="${AGI_INSTALL_PATH%/src/agilab}"
        if [[ -z "${AGI_INSTALL_ROOT}" || "${AGI_INSTALL_ROOT}" == "${AGI_INSTALL_PATH}" ]]; then
          AGI_INSTALL_ROOT="${AGI_INSTALL_PATH}"
        fi
      fi
    fi

    [[ -n "${AGI_INSTALL_ROOT}" && -d "${AGI_INSTALL_ROOT}" ]] || {
      echo "Error: Missing or invalid install path for local source: ${AGI_INSTALL_PATH}" >&2
      exit 1
    }

    [[ -n "${AGI_INSTALL_PATH:-}" && -d "${AGI_INSTALL_PATH}" ]] || { echo "Error: Missing or invalid install path: ${AGI_INSTALL_PATH}" >&2; exit 1; }

    # OPTIMIZATION 3: Create lock file ONCE at repo root if it doesn't exist
    pushd "${AGI_INSTALL_ROOT}" >/dev/null
    if [[ ! -f "uv.lock" || "${FORCE_REBUILD}" -eq 1 ]]; then
      echo "[info] Creating/updating lock file for local repo (one-time operation)..."
      uv lock --quiet
      echo "[info] Lock file created - future installs will be much faster!"
    else
      echo "[info] Using existing lock file from repo"
    fi

    # OPTIMIZATION 4: Build wheel only if needed
    WHEEL_DIR="${AGI_INSTALL_ROOT}/dist"
    NEEDS_BUILD=0
    if [[ ! -d "${WHEEL_DIR}" ]] || [[ "${FORCE_REBUILD}" -eq 1 ]]; then
      NEEDS_BUILD=1
    else
      # Check if any wheel exists
      if ! ls "${WHEEL_DIR}"/*.whl >/dev/null 2>&1; then
        NEEDS_BUILD=1
      fi
    fi

    if [[ "${NEEDS_BUILD}" -eq 1 ]]; then
      echo "[info] Building wheel from local source..."
      uv build --wheel --no-build-logs --quiet
    else
      echo "[info] Using existing wheel (use --force-rebuild to recreate)"
    fi
    popd >/dev/null

    # OPTIMIZATION 5: Install all packages in one command
    echo "Installing packages from local source tree..."
    INSTALL_PATHS=()
    for pkg in ${PACKAGES}; do
      if [[ -d "${AGI_INSTALL_PATH}/core/${pkg}" ]]; then
        INSTALL_PATHS+=("${AGI_INSTALL_PATH}/core/${pkg}")
      fi
    done
    INSTALL_PATHS+=("${AGI_INSTALL_ROOT}")

    # Install all at once instead of one-by-one
    if [[ ${#INSTALL_PATHS[@]} -gt 0 ]]; then
      ${UV_PREVIEW[@]} pip install --upgrade --no-deps "${INSTALL_PATHS[@]}"
    fi
    ;;

  pypi)
    echo "Installing from PyPI..."
    if [[ -z "${VERSION}" ]]; then
      ${UV_PREVIEW[@]} pip install --upgrade ${PACKAGES}
    else
      # shellcheck disable=SC2046
      ${UV_PREVIEW[@]} pip install --upgrade $(for p in ${PACKAGES}; do printf "%s==%s " "${p}" "${VERSION}"; done)
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
      echo "✓ Using version ${VERSION} for all packages"
    else
      echo "Installing from TestPyPI (forced VERSION=${VERSION} for all)…"
    fi

    echo "Installing packages: ${PACKAGES} == ${VERSION}"
    # pip 25 removed --index-strategy; rely on default resolver across indexes
    ${UV_PREVIEW[@]} run python -m pip install \
      --index "${INDEX_URL}" \
      --extra-index-url "${EXTRA_INDEX_URL}" \
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

# OPTIMIZATION 6: Make offline install optional and use UV instead of pip
install_offline_assistant() {
  if [[ "${SKIP_OFFLINE}" -eq 1 ]]; then
    echo "[info] Skipping offline assistant installation (--skip-offline flag set)"
    return
  fi

  local python_bin="${VENV}/bin/python"
  if [[ ! -x "${python_bin}" ]]; then
    warn "Skipping GPT-OSS install; missing interpreter at ${python_bin}"
    return
  fi

  local pyver major minor _
  pyver="$("${python_bin}" - <<'PY'
import sys
print(".".join(map(str, sys.version_info[:3])))
PY
)"

  IFS='.' read -r major minor _ <<< "${pyver}"
  if [[ -z "${major:-}" || -z "${minor:-}" ]]; then
    warn "Could not determine Python version; skipping GPT-OSS install"
    return
  fi

  if (( major > 3 || (major == 3 && minor >= 12) )); then
    echo "Installing GPT-OSS offline assistant dependencies..."
    echo "[info] This may take several minutes (downloading torch ~2GB, transformers, etc.)"
    echo "[info] To skip this in the future, use --skip-offline flag"

    # Use UV instead of pip for faster installation
    if ${UV_PREVIEW[@]} pip install --upgrade "agilab[offline]" 2>&1 | tee /tmp/offline-install.log; then
      echo "GPT-OSS offline assistant packages installed."
    else
      warn "Unable to install GPT-OSS automatically."
      warn "Install log saved to /tmp/offline-install.log"
      warn "Run 'uv pip install agilab[offline]' manually if needed."
      return
    fi

    # Verify critical packages (but don't reinstall if already present)
    local ensure_specs=("transformers>=4.57.0" "torch>=2.8.0" "accelerate>=0.34.2")
    for spec in "${ensure_specs[@]}"; do
      local pkg="${spec%%>=*}"
      if ! "${python_bin}" -c "import ${pkg}" >/dev/null 2>&1; then
        echo "[warn] Package ${pkg} not importable after installation"
        echo "[info] Try: uv pip install --upgrade '${spec}'"
      fi
    done
  else
    warn "Skipping GPT-OSS offline assistant (requires Python >=3.12; detected ${pyver})."
  fi
}

install_offline_assistant
popd >/dev/null

# Some uv operations materialize helper folders inside the venv root when
# installing from local sources. They are not required once the packages are
# installed, so prune them to keep the environment tidy.
for leftover in "${VENV}/agi_env" "${VENV}/agi-node" "${VENV}/agi-cluster" "${VENV}/agi-core"; do
  if [[ -d "${leftover}" ]]; then
    rm -rf "${leftover}"
  fi
done

# -----------------------------
# Show results
# -----------------------------
echo "===================================="
echo "Installed packages in agi-space/.venv:"
if ! "${VENV}/bin/python" -m pip list | grep -E '^(agilab|agi-)' ; then
  echo "(No agi* packages detected.)"
fi
echo "===================================="
echo ""
echo "Installation complete!"
echo ""
echo "Performance tips:"
echo "  - Use existing venv for faster installs (automatic now)"
echo "  - Use --skip-offline to skip heavy ML packages (saves 5-10 min)"
echo "  - Lock file is cached at repo root for faster rebuilds"
echo "  - Use --force-rebuild only when needed (cleans everything)"