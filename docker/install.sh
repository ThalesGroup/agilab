#!/bin/bash
set -e
set -o pipefail

# ================================
# Docker-specific Installation Script
# This is a simplified version for containerized deployment
# ================================

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

UV="uv --preview-features extra-build-dependencies"

AGI_INSTALL_PATH="${AGI_INSTALL_PATH:-$(realpath '.')}"
CLUSTER_CREDENTIALS="${CLUSTER_CREDENTIALS:-}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
SOURCE="${SOURCE:-local}"
INSTALL_APPS_FLAG=0
TEST_APPS_FLAG=0
APPS_REPOSITORY="${APPS_REPOSITORY:-}"

warn() {
    echo -e "${YELLOW}Warning:${NC} $*"
}

install_python_version() {
    echo -e "${BLUE}Installing Python...${NC}"

    installed_pythons=$(uv python list --only-installed | cut -d' ' -f1)
    if ! echo "$installed_pythons" | grep -q "$AGI_PYTHON_VERSION"; then
        echo -e "${YELLOW}Installing $AGI_PYTHON_VERSION...${NC}"
        uv python install "$AGI_PYTHON_VERSION"
        echo -e "${GREEN}Python version ($AGI_PYTHON_VERSION) is now installed.${NC}"
    else
        echo -e "${GREEN}Python version ($AGI_PYTHON_VERSION) is already installed.${NC}"
    fi
}

update_environment() {
    ENV_FILE="$HOME/.local/share/agilab/.env"
    if [[ -f "$ENV_FILE" ]]; then
        rm "$ENV_FILE"
    fi
    mkdir -p "$(dirname "$ENV_FILE")"
    {
        echo "OPENAI_API_KEY=\"$OPENAI_API_KEY\""
        echo "CLUSTER_CREDENTIALS=\"$CLUSTER_CREDENTIALS\""
        echo "AGI_PYTHON_VERSION=\"$AGI_PYTHON_VERSION\""
        echo "AGI_PYTHON_FREE_THREADED=\"${AGI_PYTHON_FREE_THREADED:-0}\""
        echo "APPS_REPOSITORY=\"$APPS_REPOSITORY\""
        echo "OLLAMA_HOST=\"${OLLAMA_HOST:-http://localhost:11434}\""
    } > "$ENV_FILE"
    echo -e "${GREEN}Environment updated in $ENV_FILE${NC}"
}

write_env_values() {
    shared_env="$HOME/.local/share/agilab/.env"
    agilab_env="$HOME/.agilab/.env"

    [[ -f "$shared_env" ]] || { echo -e "${RED}Error: $shared_env does not exist.${NC}"; return 1; }

    mkdir -p "$(dirname "$agilab_env")"
    
    # Create .agilab/.env if it doesn't exist
    if [[ ! -f "$agilab_env" ]]; then
        touch "$agilab_env"
    fi

    sed_cmd() {
        sed -i "s|^$1=.*|$1=$2|" "$agilab_env"
    }

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
    
    if [[ ! -f "$framework_dir/install.sh" ]]; then
        echo -e "${RED}Error: $framework_dir/install.sh not found${NC}"
        return 1
    fi
    
    chmod +x "$framework_dir/install.sh"

    echo -e "${BLUE}Installing Framework...${NC}"
    pushd "$framework_dir" > /dev/null
    ./install.sh "$framework_dir"
    popd > /dev/null
}

install_apps() {
    dir="$AGI_INSTALL_PATH/src/agilab"
    
    if [[ ! -f "$dir/install_apps.sh" ]]; then
        echo -e "${YELLOW}Warning: $dir/install_apps.sh not found, skipping apps installation${NC}"
        return 0
    fi
    
    pushd "$dir" > /dev/null
    chmod +x "install_apps.sh"
    
    local agilab_public
    agilab_public="$(cat "$HOME/.local/share/agilab/.agilab-path")"
    
    local -a install_args=()
    if (( TEST_APPS_FLAG )); then
        install_args+=(--test-apps)
    fi
    
    APPS_DEST_BASE="${agilab_public}/apps" \
    PAGES_DEST_BASE="${agilab_public}/apps-pages" \
        ./install_apps.sh "${install_args[@]}"
    popd > /dev/null
}

usage() {
    echo "Usage: $0 --cluster-ssh-credentials <user[:password]> --openai-api-key <api-key> [--install-path <path>] [--source local|pypi|testpypi] [--install-apps] [--test-apps]"
    exit 1
}

# ================================
# Script Execution
# ================================

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --cluster-ssh-credentials) CLUSTER_CREDENTIALS="$2"; shift 2;;
        --openai-api-key)      OPENAI_API_KEY="$2";      shift 2;;
        --install-path)        AGI_INSTALL_PATH=$(realpath "$2"); shift 2;;
        --apps-repository)     APPS_REPOSITORY=$(realpath "$2"); shift 2;;
        --source)             SOURCE="$2"; shift 2;;
        --install-apps)       INSTALL_APPS_FLAG=1; shift;;
        --test-apps)          TEST_APPS_FLAG=1; INSTALL_APPS_FLAG=1; shift;;
        *) echo -e "${RED}Unknown option: $1${NC}" && usage;;
    esac
done

export APPS_REPOSITORY

# Validate required parameters
if [[ -z "$CLUSTER_CREDENTIALS" ]]; then
    warn "CLUSTER_CREDENTIALS not set, using default"
    CLUSTER_CREDENTIALS="user:password"
fi

if [[ -z "$OPENAI_API_KEY" ]]; then
    warn "OPENAI_API_KEY not set, using default"
    OPENAI_API_KEY="dummykey"
fi

# Main installation flow
echo -e "${BLUE}Starting AGILAB Docker installation...${NC}"
echo -e "${BLUE}Install path: $AGI_INSTALL_PATH${NC}"

install_python_version
update_environment
mkdir -p "$HOME/.local/share/agilab"
echo "$AGI_INSTALL_PATH" > "$HOME/.local/share/agilab/.agilab-path"
install_core
write_env_values

if (( INSTALL_APPS_FLAG )); then
    if ! install_apps; then
        warn "install_apps failed; continuing anyway."
    else
        echo -e "${GREEN}Apps installed successfully!${NC}"
    fi
else
    warn "App installation skipped (use --install-apps to enable)."
fi

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
ELAPSED_MIN=$((ELAPSED / 60))
ELAPSED_SEC=$((ELAPSED % 60))

echo -e "${GREEN}Installation complete!${NC}"
echo -e "${BLUE}Total install duration: ${ELAPSED_MIN}m ${ELAPSED_SEC}s${NC}"
echo -e "${YELLOW}Note: Offline LLM features are handled by the separate Ollama container${NC}"
