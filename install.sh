#!/bin/bash
set -e
set -o pipefail

# ================================
# Initial Setup
# ================================
LOG_DIR="$HOME/log/install_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

# Colors for output
RED='\033[1;31m'
GREEN='\033[1;32m'
BLUE='\033[1;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Prevent Running as Root
if [[ "$EUID" -eq 0 ]]; then
    echo -e "${RED}Error: This script should not be run as root. Please run as a regular user.${NC}"
    exit 1
fi

# Remove unwanted files/directories
find . \( -name ".venv" -o -name "uv.lock" -o -name "build" -o -name "dist" -o -name "*egg-info" \) -exec rm -rf {} +

# ================================
# Command-Line Arguments
# ================================
usage() {
    echo "Usage: $0 --cluster-ssh-credentials <user[:password]> --openai-api-key <api-key> [--install-path <path>]"
    exit 1
}

AGI_INSTALL_PATH="$(realpath '.')"
CURRENT_PATH="$(realpath '.')"
cluster_credentials=""
openai_api_key=""

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --cluster-ssh-credentials) cluster_credentials="$2"; shift 2;;
        --openai-api-key)      openai_api_key="$2";      shift 2;;
        --install-path)        AGI_INSTALL_PATH=$(realpath "$2"); shift 2;;
        *) echo -e "${RED}Unknown option: $1${NC}" && usage;;
    esac
done

# Validate mandatory parameters
if [[ -z "$cluster_credentials" ]]; then
    echo -e "${RED}Missing mandatory parameter: --cluster-ssh-credentials${NC}"
    usage
fi

# Ensure credentials are in user[:password] form
if [[ ! "$cluster_credentials" =~ ^[^:]+(:.*)?$ ]]; then
    echo -e "${RED}Invalid format for --cluster-ssh-credentials. Expected user or user:password${NC}"
    usage
fi

if [[ -z "$openai_api_key" ]]; then
    echo -e "${RED}Missing mandatory parameter: --openai-api-key${NC}"
    usage
fi

read -p "Enter Python version [3.13]: " PYTHON_VERSION
PYTHON_VERSION=${PYTHON_VERSION:-3.13}
echo "You selected Python version $PYTHON_VERSION"

# ================================
# Pre-check Functions
# ================================
check_internet() {
    echo -e "${BLUE}Checking internet connectivity...${NC}"
    curl -s --head --fail https://www.google.com >/dev/null || {
        echo -e "${RED}No internet connection detected. Aborting.${NC}"
        exit 1
    }
    echo -e "${GREEN}Internet connection is OK.${NC}"
}

set_locale() {
    echo -e "${BLUE}Setting locale...${NC}"
    if ! locale -a | grep -q "en_US.utf8"; then
        echo -e "${YELLOW}Locale en_US.UTF-8 not found. Generating...${NC}"
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            sudo locale-gen en_US.UTF-8 || { echo -e "${RED}Error generating locale. Please generate it manually.${NC}"; exit 1; }
            echo -e "${GREEN}Locale en_US.UTF-8 generated successfully.${NC}"
        elif [[ "$OSTYPE" == "darwin"* ]]; then
            echo -e "${YELLOW}macOS typically includes en_US.UTF-8 by default. Skipping locale generation.${NC}"
        else
            echo -e "${RED}Unsupported OS for locale generation.${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}Locale en_US.UTF-8 is already available.${NC}"
    fi
    export LC_ALL=en_US.UTF-8
    export LANG=en_US.UTF-8
}

