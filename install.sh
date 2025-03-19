#!/bin/bash

# Script: install_AGI_all.sh
# Purpose: Install both fwk and apps
# Exit immediately if a command exits with a non-zero status and handle pipe failures
set -e
set -o pipefail

PYTHON_VERSION="3.12"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to display messages with a timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

usage() {
  echo "Usage: $0 --openai-api-key <api-key> [--install-path <path>] [--cluster-credentials <user:password>]"
  exit 1
}

check_script() {
    local script_path="$1"
    local script_name="$2"

    if [[ ! -f "$script_path" ]]; then
        log "${RED}Error: $script_name installation script '$script_path' not found!${NC}"
        exit 1
    fi

    # Make the script executable if it's not already
    if [[ ! -x "$script_path" ]]; then
        log "Setting execute permissions for '$script_path'..."
        chmod +x "$script_path"
    fi
}

execute_installation() {
    local project_dir="$1"
    local install_script="$2"
    local project_name="$3"

    log "Starting installation of $project_name..."
    pushd "$project_dir" > /dev/null
    source "$(basename "$install_script")"
    popd > /dev/null
    log "Installation of $project_name completed."
}

choose_python() {
    echo -e "${BLUE}Choosing Python version...${NC}"
    available_python_versions=$(uv python list)

    python_array=()
    while IFS= read -r line; do
        python_array+=("$line")
    done <<< "$available_python_versions"

    echo -e "${YELLOW}Recommended versions are highlighted in ${GREEN}green${YELLOW}.${NC}"
    for idx in "${!python_array[@]}"; do
        if [[ "${python_array[$idx]}" == *"$PYTHON_VERSION"* ]]; then
            echo -e "${GREEN}$((idx + 1)) - ${python_array[$idx]}${NC}"
        else
            echo -e "$((idx + 1)) - ${python_array[$idx]}"
        fi
    done

    while true; do
        read -rp "Select Python version: " selection
        if [[ $selection =~ ^[0-9]+$ ]] && (( selection >= 1 && selection <= ${#python_array[@]} )); then
            chosen_python=$(echo "${python_array[$((selection - 1))]}" | cut -d' ' -f1)
            break
        else
            echo "Invalid selection. Try again."
        fi
    done

    installed_pythons=$(uv python list --only-installed | cut -d' ' -f1)
    if echo "$installed_pythons" | grep -q "$chosen_python"; then
        echo -e "${GREEN}Python ($chosen_python) is installed.${NC}"
    else
        echo -e "${YELLOW}Installing $chosen_python...${NC}"
        uv python install "$chosen_python"
        echo -e "${GREEN}Python installed.${NC}"
    fi

    python_version=$(echo "$chosen_python" | cut -d '-' -f2)
    export PYTHON_VERSION=$python_version
}

start_installation() {
    # Ensure the installation path is set (default: current directory `.`)
    AGI_ROOT=$(realpath "${AGI_ROOT:-.}")
    AGI_PATH_FILE="$HOME/.local/share/agilab/.agi-path"

    log "Installing to: $AGI_ROOT (Stored in: $AGI_PATH_FILE)"

    # Store the chosen installation path
    mkdir -p "$(dirname "$AGI_PATH_FILE")"
    echo "$AGI_ROOT" > "$AGI_PATH_FILE"

    AGI_PROJECT="$AGI_ROOT/src"
    framework_dir="$AGI_PROJECT/fwk"
    apps_dir="$AGI_PROJECT/apps"
    framework_script="$framework_dir/install.sh"
    apps_script="$apps_dir/install.sh"

    check_script "$framework_script" "Framework"
    check_script "$apps_script" "Apps"

    log "Installing AGI project..."
    choose_python

    rm -fr "$HOME/wenv"
    AGI_env_file="$HOME/.agilab/.env"
    echo execute_installation "$framework_dir" "$framework_script" "Framework"
    execute_installation "$framework_dir" "$framework_script" "Framework"

    grep -qxF "OPENAI_API_KEY=\"$openai_api_key\"" "$AGI_env_file" || echo "OPENAI_API_KEY=\"$openai_api_key\"" >> "$AGI_env_file"
    grep -qxF "AGI_CREDENTIALS=\"$cluster_username\"" "$AGI_env_file" || echo "AGI_CREDENTIALS=\"$cluster_username\"" >> "$AGI_env_file"
    grep -qxF "AGI_PYTHON_VERSION=\"$python_version\"" "$AGI_env_file" || echo "AGI_PYTHON_VERSION=\"$python_version\"" >> "$AGI_env_file"

    execute_installation "$apps_dir" "$apps_script" "Apps"
    log "Installation complete!"
}

# Default values
AGI_ROOT="."
openai_api_key=""
cluster_username=""

# Parse CLI arguments
while [[ "$#" -gt 0 ]]; do
  case $1 in
    --install-path)
      AGI_ROOT="$2"
      shift 2
      ;;
    --openai-api-key)
      openai_api_key="$2"
      shift 2
      ;;
    --cluster-credentials)
      cluster_username="$2"
      shift 2
      ;;
    *)
        echo -e "${RED}Unknown option: $1${NC}"
        usage
        ;;
  esac
done

# Ensure required arguments are set
if [[ -z "$openai_api_key" ]]; then
    echo -e "${RED}Error: Missing mandatory parameter: --openai-api-key${NC}"
    usage
fi

start_installation