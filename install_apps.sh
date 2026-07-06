#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./install_apps.sh [--apps-repository <path>] [--install-apps [app1,app2,...|all|builtin]] [--test-apps]

Installs apps/pages by delegating to the active source checkout's existing
src/agilab/install_apps.sh script.

Options:
  --apps-repository <path>   External apps repository root containing apps/ and/or apps-pages/.
  --install-apps [value]     Same selection shape as install.sh:
                               all      install all discoverable apps
                               builtin  install only bundled public apps
                               name,... install the named apps
                             Omit the value to use the existing picker/default selection.
  --test-apps, --apps-test   Run app tests after install.
  --active-checkout <path>   Override the source path normally read from
                             ~/.local/share/agilab/.agilab-path.
  --help, -h                 Show this help.

Examples:
  ./install_apps.sh --apps-repository /path/to/apps-repo --install-apps all
  ./install_apps.sh --apps-repository /path/to/apps-repo --install-apps app_a_project,app_b_project
  ./install_apps.sh --install-apps builtin --test-apps
EOF
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
active_source="${AGILAB_SRC:-}"
apps_repository="${APPS_REPOSITORY:-}"
install_apps_value=""
install_apps_value_set=0
declare -a forwarded_args=()
forwarded_args_count=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apps-repository)
      if [[ $# -lt 2 || "$2" == --* ]]; then
        echo "Error: --apps-repository requires a path." >&2
        usage >&2
        exit 2
      fi
      apps_repository="$2"
      shift 2
      ;;
    --apps-repository=*)
      apps_repository="${1#--apps-repository=}"
      shift
      ;;
    --install-apps)
      install_apps_value_set=1
      if [[ $# -ge 2 && "$2" != --* ]]; then
        install_apps_value="$2"
        shift 2
      else
        install_apps_value=""
        shift
      fi
      ;;
    --install-apps=*)
      install_apps_value_set=1
      install_apps_value="${1#--install-apps=}"
      shift
      ;;
    --test-apps|--apps-test|--link-compatible-venvs|--no-link-compatible-venvs)
      forwarded_args[$forwarded_args_count]="$1"
      forwarded_args_count=$((forwarded_args_count + 1))
      shift
      ;;
    --active-checkout)
      if [[ $# -lt 2 || "$2" == --* ]]; then
        echo "Error: --active-checkout requires a path." >&2
        usage >&2
        exit 2
      fi
      active_source="$2"
      shift 2
      ;;
    --active-checkout=*)
      active_source="${1#--active-checkout=}"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown option '$1'." >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$active_source" ]]; then
  active_path_file="$HOME/.local/share/agilab/.agilab-path"
  if [[ -f "$active_path_file" ]]; then
    active_source="$(cat "$active_path_file")"
  elif [[ -x "$script_dir/src/agilab/install_apps.sh" ]]; then
    active_source="$script_dir/src/agilab"
  else
    echo "Error: active AGILAB source path is unknown." >&2
    echo "Run the root installer first or pass --active-checkout <path>." >&2
    exit 1
  fi
fi

active_source="${active_source%/}"
installer="$active_source/install_apps.sh"
if [[ ! -x "$installer" ]]; then
  echo "Error: install_apps.sh not found or not executable at: $installer" >&2
  exit 1
fi

if [[ -n "$apps_repository" ]]; then
  if [[ ! -d "$apps_repository" ]]; then
    echo "Error: --apps-repository is not a directory: $apps_repository" >&2
    exit 1
  fi
  if [[ ! -d "$apps_repository/apps" && ! -d "$apps_repository/apps-pages" ]]; then
    echo "Error: apps repository must contain apps/ and/or apps-pages/: $apps_repository" >&2
    exit 1
  fi
fi

case "$install_apps_value" in
  all)
    install_apps_value="__AGILAB_ALL_APPS__"
    ;;
  builtin)
    install_apps_value="__AGILAB_BUILTIN_APPS__"
    ;;
esac

echo "Active AGILAB source: $active_source"
if [[ -n "$apps_repository" ]]; then
  echo "Apps repository: $apps_repository"
fi

export APPS_REPOSITORY="$apps_repository"
export AGILAB_DEV_APPS_REPOSITORY="${AGILAB_DEV_APPS_REPOSITORY:-1}"
if (( install_apps_value_set )) && [[ -n "$install_apps_value" ]]; then
  export BUILTIN_APPS="$install_apps_value"
fi

cd "$active_source"
if [[ "$forwarded_args_count" -gt 0 ]]; then
  exec ./install_apps.sh "${forwarded_args[@]}"
fi
exec ./install_apps.sh
