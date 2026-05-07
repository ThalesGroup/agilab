#!/bin/bash
set -e
set -o pipefail

LOG_DIR="$HOME/log/install_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install_$(date +%Y%m%d_%H%M%S).log"
exec 3>&1
exec > >(
    tee >(
        awk '
            BEGIN { blank = 1 }
            {
                line = $0
                sub(/\r$/, "", line)
                if (line ~ /^[[:space:]]*$/) {
                    if (!blank) {
                        print ""
                        fflush()
                    }
                    blank = 1
                    next
                }
                print $0
                fflush()
                blank = 0
            }
        ' >> "$LOG_FILE"
    ) >&3
) 2>&1

START_TIME=$(date +%s)

# Colors for output
RED='\033[1;31m'
GREEN='\033[1;32m'
BLUE='\033[1;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

export PATH="$HOME/.local/bin:$PATH"

UV="uv --preview-features extra-build-dependencies"

run_remote_shell_installer() {
    local url="$1"
    local label="$2"
    local interpreter="${3:-sh}"
    local safe_label
    safe_label="$(printf '%s' "$label" | tr -cs 'A-Za-z0-9_.-' '_' | sed 's/^_//;s/_$//')"
    local script_path
    script_path="$(mktemp "${TMPDIR:-/tmp}/agilab-${safe_label:-installer}.XXXXXX.sh")" || return 1

    echo -e "${BLUE}Downloading ${label} installer from ${url}...${NC}"
    if ! curl --proto '=https' --tlsv1.2 -fsSL "$url" -o "$script_path"; then
        rm -f "$script_path"
        return 1
    fi
    chmod 700 "$script_path"
    if ! "$interpreter" "$script_path"; then
        rm -f "$script_path"
        return 1
    fi
    rm -f "$script_path"
}

default_agi_share_user() {
    local raw_user="${AGILAB_SHARE_USER:-${USER:-}}"
    if [[ -z "$raw_user" ]]; then
        raw_user="$(id -un 2>/dev/null || whoami 2>/dev/null || true)"
    fi
    local safe_user
    safe_user="$(printf '%s' "$raw_user" | tr -cs 'A-Za-z0-9_.-' '_' | sed 's/^_//;s/_$//')"
    printf '%s\n' "${safe_user:-user}"
}

default_agi_share_dir() {
    printf 'clustershare/%s\n' "$(default_agi_share_user)"
}

AGI_INSTALL_PATH="$(realpath '.')"
# Default share dir (can be overridden via --agi-share-dir or env)
AGI_SHARE_DIR="${AGI_SHARE_DIR:-}"
CURRENT_PATH="$(realpath '.')"
CLUSTER_CREDENTIALS="${CLUSTER_CREDENTIALS:-}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
cluster_credentials="${CLUSTER_CREDENTIALS}"
openai_api_key="${OPENAI_API_KEY}"
SOURCE="local"
INSTALL_APPS_FLAG=0
TEST_APPS_FLAG=0
TEST_CORE_FLAG=0
TEST_ROOT_FLAG=0
APPS_REPOSITORY=""
CUSTOM_INSTALL_APPS=""
INSTALL_ALL_SENTINEL="__AGILAB_ALL_APPS__"
INSTALL_BUILTIN_SENTINEL="__AGILAB_BUILTIN_APPS__"
INSTALLED_APPS_FILE="${INSTALLED_APPS_FILE:-$HOME/.local/share/agilab/installed_apps.txt}"
NON_INTERACTIVE=0
SKIP_OFFLINE_RAW="${SKIP_OFFLINE:-0}"
SKIP_OFFLINE_NORMALIZED="$(printf '%s' "$SKIP_OFFLINE_RAW" | tr '[:upper:]' '[:lower:]')"
case "$SKIP_OFFLINE_NORMALIZED" in
    1|true|yes|on) SKIP_OFFLINE=1 ;;
    *) SKIP_OFFLINE=0 ;;
esac
INSTALL_LOCAL_MODELS="${INSTALL_LOCAL_MODELS:-}"
DRY_RUN=0
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

