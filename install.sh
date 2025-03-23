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
    AGI_INSTALL_PATH=$(realpath ".")
fi

echo -e "${GREEN}Installation path: $AGI_INSTALL_PATH${NC}"
echo -e "${GREEN}Cluster Credentials: $cluster_credentials${NC}"
echo -e "${GREEN}OpenAI API Key: $openai_api_key${NC}"

# Check internet connectivity
echo "Checking internet connectivity..."
if curl -s --head --fail https://www.google.com >/dev/null; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${RED}No internet connection detected. Aborting.${NC}"
    exit 1
fi


# Ask to install system dependencies
read -p "Install system dependencies? (y/N): " choice
if [[ "$choice" =~ ^[Yy]$ ]]; then
    if command -v apt >/dev/null 2>&1; then
        sudo apt update && sudo apt install -y build-essential curl wget unzip
        sudo snap install astral-uv --classic
        source $HOME/.local/bin/env
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
EXISTING_PROJECT=$(realpath "$(pwd)")
EXISTING_PROJECT_SRC="$EXISTING_PROJECT/src"


backup_agi_project() {
    echo -e "${BLUE}=================================================${NC}"
    echo -e "${BLUE}Step 6: Backing Up agi Project sources (If Any) ${NC}"
    echo -e "${BLUE}=================================================${NC}"
    echo

    # Define the source directory and installation path variables
    if [[ -d "$AGI_INSTALL_PATH" && -f "$EXISTING_PROJECT_SRC/zip-agi.py" ]]; then
        echo -e "${YELLOW}Existing agilab project found at $AGI_INSTALL_PATH and zip-agi.py exists.${NC}"
        backup_file="${AGI_INSTALL_PATH}_backup_$(date +%Y%m%d-%H%M%S).zip"
        echo -e "${YELLOW}Creating backup: $backup_file${NC}"
        echo

        if uv run --project "$AGI_INSTALL_PATH/fwk/core/managers" python "$AGI_INSTALL_PATH/zip-agi.py" --dir2zip "$AGI_INSTALL_PATH" --zipfile "$backup_file"; then
            echo -e "${GREEN}Backup created successfully at $backup_file.${NC}"
            echo -e "${YELLOW}Removing existing agilab project at '$AGI_INSTALL_PATH' ...${NC}"
            echo rm -ri "$AGI_INSTALL_PATH"
            echo -e "${GREEN}Existing agilab project directory removed.${NC}"
        else
            echo -e "${RED}ERROR: Backup failed at '$backup_file'.${NC}"
            echo -e "${YELLOW}Switching to fallback backup strategy...${NC}"
            # Fallback: create a zip archive of the installation directory
            if zip -r "$backup_file" "$AGI_INSTALL_PATH"; then
                echo -e "${YELLOW}Fallback backup created at '$backup_file'.${NC}"
                echo -e "${YELLOW}Removing existing agilab project at '$AGI_INSTALL_PATH' ...${NC}"
                echo rm -ri "$AGI_INSTALL_PATH"
                echo -e "${GREEN}Existing agilab project directory removed.${NC}"
            else
                echo -e "${RED}Failed to create backup using fallback strategy.${NC}"
                exit 1
            fi
        fi
    else
        echo -e "${YELLOW}No existing agilab project found or zip-agi.py does not exist. Skipping backup.${NC}"
    fi
    echo
}

# Copy new project files from the source directory to the install path if needed
if [[ "$AGI_INSTALL_PATH" != "$EXISTING_PROJECT" ]]; then
    if [[ -d "$EXISTING_PROJECT_SRC" ]]; then
        mkdir -p "$AGI_INSTALL_PATH"
        rsync -a "$EXISTING_PROJECT"/ "$AGI_INSTALL_PATH"/
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
framework_dir="$AGI_INSTALL_PATH/src/fwk"
apps_dir="$AGI_INSTALL_PATH/src/apps"

# Ensure install scripts are executable
chmod +x "$framework_dir/install.sh" "$apps_dir/install.sh"

echo "Installing Framework..."
pushd "$framework_dir" > /dev/null
echo ./install.sh "$apps_dir"
./install.sh "$framework_dir"
popd > /dev/null

echo "Installing Apps..."
pushd "$apps_dir" > /dev/null
echo ./install.sh "$apps_dir"
./install.sh "$apps_dir"
popd > /dev/null

echo -e "${GREEN}Installation complete!${NC}"
