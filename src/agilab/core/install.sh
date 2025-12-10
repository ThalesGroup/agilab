#!/bin/bash

# Script: install_Agi_framework.sh
# Purpose: Install the framework

# Exit immediately if a command fails
set -e
set -o pipefail

UV_PREVIEW=(uv --preview-features extra-build-dependencies)

#source "$HOME/.local/bin/env"
source "$HOME/.local/share/agilab/.env"
AGI_PYTHON_VERSION=$(echo "$AGI_PYTHON_VERSION" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*/\1/')
export AGI_PYTHON_VERSION

BLUE='\033[1;34m'
GREEN='\033[1;32m'
RED='\033[1;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

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
pushd agi-env > /dev/null
echo "${UV_PREVIEW[*]} sync -p $AGI_PYTHON_VERSION --dev"
${UV_PREVIEW[@]} sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
${UV_PREVIEW[@]} pip install -e .
popd > /dev/null

echo -e "${BLUE}Installing agi-node...${NC}"
pushd agi-node > /dev/null
echo "${UV_PREVIEW[*]} sync -p $AGI_PYTHON_VERSION --dev"
${UV_PREVIEW[@]} sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
${UV_PREVIEW[@]} pip install -e .
${UV_PREVIEW[@]} pip install -e ../agi-env
popd > /dev/null

echo -e "${BLUE}Installing agi-cluster...${NC}"
pushd agi-cluster > /dev/null
echo "${UV_PREVIEW[*]} sync -p $AGI_PYTHON_VERSION --dev"
${UV_PREVIEW[@]} sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
${UV_PREVIEW[@]} pip install -e .
${UV_PREVIEW[@]} pip install -e ../agi-node
${UV_PREVIEW[@]} pip install -e ../agi-env
popd > /dev/null

echo -e "${BLUE}Preparing repository root for test runs...${NC}"
pushd ../../.. > /dev/null

popd > /dev/null
echo ""
echo -e "${GREEN}Framework installation completed!${NC}"
