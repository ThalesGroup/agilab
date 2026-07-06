#!/bin/bash

# Script: install_Agi_framework.sh
# Purpose: Install the framework

# Exit immediately if a command fails
set -e
set -o pipefail

UV_PREVIEW=(uv --preview-features extra-build-dependencies)
CORE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python_uv_spec_for_version() {
    local version="${1:-}"
    case "$version" in
        3.14|3.14.*)
            if [[ "$version" == *+* ]]; then
                printf '%s\n' "$version"
            else
                printf '%s+gil\n' "$version"
            fi
            ;;
        *)
            printf '%s\n' "$version"
            ;;
    esac
}

#source "$HOME/.local/bin/env"
source "$HOME/.local/share/agilab/.env"
normalize_agi_python_version() {
    local raw="${1:-3.14}"
    raw="$(printf '%s' "$raw" | sed -E 's/^[[:space:]]+//;s/[[:space:]]+$//')"
    [[ -n "$raw" ]] || raw="3.14"

    if [[ "$raw" == *freethreaded* \
       || "$raw" =~ (^|[^[:alnum:]])python3\.[0-9]+t([^[:alnum:]]|$) \
       || "$raw" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?t($|[^[:alnum:]]) ]]; then
        echo "Unsupported AGI_PYTHON_VERSION '${raw}': AGILAB core installs require a standard GIL Python interpreter." >&2
        return 1
    fi

    if [[ "$raw" =~ ^([0-9]+\.[0-9]+(\.[0-9]+)?)([^0-9].*)?$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    elif [[ "$raw" =~ cpython-([0-9]+\.[0-9]+(\.[0-9]+)?)([^0-9].*)?$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    elif [[ "$raw" =~ python([0-9]+\.[0-9]+(\.[0-9]+)?)([^0-9].*)?$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    else
        echo "Invalid AGI_PYTHON_VERSION '${raw}'. Expected versions like 3.14, 3.14.6, or 3.13.14." >&2
        return 1
    fi
}

if ! AGI_PYTHON_VERSION="$(normalize_agi_python_version "$AGI_PYTHON_VERSION")"; then
    exit 1
fi
AGI_PYTHON_FREE_THREADED=0
AGI_PYTHON_UV_SPEC="${AGI_PYTHON_UV_SPEC:-$(python_uv_spec_for_version "$AGI_PYTHON_VERSION")}"
export AGI_PYTHON_VERSION
export AGI_PYTHON_FREE_THREADED
export AGI_PYTHON_UV_SPEC

BLUE='\033[1;34m'
GREEN='\033[1;32m'
RED='\033[1;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

configure_uv_link_mode() {
    local requested="${AGILAB_UV_LINK_MODE:-${UV_LINK_MODE:-hardlink}}"
    case "$requested" in
        clone|copy|hardlink|symlink) ;;
        *)
            echo -e "${RED}Invalid uv link mode '${requested}'. Expected one of: clone, copy, hardlink, symlink.${NC}"
            exit 1
            ;;
    esac
    export UV_LINK_MODE="$requested"
    echo -e "${BLUE}uv link mode: ${UV_LINK_MODE}${NC}"
}

configure_uv_link_mode

LINK_COMPATIBLE_VENVS="${AGILAB_LINK_COMPATIBLE_VENVS:-1}"
VENV_LINK_REPORT="${AGILAB_VENV_LINK_REPORT:-$HOME/.local/share/agilab/core_venv_link_report.json}"

link_compatible_core_venvs() {
    case "$LINK_COMPATIBLE_VENVS" in
        0|false|False|FALSE|no|No|NO)
            echo -e "${BLUE}Compatible core venv linking disabled.${NC}"
            return 0
            ;;
    esac

    local linker="$CORE_DIR/../venv_linker.py"
    if [[ ! -f "$linker" ]]; then
        echo -e "${YELLOW}Warning:${NC} compatible venv linker not found at $linker; keeping isolated core venvs."
        return 0
    fi

    mkdir -p -- "$(dirname "$VENV_LINK_REPORT")"
    echo -e "${BLUE}Linking compatible core virtual environments...${NC}"
    if "${UV_PREVIEW[@]}" run -p "${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION}" --no-project --with packaging python "$linker" \
        --apply \
        --report "$VENV_LINK_REPORT" \
        --root "$CORE_DIR"; then
        echo -e "${GREEN}Compatible core venv link report:${NC} $VENV_LINK_REPORT"
    else
        echo -e "${YELLOW}Warning:${NC} compatible core venv linking failed; keeping installed core venvs."
    fi
}

echo -e "${BLUE}Installing framework from $(pwd)...${NC}"
echo -e "${BLUE}Python Version: $AGI_PYTHON_VERSION${NC}"

# Array to track failed test suites
declare -a FAILED_TEST_SUITES=()

# Function to run pytest and track failures
run_pytest_tracked() {
    local test_name="$1"
    shift
    local pytest_cmd=("$@")

    echo -e "${BLUE}Running ${test_name}...${NC}"

    # Run pytest and capture exit code
    set +e
    "${pytest_cmd[@]}"
    local exit_code=$?
    set -e

    # Track failures
    if [ $exit_code -ne 0 ]; then
        FAILED_TEST_SUITES+=("${test_name} (exit code: ${exit_code})")
        echo -e "${RED}✗ ${test_name} FAILED (exit code: ${exit_code})${NC}"
        return 1
    else
        echo -e "${GREEN}✓ ${test_name} PASSED${NC}"
        return 0
    fi
}

ensure_pip_if_missing() {
    if ${UV_PREVIEW[@]} run -p "${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION}" python -c "import pip" >/dev/null 2>&1; then
        echo -e "${GREEN}pip already available.${NC}"
        return
    fi
    echo -e "${YELLOW}pip missing; bootstrapping with ensurepip...${NC}"
    ${UV_PREVIEW[@]} run -p "${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION}" python -m ensurepip
}

remove_incompatible_project_venv() {
    local project_dir="$1"
    local label="${2:-$1}"
    local venv_dir="$project_dir/.venv"
    local venv_python="$venv_dir/bin/python"
    [[ -x "$venv_python" ]] || return 0

    local status
    status="$("$venv_python" - "$AGI_PYTHON_VERSION" <<'PY' 2>/dev/null || true
import sys

expected = sys.argv[1]
expected_parts = expected.split(".")
current_parts = [str(sys.version_info.major), str(sys.version_info.minor), str(sys.version_info.micro)]
abi_flags = getattr(sys, "abiflags", "")
gil_enabled = getattr(sys, "_is_gil_enabled", lambda: True)()
if "t" in abi_flags or gil_enabled is False:
    print("freethreaded")
elif current_parts[: len(expected_parts)] != expected_parts:
    print("version")
else:
    print("ok")
PY
)"
    [[ "$status" == "ok" ]] && return 0

    echo -e "${YELLOW}Removing incompatible virtual environment for ${label}: ${venv_dir} (${status:-unreadable}; expected Python ${AGI_PYTHON_VERSION}).${NC}"
    rm -rf -- "$venv_dir"
}

# Function to prompt user about test failures
prompt_for_continuation() {
    if [ ${#FAILED_TEST_SUITES[@]} -eq 0 ]; then
        echo -e "${GREEN}All tests passed successfully!${NC}"
        return 0
    fi

    if [ ! -t 0 ]; then
        echo -e "${YELLOW}Test failures detected, non-interactive shell; continuing installation by default.${NC}"
        return 0
    fi

    echo ""
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}TEST FAILURES DETECTED${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}The following test suite(s) failed:${NC}"
    for failed_suite in "${FAILED_TEST_SUITES[@]}"; do
        echo -e "${RED}  ✗ ${failed_suite}${NC}"
    done
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    while true; do
        echo -e "${YELLOW}Do you want to continue installation despite these test errors? (y/n): ${NC}"
        read -r response
        case "$response" in
            [Yy]|[Yy][Ee][Ss])
                echo -e "${YELLOW}Continuing installation despite test failures...${NC}"
                return 0
                ;;
            [Nn]|[Nn][Oo])
                echo -e "${RED}Installation aborted by user due to test failures.${NC}"
                exit 1
                ;;
            *)
                echo -e "${RED}Invalid response. Please enter 'y' or 'n'.${NC}"
                ;;
        esac
    done
}

