#!/bin/bash
set -e
set -o pipefail

LOG_DIR="$HOME/log/install_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install_$(date +%Y%m%d_%H%M%S).log"_
exec > >(tee -a "$LOG_FILE") 2>&1

START_TIME=$(date +%s)

# Colors for output
RED='\033[1;31m'
GREEN='\033[1;32m'
BLUE='\033[1;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

UV="uv --preview-features extra-build-dependencies"

CALLER_DIR="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Always operate relative to the repository root even if invoked from another directory.
cd "$SCRIPT_DIR"

FAST_MODE=0
ASSUME_YES=0
FAST_MODE_USER_SET=0
AUTO_FAST_DEFAULT="${AGILAB_AUTO_FAST:-1}"
PYTHON_VERSION_OVERRIDE=""
AGI_ENV_FILE="$HOME/.local/share/agilab/.env"
PREVIOUS_ENV_LOADED=0

AGI_INSTALL_PATH="$(realpath '.')"
CURRENT_PATH="$AGI_INSTALL_PATH"
CLUSTER_CREDENTIALS=""
OPENAI_API_KEY=""
SOURCE="local"
INSTALL_APPS_FLAG=0
TEST_APPS_FLAG=0
APPS_REPOSITORY=""

if [[ -f "$AGI_ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$AGI_ENV_FILE"
    PREVIOUS_ENV_LOADED=1
fi

AGI_PYTHON_FREE_THREADED="${AGI_PYTHON_FREE_THREADED:-0}"

warn() {
    echo -e "${YELLOW}Warning:${NC} $*"
}

should_auto_fast() {
    # Require previous install context and a repo checkout
    (( PREVIOUS_ENV_LOADED )) || return 1
    [[ -d "$SCRIPT_DIR/.git" ]] || return 1
    [[ -d "$SCRIPT_DIR/src/agilab" ]] || return 1
    [[ -d "$SCRIPT_DIR/src/agilab/core" ]] || return 1
    return 0
}

maybe_enable_auto_fast() {
    (( FAST_MODE_USER_SET )) && return
    (( FAST_MODE )) && return

    if [[ "$AUTO_FAST_DEFAULT" == "0" ]]; then
        echo -e "${BLUE}Auto fast mode disabled (AGILAB_AUTO_FAST=0 or --no-fast).${NC}"
        return
    fi

    if ! should_auto_fast; then
        return
    fi

    local auto_enabled_message="Fast mode enabled automatically (previous install detected)."

    if (( ASSUME_YES )) || [[ ! -t 0 ]]; then
        FAST_MODE=1
        echo -e "${BLUE}${auto_enabled_message}${NC}"
        return
    fi

    if [[ -t 0 ]]; then
        read -rp "Previous install detected. Enable fast mode (skip system deps, locale, offline extras)? [Y/n]: " response
        response=${response:-Y}
        if [[ "$response" =~ ^[Yy]$ ]]; then
            FAST_MODE=1
            echo -e "${BLUE}${auto_enabled_message}${NC}"
        else
            echo -e "${BLUE}Fast mode skipped; running full install.${NC}"
        fi
    fi
}

ensure_python_runtime() {
    local version="$1"
    if [[ -z "$version" ]]; then
        version="3.13"
    fi

    echo -e "${BLUE}Ensuring Python ${version} is available...${NC}"
    local installed
    installed="$($UV python list --only-installed 2>/dev/null | awk '{print $1}' || true)"
    if ! grep -F -- "$version" <<<"$installed" >/dev/null; then
        echo -e "${YELLOW}Installing Python ${version} via uv...${NC}"
        $UV python install "$version"
        installed="$($UV python list --only-installed 2>/dev/null | awk '{print $1}' || true)"
    else
        echo -e "${GREEN}Python version (${version}) is already installed.${NC}"
    fi

    if (( FAST_MODE )); then
        warn "Fast mode: skipping freethreaded interpreter setup."
        AGI_PYTHON_FREE_THREADED=0
    else
        local python_list matches
        python_list="$($UV python list)"
        matches="$(grep -F -- "$version" <<<"$python_list" || true)"
        if grep -qi "freethreaded" <<<"$matches"; then
            local freethreaded="${version}+freethreaded"
            if ! grep -F -- "$freethreaded" <<<"$installed" >/dev/null; then
                echo -e "${YELLOW}Installing ${freethreaded} via uv...${NC}"
                $UV python install "$freethreaded"
            fi
            AGI_PYTHON_FREE_THREADED=1
        else
            AGI_PYTHON_FREE_THREADED=0
        fi
    fi

    AGI_PYTHON_VERSION="$version"
    export AGI_PYTHON_FREE_THREADED AGI_PYTHON_VERSION
}

interactive_python_selection() {
    local default_version="3.13"
    read -p "Enter Python major version [${default_version}]: " PYTHON_VERSION
    PYTHON_VERSION=${PYTHON_VERSION:-$default_version}
    echo "You selected Python version $PYTHON_VERSION"

    local available_python_versions
    available_python_versions="$($UV python list | grep -F -- "$PYTHON_VERSION" | grep -v "freethreaded" || true)"

    if [[ -z "$available_python_versions" ]]; then
        warn "No matching Python release found by uv for '$PYTHON_VERSION'. Proceeding with the requested version spec."
        echo "$PYTHON_VERSION"
        return 0
    fi

    local python_array=()
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        python_array+=("$line")
    done <<< "$available_python_versions"

    for idx in "${!python_array[@]}"; do
        if [[ "${python_array[$idx]}" == *"$PYTHON_VERSION"* ]]; then
            echo -e "${GREEN}$((idx + 1)) - ${python_array[$idx]}${NC}"
        else
            echo -e "$((idx + 1)) - ${python_array[$idx]}"
        fi
    done

    local selection
    while true; do
        read -rp "Enter the number of the Python version you want to use (default: 1) " selection
        selection=${selection:-1}
        if [[ $selection =~ ^[0-9]+$ ]] && (( selection >= 1 && selection <= ${#python_array[@]} )); then
            local choice
            choice=$(echo "${python_array[$((selection - 1))]}" | awk '{print $1}')
            choice=$(echo "$choice" | cut -d '-' -f2)
            echo "$choice"
            return 0
        fi
        echo "Invalid selection. Please try again."
    done
}

install_offline_extra() {
    if (( FAST_MODE )); then
        warn "Fast mode: skipping offline assistant extra dependencies."
        return
    fi

    local pyver="${AGI_PYTHON_VERSION:-}"
    local major minor patch
    IFS='.' read -r major minor patch <<< "$pyver"
    if [[ -z "$major" || -z "$minor" ]]; then
        warn "Could not parse Python version '$pyver'; skipping GPT-OSS offline assistant installation."
        return
    fi

    if (( major > 3 || (major == 3 && minor >= 12) )); then
        echo -e "${BLUE}Installing offline assistant dependencies (GPT-OSS + mistral:instruct)...${NC}"
        if $UV pip install ".[offline]" >/dev/null 2>&1; then
            echo -e "${GREEN}Offline assistant packages installed.${NC}"
        else
            warn "Unable to install offline extras (pip install .[offline]). Install them manually when Python >=3.12 is available."
        fi
        local ensure_specs=("transformers>=4.57.0" "torch>=2.8.0" "accelerate>=0.34.2" "universal-offline-ai-chatbot>=0.1.0")
        for spec in "${ensure_specs[@]}"; do
            local pkg="${spec%%>=*}"
            if ! $UV pip show "${pkg}" >/dev/null 2>&1; then
                if $UV pip install "${spec}" >/dev/null 2>&1; then
                    echo -e "${GREEN}Installed ${spec} for offline assistant support.${NC}"
                else
                    warn "Failed to install ${spec}. Install it manually if you plan to use the ${pkg} backend."
                fi
            fi
        done
    else
        warn "Skipping GPT-OSS offline assistant (requires Python >=3.12)."
    fi
}

setup_mistral_offline() {
    if (( FAST_MODE )); then
        warn "Fast mode: skipping local Mistral (Ollama) setup."
        return
    fi

    echo -e "${BLUE}Configuring local Mistral assistant (Ollama)...${NC}"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if ! command -v ollama >/dev/null 2>&1; then
            if command -v brew >/dev/null 2>&1; then
                echo -e "${BLUE}Installing Ollama via Homebrew...${NC}"
                brew install --cask ollama || warn "Failed to install Ollama via Homebrew. Install it manually from https://ollama.com."
            else
                warn "Homebrew not found; install Ollama manually from https://ollama.com."
                return
            fi
        fi

        # Start Ollama as a launch agent if possible
        if command -v brew >/dev/null 2>&1; then
            brew services start ollama >/dev/null 2>&1 || true
        fi

        mkdir -p "$HOME/log"
        # Pull the mistral:instruct model in the background (can be large)
        if command -v ollama >/dev/null 2>&1; then
            echo -e "${BLUE}Starting model download: mistral:instruct (running in background)...${NC}"
            nohup ollama pull mistral:instruct > "$HOME/log/ollama_pull_mistral.log" 2>&1 &
            echo $! > "$HOME/log/ollama_pull_mistral.pid"
            echo -e "${GREEN}Pull started. Monitor: tail -f $HOME/log/ollama_pull_mistral.log${NC}"
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* || "$OSTYPE" == "linux"* ]]; then
        # Linux path: use official installer
        if ! command -v ollama >/dev/null 2>&1; then
            echo -e "${BLUE}Installing Ollama (Linux)...${NC}"
            if curl -fsSL https://ollama.com/install.sh | sh; then
                echo -e "${GREEN}Ollama installed.${NC}"
            else
                warn "Failed to install Ollama via script. Install manually from https://ollama.com."
                return
            fi
        fi

        # Try to start Ollama
        if command -v systemctl >/dev/null 2>&1; then
            sudo systemctl enable --now ollama >/dev/null 2>&1 || true
        fi
        # Fallback to foreground server in background
        if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
            nohup ollama serve > "$HOME/log/ollama_serve.log" 2>&1 &
            sleep 2
        fi

        mkdir -p "$HOME/log"
        echo -e "${BLUE}Starting model download: mistral:instruct (running in background)...${NC}"
        nohup ollama pull mistral:instruct > "$HOME/log/ollama_pull_mistral.log" 2>&1 &
        nohup ollama pull gpt-oss:20b > "$HOME/log/ollama_pull_gpt-oss.log" 2>&1 &

        echo $! > "$HOME/log/ollama_pull_mistral.pid"
        echo -e "${GREEN}Pull started. Monitor: tail -f $HOME/log/ollama_pull_mistral.log${NC}"
    else
        # Unsupported OS automation
        warn "Automatic Ollama setup is available for macOS and Linux. Install Ollama and pull 'mistral:instruct' manually."
    fi
}

seed_mistral_pdfs() {
    if (( FAST_MODE )); then
        warn "Fast mode: skipping PDF seeding for offline assistants."
        return
    fi

    echo -e "${BLUE}Seeding sample PDFs for mistral:instruct (optional)...${NC}"
    local dest="$HOME/.agilab/mistral_offline/data"
    mkdir -p "$dest"

    # Prefer curated path under resources/mistral_offline/data
    local src1="$AGI_INSTALL_PATH/src/agilab/core/agi-env/src/agi_env/resources/mistral_offline/data"
    # Fallback to older stash path under resources/.agilab/pdfs
    local src2="$AGI_INSTALL_PATH/src/agilab/core/agi-env/src/agi_env/resources/.agilab/pdfs"

    local copied=0
    if [[ -d "$src1" ]]; then
        # Copy top-level PDFs
        if compgen -G "$src1/*.pdf" > /dev/null; then
            cp -f "$src1"/*.pdf "$dest"/ && copied=1
        fi
        # Copy nested PDFs
        find "$src1" -type f -iname "*.pdf" -exec cp -f {} "$dest"/ \; && copied=1
    fi

    if [[ $copied -eq 0 && -d "$src2" ]]; then
        if compgen -G "$src2/*.pdf" > /dev/null; then
            cp -f "$src2"/*.pdf "$dest"/ && copied=1
        fi
        find "$src2" -type f -iname "*.pdf" -exec cp -f {} "$dest"/ \; && copied=1
    fi

    if [[ $copied -eq 1 ]]; then
        echo -e "${GREEN}Seeded PDFs into $dest${NC}"
    else
        warn "No sample PDFs found in resources; skipping seeding."
    fi
}

refresh_launch_matrix() {
    if (( FAST_MODE )); then
        warn "Fast mode: skipping Launch Matrix refresh."
        return
    fi

    echo -e "${BLUE}Refreshing Launch Matrix from .idea/runConfigurations...${NC}"
    pushd "$AGI_INSTALL_PATH" > /dev/null || return 0
    if [[ -f "tools/refresh_launch_matrix.py" ]]; then
        # Best-effort; do not fail install if this step errors
        $UV run -p "$AGI_PYTHON_VERSION" python tools/refresh_launch_matrix.py --inplace \
          && echo -e "${GREEN}Launch Matrix updated in AGENTS.md.${NC}" \
          || warn "Launch Matrix refresh skipped (tooling not available)."
    else
        warn "No tools/refresh_launch_matrix.py found; skipping matrix refresh."
    fi
    popd > /dev/null || true
}

check_internet() {
    echo -e "${BLUE}Checking internet connectivity...${NC}"
    curl -s --head --fail https://www.google.com >/dev/null || {
        echo -e "${RED}No internet connection detected. Aborting.${NC}"
        exit 1
    }
    echo -e "${GREEN}Internet connection is OK.${NC}"
}

set_locale() {
    if (( FAST_MODE )); then
        warn "Fast mode: skipping locale check."
        return
    fi

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
    if (( FAST_MODE )); then
        warn "Fast mode: skipping system dependency installation."
        return
    fi

    echo -e "${BLUE}Step: Installing system dependencies...${NC}"
    local confirm="n"
    if (( ASSUME_YES )); then
        confirm="y"
        echo -e "${BLUE}--yes provided: auto-confirming system dependency installation.${NC}"
    else
        read -rp "Do you want to install system dependencies? (y/N): " confirm
    fi
    [[ "$confirm" =~ ^[Yy]$ ]] || { warn "Skipping dependency installation."; return; }

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
        brew install wget curl unzip openssl readline sqlite libxml2 xz tree Graphviz sshpass
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
    local chosen_python=""

    if [[ -n "$PYTHON_VERSION_OVERRIDE" ]]; then
        chosen_python="$PYTHON_VERSION_OVERRIDE"
        echo -e "${BLUE}Using Python version supplied via --python-version: ${chosen_python}${NC}"
    elif [[ -n "$AGI_PYTHON_VERSION" ]]; then
        chosen_python="$AGI_PYTHON_VERSION"
        if (( PREVIOUS_ENV_LOADED )); then
            echo -e "${BLUE}Reusing Python version from previous install: ${chosen_python}${NC}"
        else
            echo -e "${BLUE}Using preset AGI_PYTHON_VERSION: ${chosen_python}${NC}"
        fi
    elif (( FAST_MODE )); then
        chosen_python="3.13"
        echo -e "${BLUE}Fast mode: defaulting to Python ${chosen_python}.${NC}"
    else
        chosen_python="$(interactive_python_selection)"
    fi

    ensure_python_runtime "$chosen_python"
}


backup_existing_project() {
    if [[ -d "$AGI_INSTALL_PATH" && -f "$AGI_INSTALL_PATH/zip-agi.py" && "$AGI_INSTALL_PATH" != "$CURRENT_PATH" ]]; then
        echo -e "${YELLOW}Existing project found at $AGI_INSTALL_PATH with zip-agi.py present.${NC}"
        backup_file="${AGI_INSTALL_PATH}_backup_$(date +%Y%m%d-%H%M%S).zip"
        echo -e "${YELLOW}Creating backup: $backup_file${NC}"
        if $UV run --project "$AGI_INSTALL_PATH/agilab/node" python "$AGI_INSTALL_PATH/zip-agi.py" --dir2zip "$AGI_INSTALL_PATH" --zipfile "$backup_file"; then
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
    echo "$AGI_INSTALL_PATH/src/agilab" > "$HOME/.local/share/agilab/.agilab-path"
}

update_environment() {
    ENV_FILE="$HOME/.local/share/agilab/.env"
    [[ -f "$ENV_FILE" ]] && rm "$ENV_FILE"
    mkdir -p "$(dirname "$ENV_FILE")"
    {
        echo "OPENAI_API_KEY=\"$openai_api_key\""
        echo "CLUSTER_CREDENTIALS=\"$cluster_credentials\""
        echo "AGI_PYTHON_VERSION=\"$AGI_PYTHON_VERSION\""
        echo "AGI_PYTHON_FREE_THREADED=\"$AGI_PYTHON_FREE_THREADED\""
        echo "APPS_REPOSITORY=\"$APPS_REPOSITORY\""
    } > "$ENV_FILE"
    echo -e "${GREEN}Environment updated in $ENV_FILE${NC}"
}

write_env_values() {
    shared_env="$HOME/.local/share/agilab/.env"
    agilab_env="$HOME/.agilab/.env"

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

install_core() {
    framework_dir="$AGI_INSTALL_PATH/src/agilab/core"
    chmod +x "$framework_dir/install.sh"

    echo -e "${BLUE}Installing Framework...${NC}"
    pushd "$framework_dir" > /dev/null
    ./install.sh "$framework_dir"
    popd  > /dev/null
}

install_apps() {
  dir="$AGI_INSTALL_PATH/src/agilab"
  pushd $dir > /dev/null
  chmod +x "install_apps.sh"
  local agilab_public
  agilab_public="$(cat "$HOME/.local/share/agilab/.agilab-path")"
  if (( TEST_APPS_FLAG )); then
    install_args+=(--test-apps)
  fi
  APPS_DEST_BASE="${agilab_public}/apps" \
  PAGES_DEST_BASE="${agilab_public}/apps-pages" \
    ./install_apps.sh "${install_args[@]}"
  popd > /dev/null
}

install_enduser() {
    pushd "tools" > /dev/null
    echo -e "${BLUE}Installing agilab (endusers)...${NC}"
    chmod +x "./install_enduser.sh"
    ./install_enduser.sh --source $SOURCE
    echo -e "${GREEN}agilab (enduser) installation complete.${NC}"
    popd > /dev/null
}

install_pycharm_script() {
    rm -f .idea/workspace.xml
    echo -e "${BLUE}Patching PyCharm workspace.xml interpreter settings...${NC}"
    $UV run -p "$AGI_PYTHON_VERSION" python pycharm/setup_pycharm.py || warn "pycharm/install-apps-script.py failed or not found; continuing."
}

usage() {
    echo "Usage: $0 --cluster-ssh-credentials <user[:password]> --openai-api-key <api-key> [--install-path <path> --apps-repository <path>] [--source local|pypi|testpypi] [--python-version <major.minor>] [--fast|--no-fast] [--yes] [--install-apps] [--test-apps]"
    exit 1
}


# ================================
# Script Execution
# ================================

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --cluster-ssh-credentials) cluster_credentials="$2"; shift 2;;
        --openai-api-key)      openai_api_key="$2";      shift 2;;
        --install-path)
            AGI_INSTALL_PATH="$(cd "$CALLER_DIR" && realpath "$2")"
            shift 2;;
        --apps-repository)
            APPS_REPOSITORY="$(cd "$CALLER_DIR" && realpath "$2")"
            shift 2;;
        --source)             SOURCE="$2"; shift 2;;
        --python-version)
            PYTHON_VERSION_OVERRIDE="$2"
            shift 2;;
        --fast)
            FAST_MODE=1
            ASSUME_YES=1
            FAST_MODE_USER_SET=1
            shift;;
        --no-fast)
            FAST_MODE=0
            AUTO_FAST_DEFAULT=0
            FAST_MODE_USER_SET=1
            shift;;
        --yes)
            ASSUME_YES=1
            shift;;
        --install-apps)       INSTALL_APPS_FLAG=1; shift;;
        --test-apps)          TEST_APPS_FLAG=1; INSTALL_APPS_FLAG=1; shift;;
        *) echo -e "${RED}Unknown option: $1${NC}" && usage;;
    esac
done

maybe_enable_auto_fast

export APPS_REPOSITORY

check_internet
set_locale
install_dependencies
choose_python_version
backup_existing_project
copy_project_files
update_environment
install_core
write_env_values

if (( INSTALL_APPS_FLAG )); then
  if ! install_apps; then
    warn "install_apps failed; continuing with PyCharm setup."
    install_pycharm_script # needed to investigate with pycharm why previous script has failed
    refresh_launch_matrix
  else
    install_pycharm_script
    refresh_launch_matrix
    install_enduser
    install_offline_extra
    seed_mistral_pdfs
    setup_mistral_offline
    echo -e "${GREEN}Installation complete!${NC}"
  fi
else
    warn "App installation skipped (use --install-apps to enable)."
    install_pycharm_script
    refresh_launch_matrix
    install_enduser
    install_offline_extra
    seed_mistral_pdfs
    setup_mistral_offline
    echo -e "${GREEN}Installation complete (apps skipped).${NC}"
fi

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
ELAPSED_MIN=$((ELAPSED / 60))
ELAPSED_SEC=$((ELAPSED % 60))
echo -e "${BLUE}Total install duration: ${ELAPSED_MIN}m ${ELAPSED_SEC}s${NC}"
