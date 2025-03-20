#!/bin/bash
# Script: install_AGI_all.sh
# Purpose: Install both framework and apps
# Exit immediately if a command exits with a non-zero status and handle pipe failures
set -e
set -o pipefail

PYTHON_VERSION="3.12"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ================================
# Prevent Running as Root
# ================================
if [[ "$EUID" -eq 0 ]]; then
    echo -e "${RED}Error: This script should not be run as root. Please run as a regular user.${NC}"
    exit 1
fi

# ================================
# Logging Setup
# ================================
LOG_DIR="$HOME/log/install_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Installation started at $(date)${NC}"
echo -e "${BLUE}Log file: $LOG_FILE${NC}"
echo -e "${BLUE}Default/recommended Python version: $PYTHON_VERSION${NC}"
echo -e "${BLUE}========================================${NC}"
echo

# Global variables for project paths
agi_root=""
# AGI_INSTALL_PATH is optional; if not provided, we will default it to $(pwd)/agi.
AGI_INSTALL_PATH=""
AGI_PROJECT_SRC=""
framework_dir=""
apps_dir=""

usage() {
    echo -e "${YELLOW}Usage: $0 [--install-path <path>] --cluster-credentials <user:password> --openai-api-key <api-key>${NC}"
    exit 1
}

# ====================================================
# Command-line Options Parsing
# ====================================================
# Default values
cluster_credentials="agi"
openai_api_key=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --cluster-credentials)
            cluster_credentials="$2"
            shift 2
            ;;
        --openai-api-key)
            openai_api_key="$2"
            shift 2
            ;;
        --install-path)
            # Set the install path to AGI_INSTALL_PATH
            AGI_INSTALL_PATH=$(realpath "$2")
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

echo -e "${GREEN}Cluster Credentials: $cluster_credentials${NC}"
echo -e "${GREEN}OpenAI API Key: $openai_api_key${NC}"

# If no install path is provided, set a default
if [[ -z "$AGI_INSTALL_PATH" ]]; then
    AGI_INSTALL_PATH=$(realpath "$(pwd)/src")
    echo -e "${YELLOW}No AGI_INSTALL_PATH provided. Using default install path: $AGI_INSTALL_PATH${NC}"
else
    echo -e "${GREEN}Installation root (AGI_INSTALL_PATH): $AGI_INSTALL_PATH${NC}"
fi

# ---------------------------------------------------
# Utility functions
# ---------------------------------------------------
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

