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

# Remove unwanted files/directories
find . \( -name ".venv" -o -name "uv.lock" -o -name "build" -o -name "dist" -o -name "*egg-info" \) -exec rm -rf {} +

install_python_version() {
    echo -e "${BLUE}Installing Python...${NC}"

    installed_pythons=$(uv python list --only-installed | cut -d' ' -f1)
    if ! echo "$installed_pythons" | grep -q "$PYTHON_VERSION"; then
        echo -e "${YELLOW}Installing $PYTHON_VERSION...${NC}"
        uv python install "$PYTHON_VERSION"

        echo -e "${GREEN}Python version ($PYTHON_VERSION) is now installed.${NC}"
    else
        echo -e "${GREEN}Python version ($PYTHON_VERSION) is already installed.${NC}"
    fi
}

update_environment() {
    ENV_FILE="$HOME/.local/share/agilab/.env"
    if [[ -f "$ENV_FILE" ]]; then
        rm "$ENV_FILE"
    fi
    mkdir -p "$(dirname "$ENV_FILE")"
    {
        echo "OPENAI_API_KEY=\"$openai_api_key\""
        echo "CLUSTER_CREDENTIALS=\"$cluster_credentials\""
        echo "AGI_PYTHON_VERSION=\"$PYTHON_VERSION\""
    } > "$ENV_FILE"
    echo -e "${GREEN}Environment updated in $ENV_FILE${NC}"
}

install_framework_apps() {
    framework_dir="/app/src/agilab"
    apps_dir="/app/src/agilab/apps"

    chmod +x "$framework_dir/install.sh" "$apps_dir/install.sh"

    echo -e "${BLUE}Installing Framework...${NC}"
    pushd "$framework_dir" > /dev/null
    ./install.sh "$framework_dir"
    popd > /dev/null

    echo -e "${BLUE}Installing Apps...${NC}"
    pushd "$apps_dir" > /dev/null
    ./install.sh "$apps_dir" "1"
    popd > /dev/null
}

write_env_values() {
  shared_env="$HOME/.local/share/agilab/.env"
  agilab_env="$HOME/.agilab/.env"

  if [[ ! -f "$shared_env" ]]; then
    echo -e "${RED}Error: $shared_env does not exist.${NC}"
    return 1
  fi

  sed_cmd() {
    sed -i "s|^$1=.*|$1=$2|" "$agilab_env"
  }

  while IFS='=' read -r key value || [[ -n "$key" ]]; do
    # Skip empty lines and comments
    [[ -z "$key" || "$key" =~ ^# ]] && continue

    # Check if the key exists in the agilab_env file
    if grep -q "^$key=" "$agilab_env"; then
      # If the value is different, update it
      current_value=$(grep "^$key=" "$agilab_env" | cut -d '=' -f2-)
      if [[ "$current_value" != "$value" ]]; then
        sed_cmd "$key" "$value"
      fi
    else
      # Append the new key-value pair
      echo "$key=$value" >> "$agilab_env"
    fi
  done < "$shared_env"

  echo -e "${GREEN}.env file updated.${NC}"
}


# ================================
# Script Execution
# ================================
install_python_version
update_environment
mkdir -p "$HOME/.local/share/agilab"
echo "/app/src/agi" > "$HOME/.local/share/agilab/.agilab-path"
install_framework_apps
write_env_values

echo -e "${GREEN}Installation complete!${NC}"
