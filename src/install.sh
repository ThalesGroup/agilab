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

# Function to check the existence of an installation script
check_script() {
    local script_path="$1"
    local script_name="$2"

    if [[ ! -f "$script_path" ]]; then
        log "Error: $script_name installation script '$script_path' not found!"
        exit 1
    fi

    # Make the script executable if it's not already
    if [[ ! -x "$script_path" ]]; then
        log "Setting execute permissions for '$script_path'..."
        chmod +x "$script_path"
    fi
}

# Function to execute an installation script within its directory
execute_installation() {
    local project_dir="$1"
    local install_script="$2"
    local project_name="$3"

    log "Starting installation of $project_name..."

    pushd "$project_dir"
    source "$(basename "$install_script")"
    popd

    log "Installation of $project_name completed."
}

# Function to display usage information
usage() {
  echo "Usage: $0 [--cluster-credential <user:password>] --openai-api-key <openai-api-key >"
  exit 1
}

choose_python() {
    echo -e "${BLUE}Choosing Python version...${NC}"
    echo

    local available_python_versions
    available_python_versions=$(uv python list)
    python_array=()
    while IFS= read -r line; do
        python_array+=("$line")
    done <<< "$available_python_versions"


    echo -e "${YELLOW}The Python versions highlighted in ${GREEN}green${YELLOW} are the recommended ones.${NC}"
    for idx in "${!python_array[@]}"; do
        if [[ "${python_array[$idx]}" == *"$PYTHON_VERSION"* ]]; then
            echo -e "${GREEN}$((idx + 1)) - ${python_array[$idx]}${NC}"
        else
            echo -e "$((idx + 1)) - ${python_array[$idx]}"
        fi
    done

    # Ask for user input to choose a Python version
    while true; do
        read -rp "Enter the number of the Python version you want to use: " selection
        if [[ $selection =~ ^[0-9]+$ ]] && (( selection >= 1 && selection <= ${#python_array[@]} )); then
            chosen_python=$(echo "${python_array[$((selection - 1))]}" | cut -d' ' -f1)
            break
        else
            echo "Invalid selection. Please try again."
        fi
    done

    local installed_pythons
    installed_pythons=$(uv python list --only-installed | cut -d' ' -f1)
    # Check if the chosen Python version is installed
    if echo "$installed_pythons" | grep -q "$chosen_python"; then
        echo
        echo -e "${GREEN}Python version ($chosen_python) is installed.${NC}"
        echo
    else
        echo -e "${YELLOW}Installing $chosen_python in ~/.local/share/uv/python${NC}"
        echo
        uv python install "$chosen_python"
        echo -e "${GREEN}Python version ($chosen_python) is now installed.${NC}"
        echo
    fi

    # Extract version and pin it
    python_version=$(echo "$chosen_python" | cut -d '-' -f2)
    export PYTHON_VERSION=$python_version
}

start_installation() {
    AGI_ROOT=$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")
    AGI_PATH_FILE="$HOME/.local/share/agilab/.agi-path"

    echo "Executing: agi/$0 from $AGI_ROOT to install in $AGI_PATH_FILE"

    if [ -f "$AGI_PATH_FILE" ]; then
        content=$(cat "$AGI_PATH_FILE")
        if [ "$content" != "$AGI_ROOT" ]; then
            echo "The installation path has changed since the last installation."
            echo "Do you want to keep the new path \"$AGI_ROOT\" or keep the previous one \"$content\"?"
            echo "[N]ew path / [O]ld path (default: new):"

            read -r choice
            case "$choice" in
                [Oo]*)
                    log "Keeping the previous path: $content"
                    AGI_ROOT="$content"
                    ;;
                *)
                    log "Using the new path: $AGI_ROOT"
                    mkdir -p "$(dirname "$AGI_PATH_FILE")"
                    echo "$AGI_ROOT" > "$AGI_PATH_FILE"
                    ;;
            esac
        else
          log "Installation path: \"$AGI_ROOT\"."
        fi
    else
        mkdir -p "$(dirname "$AGI_PATH_FILE")"
        echo "$AGI_ROOT" > "$AGI_PATH_FILE"
    fi

    AGI_PROJECT="$AGI_ROOT/agi"

    # Define the directories and installation scripts using absolute paths
    framework_dir="$AGI_PROJECT/fwk"
    apps_dir="$AGI_PROJECT/apps"
    framework_script="$framework_dir/install.sh"
    apps_script="$apps_dir/install.sh"

    # Check if the fwk installation script exists
    check_script "$framework_script" "Framework"

    # Check if the apps installation script exists
    check_script "$apps_script" "Apps"


    log "Starting installation of AGI_project..."

    choose_python

    # Execute the installation scripts
    rm -fr "$HOME/wenv"
        # Define the path for the Agi environment file
    AGI_env_file="$HOME/.agilab/.env"



    execute_installation "$framework_dir" "$framework_script" "framework"

    # Append OpenAI API Key to the Agi environment file
    grep -qxF "OPENAI_API_KEY=\"$openai_api_key\"" "$AGI_env_file" || echo "OPENAI_API_KEY=\"$openai_api_key\"" >> "$AGI_env_file"
    grep -qxF "AGI_CREDENTIALS=\"$cluster_username\"" "$AGI_env_file" || echo "AGI_CREDENTIALS=\"$cluster_username\"" >> "$AGI_env_file"
    grep -qxF "AGI_PYTHON_VERSION=\"$python_version\"" "$AGI_env_file" || echo "AGI_PYTHON_VERSION=\"$python_version\"" >> "$AGI_env_file"

    execute_installation "$apps_dir" "$apps_script" "apps"


    # Final Message
    log "Installation of framework and apps complete!"

}

# Parse command line options
while [[ "$#" -gt 0 ]]; do
  case $1 in
    --cluster-credentials)
      cluster_username="$2"
      shift 2
      ;;
    --openai-api-key)
      openai_api_key="$2"
      shift 2
      ;;
    *)
        echo -e "${RED}Unknown option: $1${NC}"
        usage
        ;;
  esac
done

if [[ -z "${openai_api_key:-}" ]]; then
    echo -e "${RED}Error: Missing mandatory parameter: --openai-api-key${NC}"
    usage
fi

start_installation