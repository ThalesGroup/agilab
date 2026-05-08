"""Environment-file editor and runtime synchronization for the main page."""

from __future__ import annotations

import os
import importlib.resources as importlib_resources
import importlib.util
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
from agi_env.agi_logger import AgiLogger
from agi_env.credential_store_support import (
    CLUSTER_CREDENTIALS_KEY,
    KEYRING_SENTINEL,
    read_cluster_credentials,
    store_cluster_credentials,
)

_IMPORT_GUARD_PATH = Path(__file__).resolve().parents[1] / "import_guard.py"
_IMPORT_GUARD_SPEC = importlib.util.spec_from_file_location(
    "agilab_import_guard_env_editor",
    _IMPORT_GUARD_PATH,
)
if _IMPORT_GUARD_SPEC is None or _IMPORT_GUARD_SPEC.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_IMPORT_GUARD_PATH}")
_IMPORT_GUARD_MODULE = importlib.util.module_from_spec(_IMPORT_GUARD_SPEC)
_IMPORT_GUARD_SPEC.loader.exec_module(_IMPORT_GUARD_MODULE)
import_agilab_module = _IMPORT_GUARD_MODULE.import_agilab_module

_AGILAB_ROOT = Path(__file__).resolve().parents[1]
_env_file_utils_module = import_agilab_module(
    "agilab.env_file_utils",
    current_file=__file__,
    fallback_path=_AGILAB_ROOT / "env_file_utils.py",
    fallback_name="agilab_env_file_utils_env_editor_fallback",
)
_load_env_file_map = _env_file_utils_module.load_env_file_map

_logging_utils_module = import_agilab_module(
    "agilab.logging_utils",
    current_file=__file__,
    fallback_path=_AGILAB_ROOT / "logging_utils.py",
    fallback_name="agilab_logging_utils_env_editor_fallback",
)
LOG_DETAIL_LIMIT = _logging_utils_module.LOG_DETAIL_LIMIT
LOG_PATH_LIMIT = _logging_utils_module.LOG_PATH_LIMIT
bound_log_value = _logging_utils_module.bound_log_value


logger = AgiLogger.get_logger(__name__)
ENV_FILE_PATH = Path.home() / ".agilab/.env"
try:
    TEMPLATE_ENV_PATH = importlib_resources.files("agi_env") / "resources/.agilab/.env"
except (ModuleNotFoundError, FileNotFoundError, AttributeError, OSError):
    TEMPLATE_ENV_PATH = None


def _ensure_env_file(path: Path) -> Path:
    """Ensure the ~/.agilab/.env file exists without touching mtime on every rerun."""
    try:
        if path.exists():
            return path
    except OSError:
        return path

    parent = path.parent
    try:
        try:
            parent.mkdir(parents=True, exist_ok=False)
            logger.info("mkdir %s", bound_log_value(parent, LOG_PATH_LIMIT))
        except FileExistsError:
            pass
        if TEMPLATE_ENV_PATH is not None:
            try:
                template_text = TEMPLATE_ENV_PATH.read_text(encoding="utf-8")
                path.write_text(template_text, encoding="utf-8")
                return path
            except (OSError, UnicodeError):
                pass
        path.touch(exist_ok=True)
    except OSError as exc:
        logger.warning(
            "Unable to create env file at %s: %s",
            bound_log_value(path, LOG_PATH_LIMIT),
            bound_log_value(exc, LOG_DETAIL_LIMIT),
        )
    return path


def _resolve_share_dir_path(raw_value: str, *, home_path: Path) -> Path:
    """Return a normalized AGI share path or raise ``ValueError`` when invalid."""
    try:
        share_dir = Path(str(raw_value)).expanduser()
    except (TypeError, ValueError) as exc:
        raise ValueError("AGI_CLUSTER_SHARE is not a valid filesystem path.") from exc

    if not share_dir.is_absolute():
        share_dir = home_path.expanduser() / share_dir

    try:
        return share_dir.resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise ValueError(f"AGI_CLUSTER_SHARE cannot be resolved: {exc}") from exc