looks_ephemeral_validation_path() {
    local path="${1:-}"
    case "$path" in
        *"/agilab-release-check-"*|*"/agilab-fresh-install-"*|*"/agilab_source_validate_clean_"*) return 0 ;;
        *) return 1 ;;
    esac
}

guard_ephemeral_validation_env() {
    if [[ "${AGILAB_ALLOW_EPHEMERAL_ENV_WRITE:-0}" == "1" ]]; then
        return 0
    fi

    local suspect=""
    local candidate
    for candidate in "${AGI_INSTALL_PATH:-}" "${AGI_SHARE_DIR:-}" "${AGI_LOCAL_DIR:-}"; do
        if looks_ephemeral_validation_path "$candidate"; then
            suspect="$candidate"
            break
        fi
    done

    [[ -n "$suspect" ]] || return 0
    if looks_ephemeral_validation_path "$HOME"; then
        return 0
    fi

    echo -e "${RED}Refusing to persist ephemeral validation paths into the real user environment.${NC}"
    echo -e "${YELLOW}Detected path:${NC} $suspect"
    echo -e "${YELLOW}HOME:${NC} $HOME"
    echo "Run release/fresh-install validation with an isolated HOME under the validation root,"
    echo "or set AGILAB_ALLOW_EPHEMERAL_ENV_WRITE=1 if this is intentional."
    exit 1
}

USER_ENV_FILE="$HOME/.agilab/.env"
REPO_ENV_FILE="$AGI_INSTALL_PATH/.agilab/.env"
ENV_SHARE_USER="$(read_env_var "$USER_ENV_FILE" AGI_SHARE_DIR)"
ENV_SHARE_REPO="$(read_env_var "$REPO_ENV_FILE" AGI_SHARE_DIR)"
DEFAULT_SHARE_DIR="${AGI_SHARE_DIR:-${ENV_SHARE_USER:-$ENV_SHARE_REPO}}"
if [[ -z "$DEFAULT_SHARE_DIR" ]]; then
    DEFAULT_SHARE_DIR="$(default_agi_share_dir)"
fi
AGI_SHARE_DIR="${AGI_SHARE_DIR:-$DEFAULT_SHARE_DIR}"
AGI_LOCAL_DIR="${AGI_LOCAL_DIR:-${AGI_LOCAL_SHARE:-$HOME/localshare}}"
DEFAULT_LOCAL_SHARE="$AGI_LOCAL_DIR"