install_dependencies() {
    echo -e "${BLUE}Step: Installing system dependencies...${NC}"
    read -rp "Do you want to install system dependencies? (y/N): " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { echo -e "${YELLOW}Skipping dependency installation.${NC}"; return; }

    if ! command -v uv > /dev/null 2>&1; then
        echo -e "${GREEN}Installing uv...${NC}"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source "$HOME/.local/bin/env"
    fi

    if command -v apt >/dev/null 2>&1; then
        echo -e "${BLUE}Detected apt package manager (Linux).${NC}"
        sudo apt update
        sudo apt install -y build-essential curl wget unzip \
            software-properties-common libssl-dev zlib1g-dev \
            libbz2-dev libreadline-dev libsqlite3-dev libxml2-dev \
            liblzma-dev llvm tk-dev p7zip-full libffi-dev clang sshpass

    elif command -v dnf >/dev/null 2>&1; then
        echo -e "${BLUE}Detected dnf package manager (Linux).${NC}"
        sudo dnf install -y @development-tools wget curl unzip \
            openssl-devel zlib-devel ncurses-devel bzip2-devel \
            readline-devel sqlite-devel libxml2-devel xz-devel \
            libffi-devel gdbm-devel nss-devel clang
    elif command -v brew >/dev/null 2>&1; then
        echo -e "${BLUE}Detected Homebrew (macOS).${NC}"
        brew upgrade
        brew install wget curl unzip openssl readline sqlite libxml2 xz hudochenkov/sshpass/sshpass tree Graphviz sshpass
        brew cleanup
    else
        echo -e "${BLUE}Installing Homebrew.${NC}"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
        eval "$(/opt/homebrew/bin/brew shellenv)"
        brew install wget curl unzip openssl readline sqlite libxml2 xz hudochenkov/sshpass/sshpass tree Graphviz sshpass
        brew cleanup
    fi
}

