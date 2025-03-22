#!/bin/bash
set -e
set -o pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# Default values
PYTHON_VERSION="3.12"
AGI_INSTALL_PATH=""
cluster_credentials="agi"
openai_api_key=""

# Logging setup
LOG_DIR="$HOME/log/install_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

# Prevent running as root
if [[ "$EUID" -eq 0 ]]; then
    echo -e "${RED}Do not run as root. Please run as a regular user.${NC}"
    exit 1
fi

usage() {
    echo "Usage: $0 [--install-path <path>] --cluster-credentials <user:password> --openai-api-key <api-key>"
    exit 1
}

# Parse command-line arguments
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
            AGI_INSTALL_PATH=$(realpath "$2")
            shift 2
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            ;;
    esac
done

if [[ -z "$openai_api_key" ]]; then
    echo -e "${RED}Missing mandatory parameter: --openai-api-key${NC}"
    usage
fi

# Default installation path if not provided
if [[ -z "$AGI_INSTALL_PATH" ]]; then
    AGI_INSTALL_PATH=$(realpath "$(pwd)/src")
fi

echo -e "${GREEN}Installation path: $AGI_INSTALL_PATH${NC}"
echo -e "${GREEN}Cluster Credentials: $cluster_credentials${NC}"
echo -e "${GREEN}OpenAI API Key: $openai_api_key${NC}"

# Check internet connectivity
echo "Checking internet connectivity..."
if ! curl -s --head --fail https://www.google.com; then
    echo -e "${RED}No internet connection detected. Aborting.${NC}"
    exit 1
fi

# Ask to install system dependencies
read -p "Install system dependencies? (y/N): " choice
if [[ "$choice" =~ ^[Yy]$ ]]; then
    if command -v apt >/dev/null 2>&1; then
        sudo apt update && sudo apt install -y build-essential curl wget unzip
    elif command -v brew >/dev/null 2>&1; then
        brew update && brew install curl wget unzip
    else
        echo -e "${RED}No supported package manager found. Please install dependencies manually.${NC}"
        exit 1
    fi
fi

# Set locale to en_US.UTF-8 if not present
if ! locale -a | grep -qi "en_US.utf8"; then
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo locale-gen en_US.UTF-8
    fi
fi
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

# Determine the absolute path of the source directory
SRC_DIR=$(realpath "$(pwd)/src")

# Backup existing project if present
if [[ -d "$AGI_INSTALL_PATH" ]]; then
    backup_file="${AGI_INSTALL_PATH}_backup_$(date +%Y%m%d_%H%M%S).zip"
    echo "Backing up existing project to $backup_file"
    zip -r "$backup_file" "../$AGI_INSTALL_PATH"
    # Only remove the install directory if it is not the source directory
    if [[ "$AGI_INSTALL_PATH" != "$SRC_DIR" ]]; then
        echo "Removing existing project directory interactively..."
        rm -ri "$AGI_INSTALL_PATH"
    else
        echo "Install path is the source directory; skipping removal."
    fi
fi

# Copy new project files from the source directory to the install path if needed
if [[ "$AGI_INSTALL_PATH" != "$SRC_DIR" ]]; then
    if [[ -d "$SRC_DIR" ]]; then
        mkdir -p "$AGI_INSTALL_PATH"
        rsync -a --delete "$SRC_DIR"/ "$AGI_INSTALL_PATH"/
    else
        echo -e "${RED}Source directory 'src' not found. Exiting.${NC}"
        exit 1
    fi
else
    echo "Using source directory as install directory; no copy needed."
fi

# Update environment file
ENV_FILE="$HOME/.local/share/agilab/.env"
mkdir -p "$(dirname "$ENV_FILE")"
{
    echo "OPENAI_API_KEY=\"$openai_api_key\""
    echo "AGI_CREDENTIALS=\"$cluster_credentials\""
    echo "AGI_PYTHON_VERSION=\"$PYTHON_VERSION\""
} >> "$ENV_FILE"
echo -e "${GREEN}Environment updated in $ENV_FILE${NC}"

# Install Framework and Apps
framework_dir="$AGI_INSTALL_PATH/fwk"
apps_dir="$AGI_INSTALL_PATH/apps"

# Ensure install scripts are executable
chmod +x "$framework_dir/install.sh" "$apps_dir/install.sh"

echo "Installing Framework..."
pushd "$framework_dir" > /dev/null
./install.sh "$framework_dir"
popd > /dev/null

echo "Installing Apps..."
pushd "$apps_dir" > /dev/null
./install.sh "$apps_dir"
popd > /dev/null

echo -e "${GREEN}Installation complete!${NC}"