def _refresh_share_dir(env: Any, new_value: str) -> None:
    """Update the in-memory AgiEnv share-path attributes after a UI change."""
    if not new_value:
        return

    share_value = str(new_value)
    try:
        share_dir = _resolve_share_dir_path(share_value, home_path=Path(env.home_abs))
    except ValueError as exc:
        st.warning(str(exc))
        return

    # Persist the raw value so workers can resolve relative mounts appropriately.
    env.agi_share_path = share_value
    env._share_root_cache = share_dir
    env.agi_share_path_abs = share_dir
    share_target = env.share_target_name
    env.app_data_rel = share_dir / share_target
    env.dataframe_path = env.app_data_rel / "dataframe"
    try:
        env.data_root = env.ensure_data_root()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        st.warning(f"AGI_CLUSTER_SHARE update saved but data directory is still unreachable: {exc}")


def _handle_data_root_failure(exc: Exception, *, agi_env_cls: Any) -> bool:
    """Render a recovery UI when the AGI share directory is unavailable."""
    message = str(exc)
    if "AGI_CLUSTER_SHARE" not in message and "data directory" not in message:
        return False

    agi_env_cls._ensure_defaults()
    current_value = (
        st.session_state.get("agi_share_path_override_input")
        or agi_env_cls.envars.get("AGI_CLUSTER_SHARE")
        or os.environ.get("AGI_CLUSTER_SHARE")
        or agi_env_cls.envars.get("AGI_LOCAL_SHARE")
        or ""
    )
    share_dir_path = Path(str(current_value)).expanduser()

    st.error(
        "AGILAB cannot reach the configured AGI share directory. "
        "Mount the expected path or override `AGI_CLUSTER_SHARE` before continuing."
    )
    st.code(message)
    st.info(
        f"The value is persisted in `{ENV_FILE_PATH}` so CLI and Streamlit stay in sync. "
        "Point it to a mounted folder (local path or NFS mount) that AGILAB can create files in."
    )
    st.write(f"Current setting: `{current_value}` (expands to `{share_dir_path}`)")

    key = "agi_share_path_override_input"
    if key not in st.session_state or not st.session_state[key]:
        st.session_state[key] = str(current_value)

    with st.form("agi_share_path_override_form"):
        st.text_input("New AGI_CLUSTER_SHARE", key=key, help="Provide an absolute or home-relative path")
        submitted = st.form_submit_button("Save and retry", width="stretch")

    if submitted:
        new_value = (st.session_state.get(key) or "").strip()
        if not new_value:
            st.warning("AGI_CLUSTER_SHARE cannot be empty.")
        else:
            try:
                _resolve_share_dir_path(new_value, home_path=Path(agi_env_cls.home_abs))
            except ValueError as share_exc:
                st.warning(str(share_exc))
                return True
            agi_env_cls.set_env_var("AGI_CLUSTER_SHARE", new_value)
            st.success(f"Saved AGI_CLUSTER_SHARE = {new_value}. Reloading...")
            st.session_state["first_run"] = True
            st.rerun()
    return True


def _strip_dotenv_quotes(value: str) -> str:
    """Remove surrounding quotes from a .env value, matching python-dotenv behaviour."""
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        return v[1:-1]
    return v


def _read_env_file(path: Path) -> List[Dict[str, str]]:
    path = _ensure_env_file(path)
    entries: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle.readlines():
            raw = raw_line.rstrip("\n")
            stripped = raw.strip()
            if not stripped:
                entries.append({"type": "comment", "raw": raw})
                continue

            # Treat commented KEY=VAL lines as entries so they can be edited/uncommented.
            target = stripped.lstrip("#").strip()
            if "=" in target:
                key, value = target.split("=", 1)
                entries.append(
                    {
                        "type": "entry",
                        "key": key.strip(),
                        "value": _strip_dotenv_quotes(value),
                        "raw": raw,
                        "commented": stripped.startswith("#"),
                    }
                )
            else:
                entries.append({"type": "comment", "raw": raw})
    return entries


def _is_worker_python_override_key(key: str) -> bool:
    """Return True for host-specific worker Python version keys."""
    normalized = str(key).strip()
    return normalized.endswith("_PYTHON_VERSION") and normalized != "AGI_PYTHON_VERSION"