log_msg() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Check internet connectivity
check_internet() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Step 1: Checking Internet Connectivity${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
    if [[ $(curl -s --head --fail --request GET https://www.google.com | head -n 1 | cut -d' ' -f2) == "200" ]]; then
        log_msg "Internet connection is active."
    else
        echo -e "${RED}Error: No internet connection detected. Aborting installation.${NC}"
        exit 1
    fi
    echo
}

# Set locale to en_US.UTF-8 if not already set
set_locale() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Step 3: Setting Locale${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
    if ! locale -a | grep -q "en_US.utf8"; then
        echo -e "${YELLOW}Locale en_US.UTF-8 not found. Generating...${NC}"
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            locale-gen en_US.UTF-8 || { echo -e "${RED}Error: Failed to generate locale.${NC}"; exit 1; }
            echo -e "${GREEN}Locale en_US.UTF-8 generated successfully.${NC}"
        elif [[ "$OSTYPE" == "darwin"* ]]; then
            echo -e "${YELLOW}macOS typically includes en_US.UTF-8 by default. Skipping locale generation.${NC}"
        else
            echo -e "${RED}Unsupported operating system for locale generation.${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}Locale en_US.UTF-8 is already set.${NC}"
    fi
    export LC_ALL=en_US.UTF-8
    export LANG=en_US.UTF-8
    echo
}

# Install required system dependencies
install_dependencies() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Step 2: Installing System Dependencies${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
    read -p "Do you want to install system dependencies? (y/N): " choice
    if [[ "$choice" =~ ^[Yy]$ ]]; then
      if [[ "$OSTYPE" == "linux-gnu"* ]]; then
          echo -e "${GREEN}Detected Linux OS.${NC}"
          if command_exists apt; then
              echo -e "${GREEN}Using apt package manager.${NC}"
              sudo apt update
              sudo apt install -y software-properties-common build-essential libssl-dev \
                  zlib1g-dev libncurses-dev libbz2-dev libreadline-dev libsqlite3-dev \
                  libxml2-dev libxmlsec1-dev liblzma-dev wget curl llvm xz-utils tk-dev \
                  unzip p7zip-full libffi-dev libgdbm-dev libnss3-dev libgdbm-compat-dev \
                  graphviz pandoc inkscape tree
          elif command_exists dnf; then
              echo -e "${GREEN}Using dnf package manager.${NC}"
              sudo dnf groupinstall -y "Development Tools"
              sudo dnf install -y openssl-devel zlib-devel ncurses-devel bzip2-devel \
                  readline-devel sqlite-devel libxml2-devel libxmlsec1-devel xz-devel \
                  graphviz pandoc inkscape tree wget curl llvm xz tk-devel unzip p7zip \
                  libffi-devel gdbm-devel nss-devel
          elif command_exists yum; then
              echo -e "${GREEN}Using yum package manager.${NC}"
              sudo yum groupinstall -y "Development Tools"
              sudo yum install -y openssl-devel zlib-devel ncurses-devel bzip2-devel \
                  readline-devel sqlite-devel libxml2-devel libxmlsec1-devel xz-devel \
                  graphviz pandoc inkscape tree wget curl llvm xz tk-devel unzip p7zip-full \
                  libffi-dev libgdbm-dev nss-devel
          else
              echo -e "${RED}Unsupported Linux distribution. Please install dependencies manually.${NC}"
              exit 1
          fi
      elif [[ "$OSTYPE" == "darwin"* ]]; then
          echo -e "${GREEN}Detected macOS.${NC}"
          if ! command_exists brew; then
              echo -e "${YELLOW}Homebrew not found. Installing Homebrew...${NC}"
              /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
              eval "$(/opt/homebrew/bin/brew shellenv)"
              echo -e "${GREEN}Homebrew installed successfully.${NC}"
          else
              echo -e "${GREEN}Homebrew is already installed.${NC}"
          fi
          brew update
          brew upgrade
          brew cleanup
          brew install tree inkscape openssl readline sqlite libxml2 libxmlsec1 xz wget llvm p7zip
      else
          echo -e "${RED}Unsupported operating system: $OSTYPE${NC}"
          exit 1
      fi
      echo -e "${GREEN}System dependencies installed successfully.${NC}"
    fi
    if ! command_exists uv; then
      echo -e "${GREEN}Installing uv...${NC}"
      curl -LsSf https://astral.sh/uv/install.sh | sh
      echo -e "${GREEN}Uv installed successfully.${NC}"
    fi
    echo
}

# Determine the AGI project directories based on AGI_INSTALL_PATH
get_script_dirs() {
    # Use AGI_INSTALL_PATH as the project directory.
    if [[ -n "$AGI_INSTALL_PATH" ]]; then
        AGI_PROJECT_SRC="$AGI_INSTALL_PATH"
        framework_dir="$AGI_PROJECT_SRC/fwk"
        apps_dir="$AGI_PROJECT_SRC/apps"
        echo -e "${GREEN}AGI Project Directory: $AGI_PROJECT_SRC${NC}"
        echo -e "${GREEN}Framework Directory: $framework_dir${NC}"
        echo -e "${GREEN}Apps Directory: $apps_dir${NC}"
    else
        echo -e "${YELLOW}AGI_INSTALL_PATH is not set. Skipping project directory derivation.${NC}"
    fi
}

# Write installation root to a file for future reference
write_install_path() {
    mkdir -p "$HOME/.local/share/agilab"
    echo "$AGI_INSTALL_PATH" > "$HOME/.local/share/agilab/.agi-path"
    echo -e "${GREEN}Installation root has been exported as AGIROOT.${NC}"
    echo
}

# Backup an existing AGI project (if found) and remove it
backup_agi_project() {
    # Only run this step if AGI_INSTALL_PATH is set
    if [[ -z "$AGI_INSTALL_PATH" ]]; then
        echo -e "${YELLOW}AGI_INSTALL_PATH is not set. Skipping backup.${NC}"
        return
    fi

    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Step 6: Backing Up Existing AGI Project (if any)${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
    if [[ -d "$AGI_PROJECT_SRC" ]]; then
        if [[ -f "$AGI_PROJECT_SRC/zip-agi.py" ]]; then
            echo -e "${YELLOW}Existing AGI project found at $AGI_PROJECT_SRC and zip-agi.py exists.${NC}"
            backup_file="agilib-$(basename "$AGI_PROJECT_SRC")-$(date +%Y%m%d-%H%M%S).zip"

            echo -e "${YELLOW}Creating backup: $backup_file${NC}"
            if uv run --project "$AGI_PROJECT_SRC/fwk/core/managers" python "$AGI_PROJECT_SRC/zip-agi.py" --no-top --dir2zip "$AGI_PROJECT_SRC" --zipfile "$backup_file"; then
                echo -e "${GREEN}Backup created successfully at $backup_file.${NC}"
                # Only remove the project directory if it is not named "src"
                if [[ "$(basename "$AGI_PROJECT_SRC")" != "src" ]]; then
                    echo -e "${YELLOW}Removing existing AGI project directory...${NC}"
                    rm -rf "$AGI_PROJECT_SRC"
                    echo -e "${GREEN}Existing AGI project directory removed.${NC}"
                else
                    echo -e "${YELLOW}AGI project directory is 'src'; not removing it.${NC}"
                fi
            else
                echo -e "${RED}ERROR: Backup failed at '$backup_file'.${NC}"
                echo -e "${YELLOW}Switching to backup fallback strategy...${NC}"
                if mv -f "$AGI_PROJECT_SRC" "$backup_file"; then
                    echo -e "${YELLOW}Moved '$AGI_PROJECT_SRC' to '$backup_file'.${NC}"
                else
                    echo -e "${RED}Failed to move '$AGI_PROJECT_SRC' to '$backup_file'.${NC}"
                    exit 1
                fi
            fi
        else
            echo -e "${YELLOW}Existing AGI project found at $AGI_PROJECT_SRC but no zip-agi.py found. Skipping backup.${NC}"
        fi
    else
        echo -e "${YELLOW}No existing AGI project found at $AGI_PROJECT_SRC. Skipping backup.${NC}"
    fi
    echo
}

# Copy the AGI project files from the local 'agi' directory to the install path
copy_agi_project() {
    # Only run this step if AGI_INSTALL_PATH is set
    if [[ -z "$AGI_INSTALL_PATH" ]]; then
        echo -e "${YELLOW}AGI_INSTALL_PATH is not set. Skipping project copy step.${NC}"
        return
    fi

    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Step 7: Copying AGI Project Files${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
    if [[ -d "src" ]]; then
        echo -e "${YELLOW}Copying AGI project source from ./src to $AGI_INSTALL_PATH...${NC}"
        mkdir -p "$AGI_INSTALL_PATH"
        rsync -a --delete src/ "$AGI_INSTALL_PATH/" || {
            echo -e "${RED}Error: Failed to copy AGI project files to $AGI_INSTALL_PATH.${NC}"
            exit 1
        }
        echo -e "${GREEN}AGI project files copied successfully to $AGI_INSTALL_PATH.${NC}"
    else
        echo -e "${RED}AGI project source (src directory) not found in the current directory. Exiting.${NC}"
        exit 1
    fi
    echo
}

# ---------------------------------------------------
# Functions for framework & apps installation
# ---------------------------------------------------

# Check if an installation script exists and set executable permissions
check_script() {
    local script_path="$1"
    local script_name="$2"
    if [[ ! -f "$script_path" ]]; then
        log_msg "${RED}Error: $script_name installation script '$script_path' not found!${NC}"
        exit 1
    fi
    if [[ ! -x "$script_path" ]]; then
        log_msg "Setting execute permissions for '$script_path'..."
        chmod +x "$script_path"
    fi
}

# Interactive Python version selection using uv
choose_python() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Step 8: Choosing Python Version...${NC}"
    echo -e "${BLUE}========================================${NC}"
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

    python_version=$(echo "$chosen_python" | cut -d'-' -f2)
    export PYTHON_VERSION=$python_version
    echo -e "${GREEN}Using Python version: $PYTHON_VERSION${NC}"
    echo
}

# Update the environment file with credentials and Python version
update_env_file() {
    local AGI_env_file="$HOME/.local/share/agilab/.env"
    mkdir -p "$(dirname "$AGI_env_file")"
    grep -qxF "OPENAI_API_KEY=\"$openai_api_key\"" "$AGI_env_file" || echo "OPENAI_API_KEY=\"$openai_api_key\"" >> "$AGI_env_file"
    grep -qxF "AGI_CREDENTIALS=\"$cluster_credentials\"" "$AGI_env_file" || echo "AGI_CREDENTIALS=\"$cluster_credentials\"" >> "$AGI_env_file"
    grep -qxF "AGI_PYTHON_VERSION=\"$PYTHON_VERSION\"" "$AGI_env_file" || echo "AGI_PYTHON_VERSION=\"$PYTHON_VERSION\"" >> "$AGI_env_file"
    echo -e "${GREEN}Environment variables updated in $AGI_env_file.${NC}"
    echo
}

# Main unified installation function for framework and apps
start_installation() {
    # Write installation root and derive project directories (if AGI_INSTALL_PATH is set)
    write_install_path
    get_script_dirs

    # Check required installation scripts for Framework and Apps
    framework_script="$framework_dir/install.sh"
    apps_script="$apps_dir/install.sh"
    check_script "$framework_script" "Framework"
    check_script "$apps_script" "Apps"

    choose_python

    log_msg "========================================"
    log_msg "Step 9: Installing Framework"
    log_msg "========================================"
    # Clean up previous virtual environments if any
    rm -fr "$HOME/wenv"
    # Update environment file (for reference, stored in ~/.local/share/agi_env)
    local ENV_FILE="$HOME/.local/share/agi_env/.env"
    # Inline installation of Framework:
    log_msg "Starting installation of Framework..."
    pushd "$framework_dir" > /dev/null
    source "$(basename "$framework_script")"
    popd > /dev/null
    log_msg "Installation of Framework completed."

    grep -qxF "OPENAI_API_KEY=\"$openai_api_key\"" "$ENV_FILE" || echo "OPENAI_API_KEY=\"$openai_api_key\"" >> "$ENV_FILE"
    grep -qxF "AGI_CREDENTIALS=\"$cluster_credentials\"" "$ENV_FILE" || echo "AGI_CREDENTIALS=\"$cluster_credentials\"" >> "$ENV_FILE"
    grep -qxF "AGI_PYTHON_VERSION=\"$python_version\"" "$ENV_FILE" || echo "AGI_PYTHON_VERSION=\"$python_version\"" >> "$ENV_FILE"

    log_msg "========================================"
    log_msg "Step 10: Installing Apps"
    log_msg "========================================"
    log_msg "Starting installation of Apps..."
    pushd "$apps_dir" > /dev/null
    source "$(basename "$apps_script")"
    popd > /dev/null
    log_msg "Installation of Apps completed."

    log_msg "========================================"
    log_msg "Installation of both Framework and Apps complete!"
    log_msg "========================================"
}

# ---------------------------------------------------
# Main Flow
# ---------------------------------------------------
main() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Unified AGI Project Installation Script${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo

    check_internet
    install_dependencies
    set_locale

    # If AGI_INSTALL_PATH is set, run get_script_dirs first, then backup and copy
    if [[ -n "$AGI_INSTALL_PATH" ]]; then
        get_script_dirs
        backup_agi_project
        copy_agi_project
    else
        echo -e "${YELLOW}AGI_INSTALL_PATH not set. Skipping backup and copy steps.${NC}"
    fi

    # Start installation of framework and apps
    start_installation

    # Generate documentation using uv (assumes docs/gen-docs.py is configured)
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}Step Z: Generating Documentation${NC}"
    echo -e "${BLUE}========================================${NC}"
    [ -f "uv.lock" ] && rm "uv.lock"
    [ -d ".venv" ] && rm -r ".venv"
    uv sync -p "${PYTHON_VERSION}" --group sphinx
    uv run docs/gen-docs.py

    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Installation Completed Successfully!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo

    echo -e "${GREEN}Starting AGILAB from $AGI_INSTALL_PATH${NC}"
    "$AGI_INSTALL_PATH/agilab.sh" --openai-api-key "$openai_api_key" || {
        echo -e "${RED}Error: Failed to start AGILAB.${NC}"
        exit 1
    }
    echo -e "${GREEN}AGILAB started successfully.${NC}"
}

main