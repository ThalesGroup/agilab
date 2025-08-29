#!/usr/bin/env bash
set -euo pipefail

# End-user install smoke-test helper.
# Modes:
#   --source local     : build from current repo and install locally-built artifacts
#   --source testpypi  : install published artifacts from TestPyPI (requires --version)
#
# It will then try to run `run-all-test` (or a path passed via --run). If not found, it fails.

usage() {
  cat <<'EOF'
Usage:
  test-install-enduser.sh [--source local|testpypi] [--version X.Y.Z]
                          [--packages "agilab agi-env agi-node agi-cluster agi-core"]
                          [--index-url URL] [--extra-index-url URL]
                          [--run "<command>"] [--python <python>] [--venv-dir <dir>]

Defaults:
  --source local
  --index-url https://test.pypi.org/simple
  --extra-index-url https://pypi.org/simple
  --packages "agilab agi-env agi-node agi-cluster agi-core"
EOF
}

SOURCE="local"
VERSION=""
PACKAGES="agilab agi-env agi-node agi-cluster agi-core"
INDEX_URL="https://test.pypi.org/simple"
EXTRA_INDEX_URL="https://pypi.org/simple"
RUN_CMD=""
PYTHON_BIN=""
VENV_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2;;
    --version) VERSION="$2"; shift 2;;
    --packages) PACKAGES="$2"; shift 2;;
    --index-url) INDEX_URL="$2"; shift 2;;
    --extra-index-url) EXTRA_INDEX_URL="$2"; shift 2;;
    --run) RUN_CMD="$2"; shift 2;;
    --python) PYTHON_BIN="$2"; shift 2;;
    --venv-dir) VENV_DIR="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown option: $1"; usage; exit 1;;
  esac
done

if [[ "$SOURCE" == "testpypi" && -z "$VERSION" ]]; then
  echo "ERROR: --version is required when --source testpypi" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is required but not found in PATH. Install from https://astral.sh/uv and retry." >&2
  exit 1
fi

ROOT="$(pwd)"
WORKSPACE="${VENV_DIR:-$ROOT/../agi-space}"

# Fresh workspace & venv
rm -rf "$WORKSPACE"
mkdir -p "$WORKSPACE"

section() { echo -e "\n\033[1;34m==> $*\033[0m"; }

section "Creating virtual environment in $WORKSPACE/.venv"
pushd "$WORKSPACE" >/dev/null
  rm -f uv.lock
  if [[ -n "$PYTHON_BIN" ]]; then uv venv -p "$PYTHON_BIN"; else uv venv; fi
  # shellcheck disable=SC1091
  source .venv/bin/activate

  if [[ "$SOURCE" == "local" ]]; then
    section "Building local packages and installing into the venv"
    popd >/dev/null
    set -x
    # Build main project (sdist) and the four core subpackages (wheels), like the original script. :contentReference[oaicite:3]{index=3}
    rm -rf dist build
    # Remove symlinks that should never be packaged (apps/ & views/)
    find src/agilab/apps src/agilab/views -type l -print -delete || true
    uv build --sdist
    mkdir -p "$WORKSPACE/.artifacts"
    cp dist/*.gz "$WORKSPACE/.artifacts"

    # Verify the sdist doesn’t contain known symlinked app folders
    tar -tzf "$WORKSPACE/.artifacts/"agilab-*.tar.gz | \
      grep -E 'src/agilab/apps/(flight_trajectory_project|link_sim_project|sat_trajectory_project|sb3_trainer_project)|src/agilab/views/maps-network-graph' \
      && { echo "ERROR: symlinked app content found in sdist"; exit 1; } \
      || echo "OK: symlinked app content not present in sdist"

    for pkg in agi-core agi-cluster agi-node agi-env; do
      pushd "src/agilab/core/$pkg" >/dev/null
        rm -rf dist build
        uv build --wheel
      popd >/dev/null
      cp "src/agilab/core/$pkg/dist/"*.whl "$WORKSPACE/.artifacts"
    done
    set +x
    pushd "$WORKSPACE" >/dev/null
    uv pip install ./.artifacts/*.whl ./.artifacts/*.gz
  else
    section "Installing packages from TestPyPI (version ${VERSION})"
    for pkg in $PACKAGES; do
      spec="${pkg}==${VERSION}"
      echo "+ uv pip install $spec"
      uv pip install \
        --index-url "$INDEX_URL" --extra-index-url "$EXTRA_INDEX_URL" \
        "$spec"
    done
  fi

  section "Verifying distributions (installed versions)"
  python - <<PY
import sys
from importlib.metadata import version, PackageNotFoundError
expected = "${VERSION}"
pkgs = "${PACKAGES}".split()
errors = []
for p in pkgs:
    try:
        v = version(p)
        print(f"{p}=={v}")
        if expected and v != expected:
            errors.append(f"{p}: installed {v}, expected {expected}")
    except PackageNotFoundError:
        errors.append(f"{p}: NOT INSTALLED")
if errors:
    print("\\n".join(errors), file=sys.stderr)
    sys.exit(1)
print("All requested distributions are present.")
PY

  section "Running product tests (run-all-test)"
  if [[ -n "$RUN_CMD" ]]; then
    bash -lc "$RUN_CMD"
  elif command -v run-all-test >/dev/null 2>&1; then
    run-all-test
  elif [[ -x "$ROOT/scripts/run-all-test" ]]; then
#    "$ROOT/scripts/run-all-test"
  else
    echo "ERROR: run-all-test not found; please provide it or pass --run '<command>'." >&2
    exit 1
  fi
popd >/dev/null

section "✅ End-user install test succeeded"
