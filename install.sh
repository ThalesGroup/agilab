#!/bin/bash
set -e
set -o pipefail

LOG_DIR="$HOME/log/install_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

START_TIME=$(date +%s)

# Colors for output
RED='\033[1;31m'
GREEN='\033[1;32m'
BLUE='\033[1;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

export PATH="$HOME/.local/bin:$PATH"

UV="uv --preview-features extra-build-dependencies"

AGI_INSTALL_PATH="$(realpath '.')"
# Default share dir (can be overridden via --agi-share-dir or env)
AGI_SHARE_DIR="${AGI_SHARE_DIR:-clustershare}"
CURRENT_PATH="$(realpath '.')"
CLUSTER_CREDENTIALS=""
OPENAI_API_KEY=""
SOURCE="local"
INSTALL_APPS_FLAG=0
TEST_APPS_FLAG=0
APPS_REPOSITORY=""
CUSTOM_INSTALL_APPS=""
INSTALL_ALL_SENTINEL="__AGILAB_ALL_APPS__"
INSTALL_BUILTIN_SENTINEL="__AGILAB_BUILTIN_APPS__"
INSTALLED_APPS_FILE="${INSTALLED_APPS_FILE:-$HOME/.local/share/agilab/installed_apps.txt}"
NON_INTERACTIVE=0
export INSTALL_ALL_SENTINEL INSTALL_BUILTIN_SENTINEL INSTALLED_APPS_FILE

read_env_var() {
    local file="$1"
    local key="$2"
    [[ -f "$file" ]] || { echo ""; return 0; }
    local line
    line="$(grep -E "^${key}=" "$file" | tail -1)"
    line="${line#*=}"
    line="${line%\"}"
    line="${line#\"}"
    echo "$line"
    return 0
}

USER_ENV_FILE="$HOME/.agilab/.env"
REPO_ENV_FILE="$AGI_INSTALL_PATH/.agilab/.env"
ENV_SHARE_USER="$(read_env_var "$USER_ENV_FILE" AGI_SHARE_DIR)"
ENV_SHARE_REPO="$(read_env_var "$REPO_ENV_FILE" AGI_SHARE_DIR)"
DEFAULT_SHARE_DIR="${AGI_SHARE_DIR:-${ENV_SHARE_USER:-$ENV_SHARE_REPO}}"
DEFAULT_LOCAL_SHARE="${AGI_LOCAL_DIR:-${AGI_LOCAL_SHARE:-$HOME/localshare}}"

share_is_mounted() {
    local path="$1"
    [[ -d "$path" ]] || return 1
    local canonical
    canonical=$(cd "$path" 2>/dev/null && pwd -P) || return 1
    # Compare against canonical mount points to avoid symlink mismatch on macOS (/System/Volumes/Data/...)
    # and support Linux/WSL. Fallback to /proc/mounts if mount is unavailable.
    local mounts_source
    if command -v mount >/dev/null 2>&1; then
        mounts_source=$(mount | awk '{print $3}')
    elif [[ -r /proc/mounts ]]; then
        mounts_source=$(awk '{print $2}' /proc/mounts)
    else
        # If we cannot inspect mounts, treat existence as not mounted to force the prompt.
        return 1
    fi

    while read -r mpath; do
        [[ -z "$mpath" ]] && continue
        local mcanonical
        mcanonical=$(cd "$mpath" 2>/dev/null && pwd -P) || continue
        if [[ "$mcanonical" == "$canonical" ]]; then
            return 0
        fi
    done <<< "$mounts_source"
    return 1
}

