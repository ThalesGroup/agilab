#!/bin/bash
set -e
set -o pipefail

# ================================
# Prevent Running as Root
# ================================
if [[ "$EUID" -eq 0 ]]; then
    echo -e "${RED}Error: This script should not be run as root. Please run as a regular user.${NC}"
    exit 1
fi

# ================================
# Set Locals
# ================================
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 3: Setting Locale${NC}"
echo -e "${BLUE}========================================${NC}"
echo

if ! locale -a | grep -q "en_US.utf8"; then
    echo -e "${YELLOW}Locale en_US.UTF-8 not found. Generating...${NC}"
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        locale-gen en_US.UTF-8 || {
            echo -e "${RED}Error: Failed to generate locale. Please generate it manually.${NC}"
            exit 1
        }
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
#!/bin/bash

# Define colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Ask to install system dependencies
read -p "Install system dependencies? (y/N): " choice
if [[ "$choice" =~ ^[Yy]$ ]]; then
    if command -v apt >/dev/null 2>&1; then
        echo -e "${BLUE}Detected apt package manager (Linux).${NC}"
        sudo apt update
        # Original packages plus extra ones from the missing functionality
        sudo apt install -y build-essential curl wget unzip \
            software-properties-common libssl-dev zlib1g-dev libncurses-dev \
            libbz2-dev libreadline-dev libsqlite3-dev libxml2-dev libxmlsec1-dev \
            liblzma-dev llvm xz-utils tk-dev p7zip-full libffi-dev libgdbm-dev \
            libnss3-dev libgdbm-compat-dev graphviz pandoc inkscape tree
        # Original code uv installation via snap and environment sourcing
        sudo snap install astral-uv --classic
        source "$HOME/.local/bin/env"
        # Additional check: if uv is still missing, install it via the official script
        if ! command_exists uv; then
            echo -e "${GREEN}Installing uv...${NC}"
            curl -LsSf https://astral.sh/uv/install.sh | sh
        fi

    elif command_exists dnf; then
        echo -e "${BLUE}Detected dnf package manager (Linux).${NC}"
        sudo dnf groupinstall -y "Development Tools"
        sudo dnf install -y wget curl unzip openssl-devel zlib-devel ncurses-devel \
            bzip2-devel readline-devel sqlite-devel libxml2-devel libxmlsec1-devel xz-devel \
            graphviz pandoc inkscape tree llvm xz tk-devel p7zip libffi-devel gdbm-devel nss-devel
        if ! command_exists uv; then
            echo -e "${GREEN}Installing uv...${NC}"
            curl -LsSf https://astral.sh/uv/install.sh | sh
        fi

    elif command_exists yum; then
        echo -e "${BLUE}Detected yum package manager (Linux).${NC}"
        sudo yum groupinstall -y "Development Tools"
        sudo yum install -y wget curl unzip openssl-devel zlib-devel ncurses-devel \
            bzip2-devel readline-devel sqlite-devel libxml2-devel libxmlsec1-devel xz-devel \
            graphviz pandoc inkscape tree llvm xz tk-devel p7zip-full libffi-dev libgdbm-dev nss-devel
        if ! command_exists uv; then
            echo -e "${GREEN}Installing uv...${NC}"
            curl -LsSf https://astral.sh/uv/install.sh | sh
        fi

    elif command_exists brew >/dev/null 2>&1; then
        echo -e "${BLUE}Detected Homebrew (macOS).${NC}"
        brew update && brew install curl wget unzip
        # Additional packages from missing functionality
        brew install tree inkscape openssl readline sqlite libxml2 libxmlsec1 xz llvm p7zip
        # Update, upgrade, and clean up Homebrew
        brew update && brew upgrade && brew cleanup
        if ! command_exists uv; then
            echo -e "${GREEN}Installing uv...${NC}"
            curl -LsSf https://astral.sh/uv/install.sh | sh
        fi

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

mkdir -p "$HOME/.local/share/agilab"
echo "$EXISTING_PROJECT_SRC" > "$HOME/.local/share/agilab/.agi-path"
echo -e "${GREEN}Installation root path has been exported as AGIROOT.${NC}"

echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}Backing Up Project sources (If Any) ${NC}"
echo -e "${BLUE}=================================================${NC}"
echo