is_exported_nfs() {
    local path="$1"
    local canonical
    canonical=$(cd "$path" 2>/dev/null && pwd -P) || return 1

    if [ -f "/etc/exports" ]; then
        while read -r line; do
            [[ -z "$line" || "$line" =~ ^\# ]] && continue
            local export_dir=$(echo "$line" | awk '{print $1}')

            local canon_export_dir=$(cd "$export_dir" 2>/dev/null && pwd -P)
            [[ "$canonical" == "$canon_export_dir" ]] && return 0
        done < /etc/exports
    fi

    return 1
}

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
    local ensure_distinct_cluster_fallback
    ensure_distinct_cluster_fallback() {
        local requested_share="$1"
        local local_fallback="$2"
        local shadow_share="$requested_share"

        if [[ -z "$shadow_share" || "$shadow_share" == "$local_fallback" ]]; then
            shadow_share="$HOME/$(default_agi_share_dir)"
        fi

        if mkdir -p "$shadow_share" 2>/dev/null; then
            printf '%s\n' "$shadow_share"
            return 0
        fi

        shadow_share="$HOME/$(default_agi_share_dir)"
        mkdir -p "$shadow_share" || {
            echo -e "${RED}Failed to create fallback cluster share ${shadow_share}.${NC}"
            exit 1
        }
        printf '%s\n' "$shadow_share"
    }

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
    if is_exported_nfs "$share_dir" || share_is_mounted "$share_dir"; then
        export AGI_SHARE_DIR="$share_dir"
        export AGI_LOCAL_DIR="${AGI_LOCAL_DIR:-$fallback_dir}"
        return 0
    fi

    if (( NON_INTERACTIVE )); then
        if [[ -n "${CLUSTER_CREDENTIALS:-}" ]]; then
            echo -e "${RED}${share_dir} is not mounted. Cluster mode requires the shared path to be available; aborting (non-interactive).${NC}"
            exit 1
        fi
        local cluster_shadow
        cluster_shadow="$(ensure_distinct_cluster_fallback "$share_dir" "$fallback_dir")"
        echo -e "${YELLOW}AGI_SHARE_DIR ${share_dir} unavailable; non-interactive mode: using local fallback ${fallback_dir} and local cluster shadow ${cluster_shadow}.${NC}"
        mkdir -p "$fallback_dir" || { echo -e "${RED}Failed to create fallback ${fallback_dir}.${NC}"; exit 1; }
        export AGI_LOCAL_DIR="$fallback_dir"
        export AGI_SHARE_DIR="$cluster_shadow"
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
    echo -e "  1) Use local fallback at ${fallback_dir} and keep a distinct local cluster shadow"
    echo -e "  2) Wait for ${share_dir} to be mounted (mandatory for cluster installs; will timeout)"
    choice=""
    prompt_input "Enter 1 or 2 (default: 1): "
    case "$choice" in
        ""|1)
            local cluster_shadow
            cluster_shadow="$(ensure_distinct_cluster_fallback "$share_dir" "$fallback_dir")"
            mkdir -p "$fallback_dir" || { echo -e "${RED}Failed to create fallback ${fallback_dir}.${NC}"; exit 1; }
            export AGI_LOCAL_DIR="$fallback_dir"
            export AGI_SHARE_DIR="$cluster_shadow"
            echo -e "${GREEN}Using local fallback AGI_LOCAL_DIR=${AGI_LOCAL_DIR} with AGI_SHARE_DIR=${AGI_SHARE_DIR}.${NC}"
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
            local cluster_shadow
            cluster_shadow="$(ensure_distinct_cluster_fallback "$share_dir" "$fallback_dir")"
            mkdir -p "$fallback_dir" || { echo -e "${RED}Failed to create fallback ${fallback_dir}.${NC}"; exit 1; }
            export AGI_LOCAL_DIR="$fallback_dir"
            export AGI_SHARE_DIR="$cluster_shadow"
            ;;
    esac
}

warn() {
    echo -e "${YELLOW}Warning:${NC} $*"
}

normalize_local_model_name() {
    local raw="${1:-}"
    local normalized
    normalized="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
    case "$normalized" in
        "" ) return 1 ;;
        gpt-oss|gpt_oss|gptoss|gpt-oss:20b) echo "gpt-oss" ;;
        qwen|qwen2.5|qwen2.5-coder|qwen2.5-coder:latest) echo "qwen" ;;
        deepseek|deepseek-coder|deepseek-coder:latest) echo "deepseek" ;;
        qwen3|qwen3-30b|qwen3-30b-a3b|qwen3:30b-a3b|qwen3:30b-a3b-instruct|qwen3:30b-a3b-instruct-2507-q4_k_m) echo "qwen3" ;;
        qwen3-coder|qwen3-coder-30b|qwen3-coder-30b-a3b|qwen3-coder:30b|qwen3-coder:30b-a3b|qwen3-coder:30b-a3b-q4_k_m) echo "qwen3-coder" ;;
        ministral|ministral3|ministral-3|ministral-3-14b|ministral-3:14b|ministral-3:14b-instruct|ministral-3:14b-instruct-2512-q4_k_m) echo "ministral" ;;
        phi4-mini|phi-4-mini|phi4mini|phi4-mini:3.8b|phi4-mini:3.8b-q4_k_m) echo "phi4-mini" ;;
        * )
            warn "Ignoring unsupported local model '${raw}'. Supported values: gpt-oss, qwen, deepseek, qwen3, qwen3-coder, ministral, phi4-mini."
            return 1
            ;;
    esac
}