choose_python_version() {
    echo -e "${BLUE}Choosing Python version...${NC}"
    available_python_versions=$(uv python list | grep -F -- "$PYTHON_VERSION")
    python_array=()
    while IFS= read -r line; do
        python_array+=("$line")
    done <<< "$available_python_versions"

    for idx in "${!python_array[@]}"; do
        if [[ "${python_array[$idx]}" == *"$PYTHON_VERSION"* ]]; then
            echo -e "${GREEN}$((idx + 1)) - ${python_array[$idx]}${NC}"
        else
            echo -e "$((idx + 1)) - ${python_array[$idx]}"
        fi
    done

    while true; do
        read -rp "Enter the number of the Python version you want to use (default: 1) " selection
        selection=${selection:-1}
        if [[ $selection =~ ^[0-9]+$ ]] && (( selection >= 1 && selection <= ${#python_array[@]} )); then
            chosen_python=$(echo "${python_array[$((selection - 1))]}" | cut -d' ' -f1)
            break
        else
            echo "Invalid selection. Please try again."
        fi
    done

    installed_pythons=$(uv python list --only-installed | cut -d' ' -f1)
    if ! echo "$installed_pythons" | grep -q "$chosen_python"; then
        echo -e "${YELLOW}Installing $chosen_python...${NC}"
        uv python install "$chosen_python"
        echo -e "${GREEN}Python version ($chosen_python) is now installed.${NC}"
    else
        echo -e "${GREEN}Python version ($chosen_python) is already installed.${NC}"
    fi

    export PYTHON_VERSION=$(echo "$chosen_python" | cut -d '-' -f2)
}

backup_existing_project() {
    if [[ -d "$AGI_INSTALL_PATH" && -f "$AGI_INSTALL_PATH/zip-agi.py" && "$AGI_INSTALL_PATH" != "$CURRENT_PATH" ]]; then
        echo -e "${YELLOW}Existing project found at $AGI_INSTALL_PATH with zip-agi.py present.${NC}"
        backup_file="${AGI_INSTALL_PATH}_backup_$(date +%Y%m%d-%H%M%S).zip"
        echo -e "${YELLOW}Creating backup: $backup_file${NC}"
        if uv run --project "$AGI_INSTALL_PATH/fwk/core/managers" python "$AGI_INSTALL_PATH/zip-agi.py" --dir2zip "$AGI_INSTALL_PATH" --zipfile "$backup_file"; then
            echo -e "${GREEN}Backup created successfully at $backup_file.${NC}"
            echo -e "${YELLOW}Removing existing project directory...${NC}"
            rm -ri "$AGI_INSTALL_PATH"
        else
            echo -e "${RED}ERROR: Backup failed. Switching to fallback backup strategy...${NC}"
            if zip -r "$backup_file" "$AGI_INSTALL_PATH"; then
                echo -e "${YELLOW}Fallback backup created at $backup_file.${NC}"
                echo -e "${YELLOW}Removing existing project directory...${NC}"
                rm -ri "$AGI_INSTALL_PATH"
            else
                echo -e "${RED}Failed to create backup using fallback strategy.${NC}"
                exit 1
            fi
        fi
    else
        echo -e "${YELLOW}No valid existing project found or install dir is same as current directory. Skipping backup.${NC}"
    fi
}

copy_project_files() {
    if [[ "$AGI_INSTALL_PATH" != "$CURRENT_PATH" ]]; then
        [[ -d "$CURRENT_PATH/src" ]] || { echo -e "${RED}Source directory 'src' not found. Exiting.${NC}"; exit 1; }
        echo -e "${BLUE}Copying project files to install directory...${NC}"
        mkdir -p "$AGI_INSTALL_PATH"
        rsync -a "$CURRENT_PATH/" "$AGI_INSTALL_PATH/"
    else
        echo "Using current directory as install directory; no copy needed."
    fi
    mkdir -p "$HOME/.local/share/agilab"
    echo "$AGI_INSTALL_PATH/src/agi" > "$HOME/.local/share/agilab/.agi-path"
}

update_environment() {
    ENV_FILE="$HOME/.local/share/agilab/.env"
    [[ -f "$ENV_FILE" ]] && rm "$ENV_FILE"
    mkdir -p "$(dirname "$ENV_FILE")"
    {
        echo "OPENAI_API_KEY=\"$openai_api_key\""
        echo "CLUSTER_CREDENTIALS=\"$cluster_credentials\""
        echo "AGI_PYTHON_VERSION=\"$PYTHON_VERSION\""
    } > "$ENV_FILE"
    echo -e "${GREEN}Environment updated in $ENV_FILE${NC}"
}

install_framework() {
    framework_dir="$AGI_INSTALL_PATH/src/agi/fwk"
    chmod +x "$framework_dir/install.sh"

    echo -e "${BLUE}Installing Framework...${NC}"
    pushd "$framework_dir" > /dev/null
      ./install.sh "$framework_dir"
    popd  > /dev/null
}

install_apps() {
    apps_dir="$AGI_INSTALL_PATH/src/agi/apps"
    chmod +x "$apps_dir/install.sh"

    echo -e "${BLUE}Installing Apps...${NC}"
    pushd "$apps_dir" > /dev/null
      ./install.sh "$apps_dir" "1"
    popd  > /dev/null
}

write_env_values() {
    shared_env="$HOME/.local/share/agilab/.env"
    agilab_env="$HOME/.agi/.env"

    [[ -f "$shared_env" ]] || { echo -e "${RED}Error: $shared_env does not exist.${NC}"; return 1; }

    # Detect platform for sed
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed_cmd() { sed -i '' "s|^$1=.*|$1=$2|" "$agilab_env"; }
    else
        sed_cmd() { sed -i "s|^$1=.*|$1=$2|" "$agilab_env"; }
    fi

    while IFS='=' read -r key value || [[ -n "$key" ]]; do
        [[ -z "$key" || "$key" =~ ^# ]] && continue
        if grep -q "^$key=" "$agilab_env"; then
            current_value=$(grep "^$key=" "$agilab_env" | cut -d '=' -f2-)
            [[ "$current_value" != "$value" ]] && sed_cmd "$key" "$value"
        else
            echo "$key=$value" >> "$agilab_env"
        fi
    done < "$shared_env"

    echo -e "${GREEN}.env file updated.${NC}"
}

# ================================
# Script Execution
# ================================
check_internet
set_locale
install_dependencies
choose_python_version
backup_existing_project
copy_project_files
update_environment
install_framework
write_env_values
install_apps

echo -e "${GREEN}Installation complete!${NC}"