def _worker_python_override_host(key: str) -> str:
    """Return the host portion of ``<worker-host>_PYTHON_VERSION``."""
    normalized = str(key).strip()
    if not _is_worker_python_override_key(normalized):
        return ""
    return normalized[: -len("_PYTHON_VERSION")]


def _env_editor_field_label(key: str) -> str:
    """Return a human-readable label for environment-variable fields."""
    normalized = str(key).strip()
    if normalized == "AGI_PYTHON_VERSION":
        return "Default Python version"
    if normalized == "AGI_PYTHON_FREE_THREADED":
        return "Use free-threaded Python"
    if _is_worker_python_override_key(normalized):
        host = _worker_python_override_host(normalized)
        return f"Worker Python version for {host}" if host else "Worker Python version"
    return normalized


def _visible_env_editor_keys(
    template_keys: List[str],
    existing_entries: List[Dict[str, str]],
) -> List[str]:
    """Return env-editor keys in template order plus worker Python overrides."""
    ordered_keys: List[str] = list(template_keys)
    seen = set(ordered_keys)
    for entry in existing_entries:
        if entry.get("type") != "entry":
            continue
        key = str(entry.get("key", "")).strip()
        if not key or key in seen:
            continue
        if _is_worker_python_override_key(key):
            ordered_keys.append(key)
            seen.add(key)
    if ordered_keys:
        return ordered_keys
    return list(dict.fromkeys(str(entry["key"]).strip() for entry in existing_entries if entry.get("type") == "entry"))


def _write_env_file(
    path: Path,
    entries: List[Dict[str, str]],
    updates: Dict[str, str],
    new_entry: Dict[str, str] | None,
) -> None:
    """Write the .env file, consolidating duplicate keys (last value wins)."""
    path = _ensure_env_file(path)
    lines: List[str] = []
    emitted_keys: set[str] = set()

    file_values: Dict[str, str] = {}
    for entry in entries:
        if entry["type"] == "entry":
            file_values[entry["key"]] = entry["value"]
    final_values: Dict[str, str] = {**file_values, **updates}

    for entry in entries:
        if entry["type"] != "entry":
            lines.append(entry["raw"])
            continue
        key = entry["key"]
        if key in emitted_keys:
            continue
        emitted_keys.add(key)
        value = final_values.get(key, entry["value"])
        lines.append(f"{key}={value}")

    for key, value in updates.items():
        if key not in emitted_keys:
            lines.append(f"{key}={value}")
            emitted_keys.add(key)

    if new_entry and new_entry.get("key") and new_entry["key"] not in emitted_keys:
        lines.append(f"{new_entry['key']}={new_entry['value']}")

    content = "\n".join(lines).rstrip() + "\n"
    path.write_text(content, encoding="utf-8")


def _upsert_env_var(path: Path, key: str, value: str) -> None:
    """Update or append a single KEY=VALUE in the .env file."""
    path = _ensure_env_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    rewritten: List[str] = []
    key_eq = f"{key}="
    updated = False
    for raw in lines:
        stripped = raw.strip()
        target = stripped.lstrip("#").strip()
        if target.startswith(key_eq):
            rewritten.append(f"{key}={value}")
            updated = True
        else:
            rewritten.append(raw)
    if not updated:
        rewritten.append(f"{key}={value}")
    path.write_text("\n".join(rewritten).rstrip() + "\n", encoding="utf-8")