# Define the source directory and installation path variables
if [[ -d "$AGI_INSTALL_PATH" && -f "$EXISTING_PROJECT/zip-agi.py" && "$AGI_INSTALL_PATH" != "$EXISTING_PROJECT" ]]; then
    echo -e "${YELLOW}Existing agilab project found at $AGI_INSTALL_PATH and zip-agi.py exists.${NC}"
    backup_file="${AGI_INSTALL_PATH}_backup_$(date +%Y%m%d-%H%M%S).zip"
    echo -e "${YELLOW}Creating backup: $backup_file${NC}"

    echo uv run --project "$AGI_INSTALL_PATH/fwk/core/managers" python "$AGI_INSTALL_PATH/zip-agi.py" --dir2zip "$AGI_INSTALL_PATH" --zipfile "$backup_file"

    if uv run --project "$AGI_INSTALL_PATH/fwk/core/managers" python "$AGI_INSTALL_PATH/zip-agi.py" --dir2zip "$AGI_INSTALL_PATH" --zipfile "$backup_file"; then
        echo -e "${GREEN}Backup created successfully at $backup_file.${NC}"
        echo -e "${YELLOW}Removing existing agilab project at '$AGI_INSTALL_PATH' ...${NC}"
        rm -ri "$AGI_INSTALL_PATH"
        echo -e "${GREEN}Existing agilab project directory removed.${NC}"
    else
        echo -e "${RED}ERROR: Backup failed at '$backup_file'.${NC}"
        echo -e "${YELLOW}Switching to fallback backup strategy...${NC}"
        # Fallback: create a zip archive of the installation directory
        if zip -r "$backup_file" "$AGI_INSTALL_PATH"; then
            echo -e "${YELLOW}Fallback backup created at '$backup_file'.${NC}"
            echo -e "${YELLOW}Removing existing agilab project at '$AGI_INSTALL_PATH' ...${NC}"
            rm -ri "$AGI_INSTALL_PATH"
            echo -e "${GREEN}Existing agilab project directory removed.${NC}"
        else
            echo -e "${RED}Failed to create backup using fallback strategy.${NC}"
            exit 1
        fi
    fi
else
    echo -e "${YELLOW}No valid agilab project found, zip-agi.py is missing, or install dir is the same as the existing one. Skipping backup.${NC}"
fi
echo


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


#
#unzip_agi_project() {
#    echo -e "${BLUE}========================================${NC}"
#    echo -e "${BLUE}Step 7: Unzipping agi.zip${NC}"
#    echo -e "${BLUE}========================================${NC}"
#    echo
#
#    if [[ -e agi.zip ]]; then
#        echo -e "${YELLOW}agi.zip found. Proceeding to unzip.${NC}"
#        if ! command_exists 7z; then
#            echo -e "${RED}7z is not installed.${NC}"
#            exit 1
#        fi
#        7z t agi.zip || {
#            echo -e "${RED}Error: agi.zip integrity check failed.${NC}"
#            exit 1
#        }
#        7z x agi.zip -o"$agi_root" -y || {
#            echo -e "${RED}Error: Extraction of agi.zip failed.${NC}"
#            exit 1
#        }
#        echo -e "${GREEN}Extraction completed successfully.${NC}"
#    else
#        echo -e "${RED}agi.zip not found in the current directory. Exiting.${NC}"
#        exit 1
#    fi
#    echo
#}
#
#
#
#main() {
#    echo -e "${BLUE}===================================================${NC}"
#    echo -e "${BLUE}Unified Python and agilab Project Installation Script${NC}"
#    echo -e "${BLUE}===================================================${NC}"
#    echo
#
#    if [[ ! -d "$PWD/agi" ]]; then
#      echo -e "${RED}Agi project not found in the current directory. Exiting.${NC}"
#      exit 1
#    fi
#
#    check_internet
#    install_dependencies
#    set_locale
#    get_script_dirs
#    write_install_path
#    backup_agi_project
#    # Uncomment next line if you prefer unzipping:
#    # unzip_agi_project
#    copy_agi_project
#
#    echo -e "${BLUE}===============================${NC}"
#    echo -e "${BLUE}Step 8: Installing agi${NC}"
#    echo -e "${BLUE}===============================${NC}"
#    echo
#    source "$agi_path/install.sh" --cluster-credentials "$cluster_credentials" --openai-api-key "$openai_api_key"
#
#    echo -e "${BLUE}================================${NC}"
#    echo -e "${BLUE}Step 9: Generating documentation${NC}"
#    echo -e "${BLUE}================================${NC}"
#    echo
#    [ -f "uv.lock" ] && rm "uv.lock"
#    [ -d ".venv" ] && rm -r ".venv"
#    uv sync -p "${PYTHON_VERSION}" --group sphinx
#
#    uv run docs/gen-docs.py
#
#    echo -e "${GREEN}========================================${NC}"
#    echo -e "${GREEN}Installation Completed Successfully!${NC}"
#    echo -e "${GREEN}========================================${NC}"
#    echo
#
#    echo -e "${GREEN}Starting AGILAB from $agi_path${NC}"
#    "$agi_path/agilab.sh" || {
#        echo -e "${RED}Error: Failed to start AGILAB.${NC}"
#        exit 1
#    }
#    echo -e "${GREEN}AGILAB started successfully.${NC}"
#}