ensure_share_dir() {
    local share_dir="$1"
    local fallback_dir="$2"
    if [[ -z "$share_dir" ]]; then
        if (( NON_INTERACTIVE )); then
            share_dir="$fallback_dir"
        elif [[ -t 0 ]]; then
            read -rp "Enter AGI_SHARE_DIR path (or press Enter to abort): " share_dir
            if [[ -z "$share_dir" ]]; then
                echo -e "${RED}AGI_SHARE_DIR not provided. Aborting.${NC}"
                exit 1
            fi
        else
            echo -e "${YELLOW}AGI_SHARE_DIR not set and no TTY available. Using fallback ${fallback_dir}.${NC}"
            share_dir="$fallback_dir"
        fi
    fi

    # Normalize to absolute path for display/use
    if [[ -n "$share_dir" ]]; then
        [[ "$share_dir" == "~"* ]] && share_dir="${share_dir/#\~/$HOME}"
        [[ "$share_dir" != /* ]] && share_dir="$HOME/$share_dir"
    fi
    if [[ -n "$fallback_dir" ]]; then
        [[ "$fallback_dir" == "~"* ]] && fallback_dir="${fallback_dir/#\~/$HOME}"
        [[ "$fallback_dir" != /* ]] && fallback_dir="$HOME/$fallback_dir"
    fi
    if [[ -n "$share_dir" ]]; then
        echo -e "${BLUE}AGI_SHARE_DIR resolved to: ${share_dir}${NC}"
    fi

    # If the share is already mounted, accept it and return.
    if share_is_mounted "$share_dir"; then
        export AGI_SHARE_DIR="$share_dir"
        export AGI_LOCAL_DIR="${AGI_LOCAL_DIR:-$fallback_dir}"
        return 0
    fi

    if (( NON_INTERACTIVE )); then
        if [[ -n "${CLUSTER_CREDENTIALS:-}" ]]; then
            echo -e "${RED}${share_dir} is not mounted. Cluster mode requires the shared path to be available; aborting (non-interactive).${NC}"
            exit 1
        fi
        echo -e "${YELLOW}AGI_SHARE_DIR ${share_dir} unavailable; non-interactive mode: using fallback ${fallback_dir}.${NC}"
        mkdir -p "$fallback_dir" || { echo -e "${RED}Failed to create fallback ${fallback_dir}.${NC}"; exit 1; }
        export AGI_LOCAL_DIR="$fallback_dir"
        export AGI_SHARE_DIR="$fallback_dir"
        return 0
    fi

    # Try to prompt even if stdin is not a TTY by borrowing /dev/tty when available.
    prompt_input() {
        local prompt="$1"
        if [[ -t 0 ]]; then
            read -rp "$prompt" choice
        elif [[ -e /dev/tty ]]; then
            read -rp "$prompt" choice < /dev/tty
        else
            choice=""
        fi
    }

    echo -e "${YELLOW}AGI_SHARE_DIR is unavailable at ${share_dir}.${NC}"
    echo -e "Choose an option:"
    echo -e "  1) Use local fallback at ${fallback_dir}"
    echo -e "  2) Wait for ${share_dir} to be mounted (mandatory for cluster installs; will timeout)"
    choice=""
    prompt_input "Enter 1 or 2 (default: 1): "
    case "$choice" in
        ""|1)
            mkdir -p "$fallback_dir" || { echo -e "${RED}Failed to create fallback ${fallback_dir}.${NC}"; exit 1; }
            export AGI_LOCAL_DIR="$fallback_dir"
            export AGI_SHARE_DIR="$fallback_dir"
            echo -e "${GREEN}Using local fallback AGI_LOCAL_DIR=${AGI_LOCAL_DIR}.${NC}"
            ;;
        2)
            echo -e "${BLUE}Waiting for ${share_dir} to become available (timeout 120s)...${NC}"
            local waited=0
            while [[ $waited -lt 120 ]]; do
                if [[ -d "$share_dir" ]]; then
                    export AGI_SHARE_DIR="$share_dir"
                    echo -e "${GREEN}${share_dir} is available. Continuing.${NC}"
                    return 0
                fi
                sleep 5
                waited=$((waited + 5))
            done
            echo -e "${RED}${share_dir} did not appear within 120s. Aborting.${NC}"
            exit 1
            ;;
        *)
            echo -e "${YELLOW}No valid input detected; defaulting to local fallback.${NC}"
            mkdir -p "$fallback_dir" || { echo -e "${RED}Failed to create fallback ${fallback_dir}.${NC}"; exit 1; }
            export AGI_LOCAL_DIR="$fallback_dir"
            export AGI_SHARE_DIR="$fallback_dir"
            ;;
    esac
}

warn() {
    echo -e "${YELLOW}Warning:${NC} $*"
}

install_offline_extra() {
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
    echo -e "${BLUE}Seeding sample PDFs for mistral:instruct (optional)...${NC}"
    local dest="$HOME/.agilab/mistral_offline/data"
    mkdir -p "$dest"

    # Prefer curated path under resources/mistral_offline/data
    local src1="$AGI_INSTALL_PATH/src/agilab/core/agi-env/src/agi_env/resources/mistral_offline/data"

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


verify_share_dir() {
    local share_dir="${AGI_SHARE_DIR:-$HOME/clustershare}"
    local local_dir="${AGI_LOCAL_DIR:-}"
    [[ "$share_dir" == "~"* ]] && share_dir="${share_dir/#\~/$HOME}"

    # If we're intentionally using the local fallback, only require existence.
    if [[ -n "$local_dir" && "$share_dir" == "$local_dir" ]]; then
        if [[ -d "$share_dir" ]]; then
            return 0
        fi
        echo -e "${RED}Local AGI_SHARE_DIR missing:${NC} expected data dir at '$share_dir'."
        exit 1
    fi

    # Otherwise require a mounted share.
    if share_is_mounted "$share_dir"; then
        return 0
    fi

    echo -e "${RED}AGI_SHARE_DIR missing:${NC} expected mounted data share at '$share_dir'."
    echo -e "${YELLOW}Mount your cluster share or export AGI_SHARE_DIR to the correct path, then rerun install.sh.${NC}"
    exit 1
}

install_dependencies() {
    echo -e "${BLUE}Step: Installing system dependencies...${NC}"
    local confirm="n"
    if (( NON_INTERACTIVE )); then
        warn "Non-interactive mode; skipping dependency installation."
    elif [[ -t 0 ]]; then
        read -rp "Do you want to install system dependencies? (y/N): " confirm
    else
        warn "Non-interactive shell detected; skipping dependency installation by default."
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
    if (( NON_INTERACTIVE )); then
        PYTHON_VERSION="${AGI_PYTHON_VERSION:-3.13}"
        echo "Non-interactive mode; defaulting Python version to $PYTHON_VERSION"
    else
        if [[ -t 0 ]]; then
            read -p "Enter Python major version [3.13]: " PYTHON_VERSION
        else
            PYTHON_VERSION="${AGI_PYTHON_VERSION:-3.13}"
            echo "Non-interactive shell; defaulting Python version to $PYTHON_VERSION"
        fi
    fi
    PYTHON_VERSION=${PYTHON_VERSION:-3.13}
    echo "You selected Python version $PYTHON_VERSION"
    available_python_versions=$($UV python list | grep -F -- "$PYTHON_VERSION" | grep -v "freethreaded")
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

    if (( NON_INTERACTIVE )); then
        chosen_python=$(echo "${python_array[0]}" | cut -d' ' -f1)
        echo "Non-interactive mode: selected first available Python: $chosen_python"
    else
        if [[ -t 0 ]]; then
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
        else
            chosen_python=$(echo "${python_array[0]}" | cut -d' ' -f1)
            echo "Selected first available Python: $chosen_python"
        fi
    fi

    installed_pythons=$($UV python list --only-installed | cut -d' ' -f1)
    if ! echo "$installed_pythons" | grep -q "$chosen_python"; then
        echo -e "${YELLOW}Installing $chosen_python...${NC}"
        $UV python install "$chosen_python"
        echo -e "${GREEN}Python version ($chosen_python) is now installed.${NC}"
    else
        echo -e "${GREEN}Python version ($chosen_python) is already installed.${NC}"
    fi

    chosen_python=$(echo "$chosen_python" | cut -d '-' -f2)
    if $UV python list | grep "$chosen_python" | grep -q "freethreaded"; then
        echo -e "${YELLOW}Freethreaded version available.${NC}"
        chosen_python_free="${chosen_python}+freethreaded"
        if ! echo "$installed_pythons" | grep -q "$chosen_python_free"; then
            echo -e "${YELLOW}Installing $chosen_python_free...${NC}"
            $UV python install "$chosen_python_free"
            echo -e "${GREEN}Python version ($chosen_python_free) is now installed.${NC}"
        else
            echo -e "${GREEN}Python version ($chosen_python_free) is already installed.${NC}"
        fi
        AGI_PYTHON_FREE_THREADED=1
    fi

    AGI_PYTHON_VERSION="$chosen_python"
    export AGI_PYTHON_FREE_THREADED
    export AGI_PYTHON_VERSION
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
        rsync -a \
            --exclude 'src/agilab/apps/*_project/' \
            "$CURRENT_PATH/" "$AGI_INSTALL_PATH/"
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
    mkdir -p "$(dirname "$agilab_env")"
    [[ -f "$agilab_env" ]] || touch "$agilab_env"

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

configure_streamlit() {
    local config_dir="$HOME/.streamlit"
    local config_file="$config_dir/config.toml"
    local desired="${STREAMLIT_MAX_MESSAGE_SIZE:-600}"

    # Preferred approach: rely on AgiEnv to propagate STREAMLIT_MAX_MESSAGE_SIZE /
    # STREAMLIT_SERVER_MAX_MESSAGE_SIZE into the runtime environment. Avoid touching
    # ~/.streamlit/config.toml to prevent user-config conflicts.
    echo -e "${GREEN}Skipping Streamlit config file update; set STREAMLIT_MAX_MESSAGE_SIZE in .env for AgiEnv to propagate.${NC}"
}

install_core() {
    framework_dir="$AGI_INSTALL_PATH/src/agilab/core"
    chmod +x "$framework_dir/install.sh"

    echo -e "${BLUE}Installing Framework...${NC}"
    pushd "$framework_dir" > /dev/null
    ./install.sh "$framework_dir"
    popd  > /dev/null
}

run_repository_tests_with_coverage() {
    local repo_root="$AGI_INSTALL_PATH"
    local coverage_status=0
    local -a app_test_dirs=()
    local -a page_test_dirs=()
    local installed_apps_file="${INSTALLED_APPS_FILE:-$HOME/.local/share/agilab/installed_apps.txt}"
    local -a installed_apps=()
    if [[ -f "$installed_apps_file" ]]; then
        while IFS= read -r app || [[ -n "$app" ]]; do
            app="${app%%#*}"
            app="${app//$'\r'/}"
            app="${app//$'\t'/}"
            app="${app// }"
            [[ -n "$app" ]] && installed_apps+=("$app")
        done < "$installed_apps_file"
    fi
    local has_app_filter=0
    if (( ${#installed_apps[@]} )); then
        has_app_filter=1
        echo -e "${BLUE}App coverage limited to installed set from ${installed_apps_file}.${NC}"
    fi
    local -a uv_cmd=(uv --preview-features extra-build-dependencies run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade)
    local extra_pythonpath="${repo_root}/src/agilab/core/agi-env/src:${repo_root}/src/agilab/core/agi-node/src:${repo_root}/src/agilab/core/agi-cluster/src"
    local repo_pythonpath="$repo_root"
    if [[ -n "$extra_pythonpath" ]]; then
        repo_pythonpath="${repo_pythonpath}:${extra_pythonpath}"
    fi

    if [[ -d "$repo_root/src/agilab/apps" ]]; then
        while IFS= read -r dir; do
            local app_dir
            local app_name
            app_dir="$(dirname "$dir")"
            app_name="$(basename "$app_dir")"
            local include_dir=1
            if (( has_app_filter )); then
                include_dir=0
                for selected_app in "${installed_apps[@]}"; do
                    if [[ "$selected_app" == "$app_name" ]]; then
                        include_dir=1
                        break
                    fi
                done
            fi
            if (( include_dir )); then
                app_test_dirs+=("$dir")
            else
                echo -e "${YELLOW}Skipping tests for '${app_name}' (not installed in this run).${NC}"
            fi
        done < <(find "$repo_root/src/agilab/apps" -mindepth 2 -maxdepth 2 -type d -name 'test' -not -path '*/.venv/*' 2>/dev/null)
    fi

    if (( ${#app_test_dirs[@]} )); then
        echo -e "${BLUE}Running builtin and repository app tests with coverage...${NC}"
        pushd "$repo_root" > /dev/null
        local -a cov_args=(--cov=src/agilab/apps --cov-report=term-missing --cov-report=xml --cov-append)
        if ! PYTHONPATH="${repo_pythonpath}:${PYTHONPATH:-}" "${uv_cmd[@]}" pytest "${app_test_dirs[@]}" --maxfail=1 "${cov_args[@]}"; then
            local rc=$?
            if (( rc == 5 )); then
                echo -e "${YELLOW}No tests collected for apps suite (exit code 5).${NC}"
            else
                echo -e "${RED}Coverage run failed for app tests (exit code $rc).${NC}"
                coverage_status=1
            fi
        fi
        popd > /dev/null
    else
        echo -e "${BLUE}No app test directories found under ${repo_root}/src/agilab/apps; skipping app coverage.${NC}"
    fi

    if [[ -d "$repo_root/src/agilab/apps-pages" ]]; then
        while IFS= read -r dir; do
            page_test_dirs+=("$dir")
        done < <(find "$repo_root/src/agilab/apps-pages" -mindepth 2 -maxdepth 2 -type d -name 'test' -not -path '*/.venv/*' 2>/dev/null)
    fi

    if (( ${#page_test_dirs[@]} )); then
        echo -e "${BLUE}Running apps-pages tests with coverage...${NC}"
        pushd "$repo_root" > /dev/null
        local -a cov_page_args=(--cov=src/agilab/apps-pages --cov-report=term-missing --cov-report=xml --cov-append)
        if ! PYTHONPATH="${repo_pythonpath}:${PYTHONPATH:-}" "${uv_cmd[@]}" pytest "${page_test_dirs[@]}" --maxfail=1 "${cov_page_args[@]}"; then
            local rc=$?
            if (( rc == 5 )); then
                echo -e "${YELLOW}No tests collected for apps-pages suite (exit code 5).${NC}"
            else
                echo -e "${RED}Coverage run failed for apps-pages tests (exit code $rc).${NC}"
                coverage_status=1
            fi
        fi
        popd > /dev/null
    else
        echo -e "${BLUE}No apps-pages test directories found; skipping apps-pages coverage.${NC}"
    fi

    return $coverage_status
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
  if [[ -n "$CUSTOM_INSTALL_APPS" ]]; then
    APPS_DEST_BASE="${agilab_public}/apps" \
    PAGES_DEST_BASE="${agilab_public}/apps-pages" \
    INSTALLED_APPS_FILE="${INSTALLED_APPS_FILE}" \
    BUILTIN_APPS="$CUSTOM_INSTALL_APPS" \
      ./install_apps.sh "${install_args[@]}"
  else
    APPS_DEST_BASE="${agilab_public}/apps" \
    PAGES_DEST_BASE="${agilab_public}/apps-pages" \
    INSTALLED_APPS_FILE="${INSTALLED_APPS_FILE}" \
      ./install_apps.sh "${install_args[@]}"
  fi
  popd > /dev/null
}

install_enduser() {
    local script_path="$AGI_INSTALL_PATH/tools/install_enduser.sh"
    if [[ ! -f "$script_path" ]]; then
        warn "tools/install_enduser.sh not found; skipping enduser packaging."
        return 0
    fi
    if [[ "$SOURCE" != "local" ]]; then
        warn "Source '$SOURCE' not supported by install_enduser.sh on this platform; skipping."
        return 0
    fi

    local run_choice="y"
    if (( NON_INTERACTIVE )); then
        if [[ "${SKIP_INSTALL_ENDUSER:-0}" -eq 1 ]]; then
            warn "Skipping enduser packaging (SKIP_INSTALL_ENDUSER=1 in non-interactive mode)."
            return 0
        fi
    else
        read -rp "Run enduser packaging step (may fetch Python dependencies)? (Y/n): " run_choice
    fi

    if [[ "$run_choice" =~ ^[Nn]$ ]]; then
        warn "Skipping enduser packaging at user request."
        return 0
    fi

    echo -e "${BLUE}Installing agilab (endusers)...${NC}"
    if (
        cd "$AGI_INSTALL_PATH/tools" >/dev/null 2>&1 \
        && ./install_enduser.sh --source "$SOURCE"
    ); then
        echo -e "${GREEN}agilab (enduser) installation complete.${NC}"
    else
        warn "install_enduser.sh failed; check tools/install_enduser.log for details."
    fi
}

install_pycharm_script() {
    rm -f .idea/workspace.xml
    echo -e "${BLUE}Patching PyCharm workspace.xml interpreter settings...${NC}"
    $UV run -p "$AGI_PYTHON_VERSION" python pycharm/setup_pycharm.py || warn "pycharm/install-apps-script.py failed or not found; continuing."
}

usage() {
  echo "Usage: $0 --cluster-ssh-credentials <user[:password]> --openai-api-key <api-key> [--agi-share-dir <path>] [--install-path <path> --apps-repository <path>] [--source local|pypi|testpypi] [--install-apps [app1,app2,...|all|builtin]] [--test-apps]"
    exit 1
}


# ================================
# Script Execution
# ================================

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --cluster-ssh-credentials) cluster_credentials="$2"; shift 2;;
        --openai-api-key)      openai_api_key="$2";      shift 2;;
        --agi-share-dir)       AGI_SHARE_DIR="$2"; shift 2;;
        --install-path)        AGI_INSTALL_PATH=$(realpath "$2"); shift 2;;
        --apps-repository)     APPS_REPOSITORY=$(realpath "$2"); shift 2;;
        --source)             SOURCE="$2"; shift 2;;
        --install-apps)
            INSTALL_APPS_FLAG=1
            if [[ -n "${2-}" && "${2}" != --* ]]; then
                CUSTOM_INSTALL_APPS="$2"
                if [[ -n "$CUSTOM_INSTALL_APPS" ]]; then
                    lower_val=$(printf '%s' "$CUSTOM_INSTALL_APPS" | tr '[:upper:]' '[:lower:]')
                    if [[ "$lower_val" == "all" ]]; then
                        CUSTOM_INSTALL_APPS="$INSTALL_ALL_SENTINEL"
                    elif [[ "$lower_val" == "builtin" || "$lower_val" == "built-in" ]]; then
                        CUSTOM_INSTALL_APPS="$INSTALL_BUILTIN_SENTINEL"
                    fi
                fi
                shift 2
            else
                shift
            fi
            ;;
        --install-apps=*)
            INSTALL_APPS_FLAG=1
            CUSTOM_INSTALL_APPS="${1#*=}"
            if [[ -n "$CUSTOM_INSTALL_APPS" ]]; then
                lower_val=$(printf '%s' "$CUSTOM_INSTALL_APPS" | tr '[:upper:]' '[:lower:]')
                if [[ "$lower_val" == "all" ]]; then
                    CUSTOM_INSTALL_APPS="$INSTALL_ALL_SENTINEL"
                elif [[ "$lower_val" == "builtin" || "$lower_val" == "built-in" ]]; then
                    CUSTOM_INSTALL_APPS="$INSTALL_BUILTIN_SENTINEL"
                fi
            fi
            shift
            ;;
        --test-apps)          TEST_APPS_FLAG=1; INSTALL_APPS_FLAG=1; shift;;
        --non-interactive|--yes|-y) NON_INTERACTIVE=1; shift;;
        *) echo -e "${RED}Unknown option: $1${NC}" && usage;;
    esac
done
export CLUSTER_CREDENTIALS
export APPS_REPOSITORY

# Confirm or override AGI_SHARE_DIR when interactive (relative paths are resolved under \$HOME)
if [[ -t 0 ]]; then
    read -rp "AGI_SHARE_DIR is '$AGI_SHARE_DIR' (relative paths resolve under \$HOME). Press Enter to accept or type a new path: " share_input
    if [[ -n "$share_input" ]]; then
        AGI_SHARE_DIR="$share_input"
    fi
fi

if [[ -t 0 ]]; then
    local_default="${AGI_LOCAL_DIR:-$DEFAULT_LOCAL_SHARE}"
    read -rp "AGI_LOCAL_DIR fallback is '${local_default}'. Press Enter to accept or type a new path: " local_input
    if [[ -n "$local_input" ]]; then
        AGI_LOCAL_DIR="$local_input"
        DEFAULT_LOCAL_SHARE="$local_input"
    else
        AGI_LOCAL_DIR="$local_default"
        DEFAULT_LOCAL_SHARE="$local_default"
    fi
fi

LOCAL_UNAME="$(id -un 2>/dev/null || whoami)"
SSH_USER="${cluster_credentials%%:*}"
AGI_CORE_DIST="$AGI_INSTALL_PATH/src/agilab/core/agi-core/dist"
set +e
AGI_CORE_WHL=$(ls -1t "$AGI_CORE_DIST"/agi_core*.whl 2>/dev/null | head -n 1)
set -e
if [[ -z "$AGI_CORE_WHL" ]]; then
    AGI_CORE_WHL="$AGI_CORE_DIST/agi_core-<version>.whl"
fi
if [[ -n "$SSH_USER" && "$SSH_USER" != "$LOCAL_UNAME" ]]; then
    echo -e "${RED}Refusing to continue:${NC} current user '$LOCAL_UNAME' differs from SSH user '$SSH_USER'."
    echo -e "Please login as '$SSH_USER' and rerun the install"
    exit 1
fi

check_internet
ensure_share_dir "$DEFAULT_SHARE_DIR" "$DEFAULT_LOCAL_SHARE"
set_locale
verify_share_dir
install_dependencies
choose_python_version
backup_existing_project
copy_project_files
update_environment
install_core

echo -e "${BLUE}Installing agilab (repo root)...${NC}"
pushd "$AGI_INSTALL_PATH" > /dev/null
$UV sync -p "$AGI_PYTHON_VERSION" --preview-features python-upgrade
$UV pip install -e src/agilab/core/agi-env
$UV pip install -e src/agilab/core/agi-node
$UV pip install -e src/agilab/core/agi-cluster
$UV pip install -e src/agilab/core/agi-core
popd > /dev/null

write_env_values
configure_streamlit

FINAL_STATUS=""
FINAL_OK=1
if (( INSTALL_APPS_FLAG )); then
  if ! install_apps; then
    warn "install_apps failed; continuing with PyCharm setup."
    install_pycharm_script # needed to investigate with pycharm why previous script has failed
    refresh_launch_matrix
    install_enduser
    FINAL_STATUS="Install completed with app installation errors; review the log."
    FINAL_OK=0
  else
    if ! run_repository_tests_with_coverage; then
      warn "Repository coverage run encountered issues; review the log output."
    fi
    install_pycharm_script
    refresh_launch_matrix
    install_enduser
    install_offline_extra
    seed_mistral_pdfs
    setup_mistral_offline
    FINAL_STATUS="Installation complete."
  fi
else
    warn "App installation skipped (use --install-apps to enable)."
    install_pycharm_script
    refresh_launch_matrix
    install_enduser
    install_offline_extra
    seed_mistral_pdfs
    setup_mistral_offline
    FINAL_STATUS="Installation complete (apps skipped)."
    FINAL_OK=1
fi

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
ELAPSED_MIN=$((ELAPSED / 60))
ELAPSED_SEC=$((ELAPSED % 60))
echo -e "${BLUE}Total install duration: ${ELAPSED_MIN}m ${ELAPSED_SEC}s${NC}"
if [[ -n "$FINAL_STATUS" ]]; then
    if (( FINAL_OK )); then
        echo -e "${GREEN}All done: ${FINAL_STATUS}${NC}"
    else
        echo -e "${YELLOW}Completed with issues: ${FINAL_STATUS}${NC}"
    fi
fi