normalize_local_models_csv() {
    local raw="${1:-}"
    local -a ordered=()
    local seen=" "
    local item normalized
    raw="${raw//;/,}"
    for item in ${raw//,/ }; do
        normalized="$(normalize_local_model_name "$item")" || continue
        if [[ "$seen" != *" ${normalized} "* ]]; then
            ordered+=("$normalized")
            seen="${seen}${normalized} "
        fi
    done
    if (( ${#ordered[@]} == 0 )); then
        return 0
    fi
    printf '%s' "${ordered[*]}"
}

remove_local_model_from_list() {
    local requested="${1:-}"
    local model_to_remove="${2:-}"
    local -a filtered=()
    local model
    for model in $requested; do
        [[ "$model" == "$model_to_remove" ]] && continue
        filtered+=("$model")
    done
    if (( ${#filtered[@]} == 0 )); then
        return 0
    fi
    printf '%s' "${filtered[*]}"
}

ollama_tag_for_family() {
    local family="${1:-}"
    case "$family" in
        gpt-oss) echo "gpt-oss:20b" ;;
        qwen) echo "qwen2.5-coder:latest" ;;
        deepseek) echo "deepseek-coder:latest" ;;
        qwen3) echo "qwen3:30b-a3b-instruct-2507-q4_K_M" ;;
        qwen3-coder) echo "qwen3-coder:30b-a3b-q4_K_M" ;;
        ministral) echo "ministral-3:14b-instruct-2512-q4_K_M" ;;
        phi4-mini) echo "phi4-mini:3.8b-q4_K_M" ;;
        *)
            warn "No Ollama tag mapping defined for local model family '${family}'."
            return 1
            ;;
    esac
}

ensure_ollama_runtime() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if ! command -v ollama >/dev/null 2>&1; then
            if command -v brew >/dev/null 2>&1; then
                echo -e "${BLUE}Installing Ollama via Homebrew...${NC}"
                brew install --cask ollama || warn "Failed to install Ollama via Homebrew. Install it manually from https://ollama.com."
            else
                warn "Homebrew not found; install Ollama manually from https://ollama.com."
                return 1
            fi
        fi
        if command -v brew >/dev/null 2>&1; then
            brew services start ollama >/dev/null 2>&1 || true
        fi
    elif [[ "$OSTYPE" == "linux-gnu"* || "$OSTYPE" == "linux"* ]]; then
        if ! command -v ollama >/dev/null 2>&1; then
            echo -e "${BLUE}Installing Ollama (Linux)...${NC}"
            if run_remote_shell_installer "https://ollama.com/install.sh" "Ollama"; then
                echo -e "${GREEN}Ollama installed.${NC}"
            else
                warn "Failed to install Ollama via script. Install manually from https://ollama.com."
                return 1
            fi
        fi

        if command -v systemctl >/dev/null 2>&1; then
            sudo systemctl enable --now ollama >/dev/null 2>&1 || true
        fi
        if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
            nohup ollama serve > "$HOME/log/ollama_serve.log" 2>&1 &
            sleep 2
        fi
    else
        warn "Automatic Ollama setup is available for macOS and Linux. Install Ollama and pull the requested models manually."
        return 1
    fi

    if ! command -v ollama >/dev/null 2>&1; then
        warn "Ollama is not available after setup."
        return 1
    fi
    return 0
}

start_ollama_pull() {
    local tag="$1"
    local slug="$2"
    mkdir -p "$HOME/log"
    echo -e "${BLUE}Starting model download: ${tag} (running in background)...${NC}"
    nohup ollama pull "$tag" > "$HOME/log/ollama_pull_${slug}.log" 2>&1 &
    echo $! > "$HOME/log/ollama_pull_${slug}.pid"
    echo -e "${GREEN}Pull started. Monitor: tail -f $HOME/log/ollama_pull_${slug}.log${NC}"
}