echo -e "${BLUE}Installing agi-env...${NC}"
pushd "$CORE_DIR/agi-env" > /dev/null
echo "${UV_PREVIEW[*]} sync -p ${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION} --dev"
remove_incompatible_project_venv "$PWD" "agi-env"
${UV_PREVIEW[@]} sync -p "${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION}" --dev
ensure_pip_if_missing
${UV_PREVIEW[@]} pip install --upgrade --no-deps -e .
popd > /dev/null

echo -e "${BLUE}Installing agi-node...${NC}"
pushd "$CORE_DIR/agi-node" > /dev/null
echo "${UV_PREVIEW[*]} sync -p ${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION} --dev"
remove_incompatible_project_venv "$PWD" "agi-node"
${UV_PREVIEW[@]} sync -p "${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION}" --dev
ensure_pip_if_missing
${UV_PREVIEW[@]} pip install --upgrade --no-deps -e . -e ../agi-env
popd > /dev/null

echo -e "${BLUE}Installing agi-cluster...${NC}"
pushd "$CORE_DIR/agi-cluster" > /dev/null
echo "${UV_PREVIEW[*]} sync -p ${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION} --dev"
remove_incompatible_project_venv "$PWD" "agi-cluster"
${UV_PREVIEW[@]} sync -p "${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION}" --dev
ensure_pip_if_missing
${UV_PREVIEW[@]} pip install --upgrade --no-deps -e . -e ../agi-node -e ../agi-env
popd > /dev/null

echo -e "${BLUE}Installing agi-core...${NC}"
pushd "$CORE_DIR/agi-core" > /dev/null
echo "${UV_PREVIEW[*]} sync -p ${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION} --dev"
remove_incompatible_project_venv "$PWD" "agi-core"
${UV_PREVIEW[@]} sync -p "${AGI_PYTHON_UV_SPEC:-$AGI_PYTHON_VERSION}" --dev
ensure_pip_if_missing
${UV_PREVIEW[@]} pip install --upgrade --no-deps -e ../agi-env -e ../agi-node -e ../agi-cluster -e .
popd > /dev/null

link_compatible_core_venvs

echo -e "${BLUE}Preparing repository root for test runs...${NC}"
pushd "$CORE_DIR/../../.." > /dev/null

popd > /dev/null
echo ""
echo -e "${GREEN}Framework installation completed!${NC}"