def _refresh_env_from_file(env: Any) -> None:
    """Re-load ~/.agilab/.env into env.envars and os.environ when it changes."""
    try:
        current_mtime = ENV_FILE_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return

    last_mtime = st.session_state.get("env_file_mtime_ns")
    if last_mtime is not None and last_mtime == current_mtime:
        return

    env_map = _load_env_file_map(ENV_FILE_PATH)
    if not env_map:
        st.session_state["env_file_mtime_ns"] = current_mtime
        return

    for key, val in env_map.items():
        resolved_value = val
        if key == CLUSTER_CREDENTIALS_KEY:
            resolved_value = read_cluster_credentials(
                val,
                environ=os.environ,
                logger=logger,
            )
        os.environ[key] = resolved_value
        try:
            if env.envars is not None:
                env.envars[key] = resolved_value
        except (AttributeError, TypeError):
            pass

    new_apps_path = env_map.get("APPS_PATH", "").strip()
    if new_apps_path and str(getattr(env, "apps_path", "")) != new_apps_path:
        try:
            resolved = Path(new_apps_path).expanduser().resolve()
            env.apps_path = resolved
        except (OSError, RuntimeError, TypeError, ValueError):
            pass

    st.session_state["env_file_mtime_ns"] = current_mtime


def _render_env_editor(env: Any, help_file: Path | None = None) -> None:
    del help_file
    feedback = st.session_state.pop("env_editor_feedback", None)
    if feedback:
        st.success(feedback)

    st.session_state.setdefault("env_editor_new_key", "")
    st.session_state.setdefault("env_editor_new_value", "")

    entries = _read_env_file(ENV_FILE_PATH)
    existing_entries = [entry for entry in entries if entry["type"] == "entry"]

    last_value_map: Dict[str, str] = {}
    commented_default_map: Dict[str, str] = {}
    for entry in existing_entries:
        key = entry["key"]
        value = entry["value"].strip()
        if entry.get("commented"):
            commented_default_map[key] = value
            continue
        last_value_map[key] = value
    existing_values = dict(last_value_map)

    template_keys: List[str] = []
    template_defaults: Dict[str, str] = {}
    if TEMPLATE_ENV_PATH is not None:
        try:
            with TEMPLATE_ENV_PATH.open("r", encoding="utf-8") as template_file:
                for raw in template_file.readlines():
                    stripped = raw.strip()
                    if not stripped or "=" not in stripped:
                        continue
                    key_part, value_part = stripped.lstrip("#").split("=", 1)
                    key = key_part.strip()
                    value = value_part.strip()
                    if key and key not in template_keys:
                        template_keys.append(key)
                    if key and key not in template_defaults:
                        template_defaults[key] = value
        except (OSError, UnicodeError):
            pass

    unique_keys = _visible_env_editor_keys(template_keys, existing_entries)

    st.caption(
        "`AGI_PYTHON_VERSION` sets the default Python version. "
        "Workers can override it with `<worker-host>_PYTHON_VERSION`, "
        "for example `127.0.0.1_PYTHON_VERSION=3.13`."
    )

    with st.form("env_editor_form"):
        for key in unique_keys:
            default_value = last_value_map.get(key, template_defaults.get(key, ""))
            if key == CLUSTER_CREDENTIALS_KEY and key not in last_value_map:
                default_value = ""
            if key == CLUSTER_CREDENTIALS_KEY and default_value == KEYRING_SENTINEL:
                default_value = (
                    str(getattr(env, "CLUSTER_CREDENTIALS", "") or "")
                    or str(getattr(env, "envars", {}).get(CLUSTER_CREDENTIALS_KEY, "") or "")
                )
            st.text_input(
                _env_editor_field_label(key),
                value=default_value,
                key=f"env_editor_val_{key}",
                help=f"Set value for {key}",
            )

        st.markdown("#### Add a new variable")
        new_key = st.text_input("Variable name", key="env_editor_new_key", placeholder="MY_SETTING")
        new_value = st.text_input("Variable value", key="env_editor_new_value", placeholder="value")

        submitted = st.form_submit_button("Save .env", type="primary")

    if submitted:
        cleaned_updates: Dict[str, str] = {}
        for key in unique_keys:
            submitted_value = st.session_state.get(f"env_editor_val_{key}", "").strip()
            untouched_template_default = commented_default_map.get(key, template_defaults.get(key, ""))
            if key not in last_value_map and submitted_value == untouched_template_default:
                continue
            cleaned_updates[key] = submitted_value

        new_entry_data = None
        new_key_clean = new_key.strip()
        if new_key_clean:
            new_value_clean = new_value.strip()
            if new_key_clean in cleaned_updates:
                cleaned_updates[new_key_clean] = new_value_clean
            else:
                new_entry_data = {"key": new_key_clean, "value": new_value_clean}

        try:
            runtime_updates = dict(cleaned_updates)
            env_file_updates = dict(cleaned_updates)
            env_file_new_entry = dict(new_entry_data) if new_entry_data else None
            if CLUSTER_CREDENTIALS_KEY in runtime_updates:
                cluster_secret = runtime_updates[CLUSTER_CREDENTIALS_KEY]
                if store_cluster_credentials(cluster_secret, environ=os.environ, logger=logger):
                    env_file_updates[CLUSTER_CREDENTIALS_KEY] = KEYRING_SENTINEL

            if (
                env_file_new_entry
                and env_file_new_entry.get("key") == CLUSTER_CREDENTIALS_KEY
                and env_file_new_entry.get("value")
            ):
                if store_cluster_credentials(env_file_new_entry["value"], environ=os.environ, logger=logger):
                    env_file_new_entry["value"] = KEYRING_SENTINEL

            _write_env_file(ENV_FILE_PATH, entries, env_file_updates, env_file_new_entry)
            combined_updates = dict(runtime_updates)
            if new_entry_data:
                combined_updates[new_entry_data["key"]] = new_entry_data["value"]

            for key, value in combined_updates.items():
                os.environ[key] = value
                if hasattr(env, "envars") and isinstance(env.envars, dict):
                    env.envars[key] = value
            if CLUSTER_CREDENTIALS_KEY in combined_updates:
                env.CLUSTER_CREDENTIALS = combined_updates[CLUSTER_CREDENTIALS_KEY]

            new_share = combined_updates.get("AGI_CLUSTER_SHARE")
            if new_share is not None and new_share.strip() and new_share.strip() != existing_values.get("AGI_CLUSTER_SHARE"):
                _refresh_share_dir(env, new_share.strip())

            st.session_state["env_editor_feedback"] = "Environment variables updated."
            st.session_state["env_editor_reset"] = True
            st.rerun()
        except (OSError, RuntimeError, TypeError, UnicodeError, ValueError) as exc:
            st.error(f"Failed to save .env file: {exc}")

    st.divider()
    st.markdown("#### .env contents (template order; all variables)")
    try:
        if TEMPLATE_ENV_PATH is None:
            raise FileNotFoundError("AgiEnv template .env not found in package resources.")

        template_keys = []
        with TEMPLATE_ENV_PATH.open("r", encoding="utf-8") as template_file:
            for raw in template_file.readlines():
                stripped = raw.strip()
                if not stripped or "=" not in stripped:
                    continue
                key = stripped.lstrip("#").split("=", 1)[0].strip()
                if key:
                    template_keys.append(key)

        env_lines = ENV_FILE_PATH.read_text(encoding="utf-8").splitlines()
        current: Dict[str, str] = {}
        for raw in env_lines:
            stripped = raw.strip()
            if not stripped or "=" not in stripped:
                continue
            normalized = stripped.lstrip("#").strip()
            if "=" not in normalized:
                continue
            key, val = normalized.split("=", 1)
            current[key.strip()] = _strip_dotenv_quotes(val)

        merged = []
        for key in template_keys:
            value = current.get(key, "")
            if key == CLUSTER_CREDENTIALS_KEY and value == KEYRING_SENTINEL:
                value = "<stored in keyring>"
            merged.append(f"{key}={value}")
        for key in sorted(current.keys()):
            if key in template_keys:
                continue
            if key == CLUSTER_CREDENTIALS_KEY and current.get(key) == KEYRING_SENTINEL:
                merged.append(f"{key}=<stored in keyring>")
            else:
                merged.append(f"{key}={current[key]}")
        if merged:
            st.code("\n".join(merged))
        else:
            st.caption("No environment variables found in the current .env.")
    except FileNotFoundError:
        st.caption(f"Template or current .env file not found (template: {TEMPLATE_ENV_PATH}, current: {ENV_FILE_PATH}).")
    except (OSError, UnicodeError) as exc:
        st.error(f"Unable to read env files: {exc}")