setup_requested_local_models() {
    local requested="${1:-}"
    local label="${2:-requested local models}"
    local -a families=()
    local family tag

    [[ -n "$requested" ]] || return 0

    for family in $requested; do
        families+=("$family")
    done
    [[ ${#families[@]} -gt 0 ]] || return 0

    echo -e "${BLUE}Configuring ${label} via Ollama...${NC}"
    ensure_ollama_runtime || return 1

    for family in "${families[@]}"; do
        tag="$(ollama_tag_for_family "$family")" || continue
        start_ollama_pull "$tag" "$family"
    done
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
        echo -e "${BLUE}Installing offline assistant dependencies (GPT-OSS + Universal Offline AI Chatbot)...${NC}"
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

setup_default_offline_models() {
    echo -e "${BLUE}Configuring default local GPT-OSS model (Ollama)...${NC}"
    ensure_ollama_runtime || return 1
    if [[ "$OSTYPE" == "linux-gnu"* || "$OSTYPE" == "linux"* ]]; then
        start_ollama_pull "gpt-oss:20b" "gpt_oss"
    fi
}

seed_uoaic_pdfs() {
    echo -e "${BLUE}Seeding sample PDFs for Universal Offline AI Chatbot (optional)...${NC}"
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

restore_deleted_runconfig_assets() {
    local repo_root="$AGI_INSTALL_PATH"
    if ! git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        return 0
    fi

    local -a deleted_paths=()
    while IFS= read -r path; do
        [[ -n "$path" ]] && deleted_paths+=("$path")
    done < <(
        git -C "$repo_root" ls-files --deleted -- .idea/runConfigurations tools/run_configs 2>/dev/null
    )

    if (( ${#deleted_paths[@]} == 0 )); then
        return 0
    fi

    echo -e "${YELLOW}Restoring deleted tracked run-config assets...${NC}"
    if git -C "$repo_root" restore --source=HEAD -- "${deleted_paths[@]}"; then
        echo -e "${GREEN}Restored ${#deleted_paths[@]} run-config assets from Git.${NC}"
    else
        warn "Failed to restore deleted run-config assets; continuing without self-heal."
    fi
}

check_internet() {
    echo -e "${BLUE}Checking internet connectivity...${NC}"
    if curl -Is --connect-timeout 3 https://www.google.com &>/dev/null; then
        echo -e "${GREEN}Internet connection is OK.${NC}"
        AGI_INTERNET_ON=1
    else
        echo -e "${RED}No internet connection detected. Going into network restricted mode.${NC}"
        AGI_INTERNET_ON=0
    fi
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
    local share_dir="${AGI_SHARE_DIR:-$HOME/$(default_agi_share_dir)}"
    local local_dir="${AGI_LOCAL_DIR:-}"
    local home_prefix="$HOME/"
    [[ "$share_dir" == "~"* ]] && share_dir="${share_dir/#\~/$HOME}"

    # If we're intentionally using the local fallback, only require existence.
    if [[ -n "$local_dir" && "$share_dir" == "$local_dir" ]]; then
        if [[ -d "$share_dir" ]]; then
            return 0
        fi
        echo -e "${RED}Local AGI_SHARE_DIR missing:${NC} expected data dir at '$share_dir'."
        exit 1
    fi

    # Local-only installs may keep a distinct "cluster shadow" under $HOME so
    # worker environments can preserve AGI_CLUSTER_SHARE != AGI_LOCAL_SHARE
    # without requiring a mounted remote share.
    if [[ -z "${CLUSTER_CREDENTIALS:-}" && -n "$local_dir" && -d "$local_dir" && -d "$share_dir" ]]; then
        if [[ "$share_dir" == "$home_prefix"* ]]; then
            return 0
        fi
    fi

    # Otherwise require a mounted share.
    if is_exported_nfs "$share_dir" || share_is_mounted "$share_dir"; then
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
        run_remote_shell_installer "https://astral.sh/uv/install.sh" "uv"
        [[ -f "$HOME/.local/bin/env" ]] && source "$HOME/.local/bin/env"
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
        run_remote_shell_installer "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh" "Homebrew" "/bin/bash"
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
        echo "AGI_CLUSTER_SHARE=\"$AGI_SHARE_DIR\""
        echo "AGI_LOCAL_SHARE=\"$AGI_LOCAL_DIR\""
        echo "AGI_INTERNET_ON=\"$AGI_INTERNET_ON\""
        echo "IS_SOURCE_ENV=\"1\""
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

run_core_tests() {
    local repo_root="$AGI_INSTALL_PATH"
    local -a failures=()
    local -a uv_run=(uv --preview-features extra-build-dependencies run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade)

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}RUNNING CORE TEST SUITES${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    pushd "$repo_root" > /dev/null

    # Ensure the repo root virtual environment is populated before running pytest/coverage.
    # `uv run --no-sync` assumes dependencies are already installed.
    echo -e "${BLUE}Syncing repository environment for core tests...${NC}"
    $UV sync -p "$AGI_PYTHON_VERSION" --preview-features python-upgrade

    if ! "${uv_run[@]}" -m pytest src/agilab/core/agi-env/test --cov=src/agilab/core/agi-env/src/agi_env --cov-report=term-missing --cov-report=xml:coverage-agi-env.xml; then
        failures+=("agi-env tests")
    fi
    if ! "${uv_run[@]}" -m pytest src/agilab/core/test --cov=src/agilab/core --cov=src/agilab/core/agi-node/src/agi_node --cov=src/agilab/core/agi-cluster/src/agi_cluster --cov-report=term-missing --cov-report=xml:coverage-agi-core.xml; then
        failures+=("core tests")
    fi

    echo -e "${BLUE}Generating coverage reports...${NC}"
    COVERAGE_FILE=".coverage-agi-core" "${uv_run[@]}" -m coverage xml -i --include="src/agilab/core/agi-node/src/agi_node/*" -o coverage-agi-node.xml || true
    COVERAGE_FILE=".coverage-agi-core" "${uv_run[@]}" -m coverage xml -i --include="src/agilab/core/agi-cluster/src/agi_cluster/*" -o coverage-agi-cluster.xml || true

    popd > /dev/null

    if ((${#failures[@]})); then
        echo -e "${RED}Core test suites reported failures: ${failures[*]}. Aborting install.${NC}"
        exit 1
    fi
}

maybe_run_core_tests() {
    if (( TEST_CORE_FLAG )); then
        run_core_tests
    else
        echo -e "${BLUE}Skipping core test suites by default (use --test-core to enable).${NC}"
    fi
}

run_root_tests() {
    local repo_root="$AGI_INSTALL_PATH"

    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}RUNNING ROOT AGILAB TEST SUITE${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    pushd "$repo_root" > /dev/null
    if ! $UV run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade -m pytest src/agilab/test --cov=src/agilab --cov-report=term-missing --cov-report=xml:coverage-agilab.xml; then
        echo -e "${RED}Agilab unit tests failed. Aborting install.${NC}"
        popd > /dev/null
        exit 1
    fi
    popd > /dev/null
}

maybe_run_root_tests() {
    if (( TEST_ROOT_FLAG )); then
        run_root_tests
    else
        echo -e "${BLUE}Skipping root AGILAB test suite by default (use --test-root to enable).${NC}"
    fi
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

maybe_run_repository_tests_with_coverage() {
    if (( TEST_APPS_FLAG )); then
        run_repository_tests_with_coverage || warn "Repository coverage run encountered issues; review the log output."
    else
        echo -e "${BLUE}Skipping app/apps-pages repository coverage by default (use --test-apps to enable).${NC}"
    fi
}

install_apps() {
  dir="$AGI_INSTALL_PATH/src/agilab"
  local rc=0
  pushd "$dir" > /dev/null
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
    rc=$?
  else
    APPS_DEST_BASE="${agilab_public}/apps" \
    PAGES_DEST_BASE="${agilab_public}/apps-pages" \
    INSTALLED_APPS_FILE="${INSTALLED_APPS_FILE}" \
      ./install_apps.sh "${install_args[@]}"
    rc=$?
  fi
  popd > /dev/null
  return $rc
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
    local -a enduser_cmd=("./install_enduser.sh" "--source" "$SOURCE")
    if (( SKIP_OFFLINE )); then
        enduser_cmd+=("--skip-offline")
    fi
    if (
        cd "$AGI_INSTALL_PATH/tools" >/dev/null 2>&1 \
        && "${enduser_cmd[@]}"
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

resolve_cli_path_arg() {
    local raw="$1"
    case "$raw" in
        "~") printf '%s\n' "$HOME" ;;
        "~/"*) printf '%s/%s\n' "$HOME" "${raw#"~/"}" ;;
        /*) printf '%s\n' "$raw" ;;
        *) printf '%s/%s\n' "$(pwd -P)" "$raw" ;;
    esac
}

print_dry_run_plan() {
    local apps_plan
    if (( INSTALL_APPS_FLAG )); then
        apps_plan="${CUSTOM_INSTALL_APPS:-default apps selection}"
    else
        apps_plan="skipped"
    fi

    echo "AGILAB installer dry-run plan"
    echo "install_path: ${AGI_INSTALL_PATH}"
    echo "source: ${SOURCE}"
    echo "agi_share_dir: ${AGI_SHARE_DIR:-<default clustershare>}"
    echo "agi_local_dir: ${AGI_LOCAL_DIR:-${DEFAULT_LOCAL_SHARE:-<default localshare>}}"
    echo "apps_repository: ${APPS_REPOSITORY:-<not set>}"
    echo "install_apps: ${apps_plan}"
    echo "test_root: ${TEST_ROOT_FLAG}"
    echo "test_core: ${TEST_CORE_FLAG}"
    echo "test_apps: ${TEST_APPS_FLAG}"
    echo "skip_offline: ${SKIP_OFFLINE}"
    echo "local_models: ${INSTALL_LOCAL_MODELS:-<none>}"
    echo "non_interactive: ${NON_INTERACTIVE}"
    echo "steps_would_run:"
    echo "  - check internet and validation-environment guard"
    echo "  - prepare AGI share/local directories and write ~/.agilab/.env"
    echo "  - install system and Python dependencies required by selected profiles"
    echo "  - install AGILAB core packages and root package"
    echo "  - install selected apps and run requested tests"
    echo "  - configure PyCharm/launch matrix and optional end-user space"
    if (( ! SKIP_OFFLINE )); then
        echo "  - install offline assistant extras unless disabled"
    fi
    if [[ -n "$INSTALL_LOCAL_MODELS" ]]; then
        echo "  - install requested local Ollama model families"
    fi
}

usage() {
  echo "Usage: CLUSTER_CREDENTIALS=<user[:password]> OPENAI_API_KEY=<api-key> $0 [--agi-share-dir <path>] [--install-path <path> --apps-repository <path>] [--source local|pypi|testpypi] [--install-apps [app1,app2,...|all|builtin]] [--test-root] [--test-apps|--apps-test] [--test-core]"
  echo "       [--dry-run]       Print the install plan without changing environments or installing dependencies"
  echo "       [--skip-offline]  (or set SKIP_OFFLINE=1)"
  echo "       [--install-local-models gpt-oss,qwen,deepseek,qwen3,qwen3-coder,ministral,phi4-mini]"
    exit 1
}


# ================================
# Script Execution
# ================================

for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN=1
        break
    fi
done

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --agi-share-dir)       AGI_SHARE_DIR="$2"; shift 2;;
        --install-path)
            if (( DRY_RUN )); then
                AGI_INSTALL_PATH="$(resolve_cli_path_arg "$2")"
            else
                mkdir -p "$2"
                AGI_INSTALL_PATH=$(realpath "$2")
            fi
            shift 2
            ;;
        --apps-repository)
            if (( DRY_RUN )); then
                APPS_REPOSITORY="$(resolve_cli_path_arg "$2")"
            else
                APPS_REPOSITORY=$(realpath "$2")
            fi
            shift 2
            ;;
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
        --test-apps|--apps-test)
            TEST_APPS_FLAG=1
            INSTALL_APPS_FLAG=1
            shift
            ;;
        --test-root)
            TEST_ROOT_FLAG=1
            shift
            ;;
        --test-core)
            TEST_CORE_FLAG=1
            shift
            ;;
        --install-local-models)
            INSTALL_LOCAL_MODELS="$2"
            shift 2
            ;;
        --install-local-models=*)
            INSTALL_LOCAL_MODELS="${1#*=}"
            shift
            ;;
        --skip-offline)       SKIP_OFFLINE=1; shift;;
        --non-interactive|--yes|-y) NON_INTERACTIVE=1; shift;;
        --dry-run)            shift;;
        --help|-h) usage && exit;;
        *) echo -e "${RED}Unknown option: $1${NC}" && usage;;
    esac
done
INSTALL_LOCAL_MODELS="$(normalize_local_models_csv "$INSTALL_LOCAL_MODELS")"
export CLUSTER_CREDENTIALS
export APPS_REPOSITORY

if (( DRY_RUN )); then
    print_dry_run_plan
    exit 0
fi

# Confirm or override AGI_SHARE_DIR when interactive (relative paths are resolved under \$HOME)
if [[ -t 0 ]] && (( ! NON_INTERACTIVE )); then
    read -rp "AGI_SHARE_DIR is '$AGI_SHARE_DIR' (relative paths resolve under \$HOME). Press Enter to accept or type a new path: " share_input
    if [[ -n "$share_input" ]]; then
        AGI_SHARE_DIR="$share_input"
    fi
fi

if [[ -t 0 ]] && (( ! NON_INTERACTIVE )); then
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
#if [[ -n "$SSH_USER" && "$SSH_USER" != "$LOCAL_UNAME" ]]; then
#    echo -e "${RED}Refusing to continue:${NC} current user '$LOCAL_UNAME' differs from SSH user '$SSH_USER'."
#    echo -e "Please login as '$SSH_USER' and rerun the install"
#    exit 1
#fi

find . \( -name "uv.lock" -o -name "dist" -o -name "build" -o -name "*egg-info" \) -exec rm -rf {} +

check_internet
guard_ephemeral_validation_env
ensure_share_dir "$AGI_SHARE_DIR" "$AGI_LOCAL_DIR"
set_locale
verify_share_dir
install_dependencies
choose_python_version
backup_existing_project
copy_project_files
update_environment
write_env_values
install_core
maybe_run_core_tests

echo -e "${BLUE}Installing agilab (repo root)...${NC}"
pushd "$AGI_INSTALL_PATH" > /dev/null
$UV sync -p "$AGI_PYTHON_VERSION" --preview-features python-upgrade
$UV pip install -e src/agilab/core/agi-env
$UV pip install -e src/agilab/core/agi-node
$UV pip install -e src/agilab/core/agi-cluster
$UV pip install -e src/agilab/core/agi-core
$UV pip install -e .
popd > /dev/null

maybe_run_root_tests

configure_streamlit

FINAL_STATUS=""
FINAL_OK=1
run_extras=true
requested_local_models="$INSTALL_LOCAL_MODELS"

if (( INSTALL_APPS_FLAG )); then
  if ! install_apps; then
    warn "install_apps failed; continuing with PyCharm setup."
    FINAL_STATUS="Install completed with app installation errors; review the log."
    FINAL_OK=0
    run_extras=false
  else
    maybe_run_repository_tests_with_coverage
    FINAL_STATUS="Installation complete."
  fi
else
  warn "App installation skipped (use --install-apps to enable)."
  FINAL_STATUS="Installation complete (apps skipped)."
fi

restore_deleted_runconfig_assets
install_pycharm_script
refresh_launch_matrix
install_enduser

if $run_extras; then
  if (( SKIP_OFFLINE )); then
    echo -e "${BLUE}[info] Skipping offline assistant installation (--skip-offline flag set)${NC}"
  else
    install_offline_extra
    seed_uoaic_pdfs
    setup_default_offline_models
  fi
fi

if [[ -n "$requested_local_models" ]]; then
  setup_requested_local_models "$requested_local_models" "requested local models"
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

if (( TEST_APPS_FLAG )) && (( ! FINAL_OK )); then
    exit 1
fi
