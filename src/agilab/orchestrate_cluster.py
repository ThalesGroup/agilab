import ipaddress
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import streamlit as st

from .cluster_lan_discovery import DiscoveryOptions, discover_lan_nodes

RUN_MODE_LABELS: tuple[str, ...] = (
    "0: python",
    "1: pool of process",
    "2: cython",
    "3: pool and cython",
    "4: dask",
    "5: dask and pool",
    "6: dask and cython",
    "7: dask and pool and cython",
    "8: rapids",
    "9: rapids and pool",
    "10: rapids and cython",
    "11: rapids and pool and cython",
    "12: rapids and dask",
    "13: rapids and dask and pool",
    "14: rapids and dask and cython",
    "15: rapids and dask and pool and cython",
)
LAN_DISCOVERY_CACHE = Path(".agilab") / "lan_nodes.json"
LAN_READY_STATUSES = {"ready"}
LAN_CONFIGURED_WORKER_SOURCES = {"ssh-config"}
LAN_WORKER_CANDIDATE_STATUSES = {
    "ready",
    "reverse-ssh-needed",
    "sshfs-missing",
    "uv-missing",
    "python-missing",
    "ssh-auth-needed",
}


@dataclass(frozen=True)
class OrchestrateClusterDeps:
    parse_and_validate_scheduler: Callable[[str], Optional[str]]
    parse_and_validate_workers: Callable[[str], Optional[dict[str, int]]]
    write_app_settings_toml: Callable[[Path, dict], dict]
    clear_load_toml_cache: Callable[[], None]
    set_env_var: Callable[[str, str], None]
    agi_env_envars: dict[str, Any] | None


def compute_cluster_mode(cluster_params: dict[str, Any], cluster_enabled: bool) -> int:
    return (
        int(cluster_params.get("pool", False))
        + int(cluster_params.get("cython", False)) * 2
        + int(cluster_enabled) * 4
        + int(cluster_params.get("rapids", False)) * 8
    )


def cluster_widget_keys(app_state_name: str) -> dict[str, str]:
    return {
        "cython": f"cluster_cython__{app_state_name}",
        "pool": f"cluster_pool__{app_state_name}",
        "rapids": f"cluster_rapids__{app_state_name}",
        "cluster_enabled": f"cluster_enabled__{app_state_name}",
        "scheduler": f"cluster_scheduler__{app_state_name}",
        "user": f"cluster_user__{app_state_name}",
        "use_key": f"cluster_use_key__{app_state_name}",
        "ssh_key_path": f"cluster_ssh_key__{app_state_name}",
        "password": f"cluster_password__{app_state_name}",
        "workers_data_path": f"cluster_workers_data_path__{app_state_name}",
        "workers": f"cluster_workers__{app_state_name}",
    }


def clear_cluster_widget_state(session_state, app_state_name: str) -> None:
    for widget_key in cluster_widget_keys(app_state_name).values():
        session_state.pop(widget_key, None)


def hydrate_cluster_widget_state(
    session_state,
    app_state_name: str,
    cluster_params: dict[str, Any],
    *,
    is_managed_pc: bool,
) -> None:
    widget_keys = cluster_widget_keys(app_state_name)
    session_state.setdefault(widget_keys["cluster_enabled"], bool(cluster_params.get("cluster_enabled", False)))
    session_state.setdefault(widget_keys["cython"], bool(cluster_params.get("cython", False)))
    session_state.setdefault(widget_keys["pool"], bool(cluster_params.get("pool", False)))
    if is_managed_pc:
        session_state[widget_keys["rapids"]] = False
    else:
        session_state.setdefault(widget_keys["rapids"], bool(cluster_params.get("rapids", False)))

    session_state.setdefault(widget_keys["scheduler"], str(cluster_params.get("scheduler", "") or ""))
    session_state.setdefault(widget_keys["user"], str(cluster_params.get("user", "") or ""))
    session_state.setdefault(widget_keys["ssh_key_path"], str(cluster_params.get("ssh_key_path", "") or ""))
    session_state.setdefault(widget_keys["workers_data_path"], str(cluster_params.get("workers_data_path", "") or ""))

    workers_value = cluster_params.get("workers", {})
    workers_key = widget_keys["workers"]
    if workers_key not in session_state:
        if isinstance(workers_value, dict):
            session_state[workers_key] = json.dumps(workers_value, indent=2)
        elif workers_value in (None, ""):
            session_state[workers_key] = ""
        else:
            session_state[workers_key] = str(workers_value)

    auth_method = cluster_params.get("auth_method")
    use_key = bool(cluster_params.get("ssh_key_path"))
    if isinstance(auth_method, str):
        use_key = auth_method.lower() == "ssh_key"
    session_state.setdefault(widget_keys["use_key"], use_key)
    session_state.pop(widget_keys["password"], None)


def persist_env_var_if_changed(
    *,
    key: str,
    value: Optional[str],
    set_env_var: Callable[[str, str], None],
    agi_env_envars: dict[str, Any] | None,
) -> None:
    normalized = "" if value is None else str(value)
    current = ""
    if isinstance(agi_env_envars, dict):
        current = str(agi_env_envars.get(key, "") or "")
    if normalized != current:
        set_env_var(key, normalized)


def _describe_share_path(env: Any) -> str:
    share_raw = env.agi_share_path
    if not share_raw:
        return "not set. Set `AGI_SHARE_DIR` to a shared mount (or symlink to one) so remote workers can read outputs."

    share_display = str(share_raw)
    resolved_display: Optional[Path] = None
    try:
        share_root = env.share_root_path()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        share_root = None
    if share_root is not None:
        resolved_display = share_root
        try:
            resolved_target = share_root.resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            resolved_target = share_root
        if resolved_target != share_root:
            resolved_display = resolved_target
    if resolved_display and str(resolved_display) != share_display:
        return f"{share_display} → {resolved_display}"
    return share_display


def _cluster_credentials_value(user: str, *, password: str = "", use_ssh_key: bool) -> str:
    sanitized_user = user.strip()
    if not sanitized_user:
        return ""
    if use_ssh_key or not password:
        return sanitized_user
    return f"{sanitized_user}:{password}"


def _is_empty_scheduler(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"", "none", "local", "localhost", "127.0.0.1", "127.0.0.1:8786"}


def _is_empty_workers(value: Any) -> bool:
    if value in (None, ""):
        return True
    if isinstance(value, dict):
        return not value or value == {"127.0.0.1": 1}
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in {"", "none"}:
            return True
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return False
        return _is_empty_workers(parsed)
    return False


def _is_empty_workers_data_path(value: Any) -> bool:
    return str(value or "").strip().lower() in {"", "none", "local", "localshare"}


def _clean_path_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def _resolve_env_relative_path(value: Any, env: Any) -> Path | None:
    text = _clean_path_text(value)
    if not text:
        return None
    try:
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            home = getattr(env, "home_abs", None)
            candidate = (Path(home).expanduser() if home else Path.home()) / candidate
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _env_local_share_candidate(env: Any) -> Path | None:
    raw_value = getattr(env, "AGI_LOCAL_SHARE", None)
    envars = getattr(env, "envars", None)
    if not raw_value and isinstance(envars, dict):
        raw_value = envars.get("AGI_LOCAL_SHARE")
    if not raw_value:
        raw_value = getattr(env, "agi_share_path", None)
    return _resolve_env_relative_path(raw_value, env)


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _workers_data_path_points_to_local_share(value: Any, env: Any) -> bool:
    text = _clean_path_text(value)
    if text.lower() in {"local", "localshare"}:
        return True
    data_path = _resolve_env_relative_path(text, env)
    local_share = _env_local_share_candidate(env)
    if data_path is None or local_share is None:
        return False
    return data_path == local_share or _path_is_within(data_path, local_share)


def _env_cluster_share_candidate(env: Any) -> Path | None:
    raw_value = getattr(env, "AGI_CLUSTER_SHARE", None)
    envars = getattr(env, "envars", None)
    if not raw_value and isinstance(envars, dict):
        raw_value = envars.get("AGI_CLUSTER_SHARE")
    if not raw_value:
        try:
            raw_value = env.share_root_path()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return None

    try:
        candidate = Path(str(raw_value)).expanduser()
    except (OSError, TypeError, ValueError):
        return None
    if not candidate.is_absolute():
        candidate = Path.home() / candidate
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return candidate


def _cluster_share_problem(env: Any) -> str | None:
    candidate = _env_cluster_share_candidate(env)
    if candidate is None:
        return "Cluster mode needs `AGI_CLUSTER_SHARE`, but no cluster share path is configured."
    if not candidate.is_dir():
        if candidate.exists():
            return f"Cluster mode needs a writable `AGI_CLUSTER_SHARE`, but `{candidate}` is not a directory."
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return (
                f"Cluster mode needs a writable `AGI_CLUSTER_SHARE`, but `{candidate}` "
                f"could not be created: {exc}"
            )
        if not candidate.is_dir():
            return f"Cluster mode needs a writable `AGI_CLUSTER_SHARE`, but `{candidate}` is not a directory."
    if not os.access(candidate, os.W_OK):
        return f"Cluster mode needs a writable `AGI_CLUSTER_SHARE`, but `{candidate}` is not writable."
    return None


def _scheduler_host_score(host: str) -> tuple[int, int, str]:
    """Prefer routable LAN scheduler addresses over link-local fallbacks."""
    cleaned = str(host or "").strip()
    if not cleaned:
        return (3, 1, "")
    try:
        address = ipaddress.ip_address(cleaned)
    except ValueError:
        return (2, 0, cleaned)
    if address.is_loopback or address.is_multicast or address.is_unspecified or address.is_link_local:
        return (3, 0, cleaned)
    if address.is_private:
        return (0, 0, cleaned)
    return (1, 0, cleaned)


def _select_lan_scheduler_host(local_hosts: Any) -> str:
    if not isinstance(local_hosts, list):
        return ""
    candidates = [str(host).strip() for host in local_hosts if str(host).strip()]
    if not candidates:
        return ""
    return min(candidates, key=_scheduler_host_score)


def _is_lan_autofill_host(host: str) -> bool:
    cleaned = str(host or "").strip()
    if not cleaned:
        return False
    try:
        address = ipaddress.ip_address(cleaned)
    except ValueError:
        if any(char.isspace() for char in cleaned):
            return False
        lowered = cleaned.lower()
        if lowered in {"localhost"}:
            return False
        return "." not in lowered or lowered.endswith(".local")

    if address.is_loopback or address.is_multicast or address.is_unspecified or address.is_link_local:
        return False
    if address.version == 4 and str(address).rsplit(".", 1)[-1] in {"0", "255"}:
        return False
    return True


def _lan_node_sources(node: dict[str, Any]) -> set[str]:
    sources = node.get("sources")
    if isinstance(sources, list):
        return {str(source).strip() for source in sources if str(source).strip()}
    if isinstance(sources, tuple):
        return {str(source).strip() for source in sources if str(source).strip()}
    return set()


def _is_known_hosts_worker_candidate(node: dict[str, Any], sources: set[str], status: str) -> bool:
    if "known-hosts" not in sources or node.get("tcp_ssh_open") is not True:
        return False
    if node.get("ssh_auth") is True:
        return True
    return status == "ssh-auth-needed"


def _is_lan_worker_autofill_candidate(node: dict[str, Any]) -> bool:
    host = str(node.get("host") or "").strip()
    if not _is_lan_autofill_host(host):
        return False
    status = str(node.get("status") or "").strip()
    if status not in LAN_WORKER_CANDIDATE_STATUSES:
        return False
    if status in LAN_READY_STATUSES:
        return True
    sources = _lan_node_sources(node)
    if sources & LAN_CONFIGURED_WORKER_SOURCES:
        return True
    return _is_known_hosts_worker_candidate(node, sources, status)


def _clear_lan_discovery_cache(cache_path: Path) -> tuple[bool, str]:
    try:
        cache_path.expanduser().unlink()
    except FileNotFoundError:
        return False, "missing"
    except OSError as exc:
        return False, str(exc)
    return True, ""


def _scheduler_ssh_target_from_cluster_value(value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    user_prefix = ""
    host = cleaned
    if "@" in host:
        user_prefix, host = host.rsplit("@", 1)
        user_prefix = f"{user_prefix}@"
    if host.startswith("[") and "]:" in host:
        host = host[1:].split("]:", 1)[0]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return f"{user_prefix}{host}".strip()


def _refresh_lan_discovery_cache(
    cache_path: Path,
    *,
    remote_user: str = "",
    scheduler: str = "",
    manager_user: str = "",
) -> tuple[bool, str]:
    try:
        report = discover_lan_nodes(
            DiscoveryOptions(
                remote_user=str(remote_user or "").strip(),
                scheduler=_scheduler_ssh_target_from_cluster_value(scheduler),
                manager_user=str(manager_user or "").strip(),
                use_cache=True,
                cache_path=cache_path,
            )
        )
    except Exception as exc:
        return False, str(exc)
    ready_count = sum(1 for node in report.nodes if node.status == "ready")
    return True, f"LAN discovery refreshed: {len(report.nodes)} node(s), {ready_count} ready."


def _env_home_path(env: Any) -> Path | None:
    raw_home = getattr(env, "home_abs", None)
    if not raw_home:
        return None
    try:
        return Path(raw_home).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _default_lan_discovery_cache_path(home: Path | str | None = None) -> Path:
    if home is None:
        return Path.home() / LAN_DISCOVERY_CACHE
    try:
        return Path(home).expanduser() / LAN_DISCOVERY_CACHE
    except (OSError, RuntimeError, TypeError, ValueError):
        return Path.home() / LAN_DISCOVERY_CACHE


def _lan_discovery_cluster_defaults(
    cache_path: Path | None = None,
    *,
    home: Path | str | None = None,
) -> dict[str, Any]:
    """Return scheduler/workers defaults from the last LAN discovery cache."""
    cache_file = cache_path or _default_lan_discovery_cache_path(home)
    try:
        payload = json.loads(cache_file.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    defaults: dict[str, Any] = {}
    local_hosts = payload.get("local_hosts")
    scheduler_host = _select_lan_scheduler_host(local_hosts)
    if scheduler_host:
        defaults["scheduler"] = f"{scheduler_host}:8786"

    nodes = payload.get("nodes")
    workers: dict[str, int] = {}
    if scheduler_host and _is_lan_autofill_host(scheduler_host):
        workers[scheduler_host] = 1
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            host = str(node.get("host") or "").strip()
            if _is_lan_worker_autofill_candidate(node):
                workers[host] = 1
    if workers:
        defaults["workers"] = dict(sorted(workers.items()))
    return defaults


def _lan_discovery_invalid_worker_hosts(cache_path: Path | None = None) -> set[str]:
    if cache_path is None:
        return set()
    try:
        payload = json.loads(cache_path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return set()
    invalid_hosts: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        host = str(node.get("host") or "").strip()
        if _is_lan_autofill_host(host) and not _is_lan_worker_autofill_candidate(node):
            invalid_hosts.add(host)
    return invalid_hosts


def _workers_dict(value: Any) -> dict[str, int]:
    if isinstance(value, dict):
        result: dict[str, int] = {}
        for key, raw_count in value.items():
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            result[str(key)] = count
        return result
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return _workers_dict(parsed)
    return {}


def _prune_invalid_lan_workers(
    cluster_params: dict[str, Any],
    session_state: dict[str, Any],
    workers_key: str,
    invalid_hosts: set[str],
) -> None:
    if not invalid_hosts:
        return
    workers = _workers_dict(session_state.get(workers_key)) or _workers_dict(cluster_params.get("workers"))
    if not workers:
        return
    pruned = {host: count for host, count in workers.items() if host not in invalid_hosts}
    if pruned == workers:
        return
    cluster_params["workers"] = pruned
    session_state[workers_key] = json.dumps(pruned, indent=2) if pruned else ""


def _apply_lan_discovery_defaults(
    cluster_params: dict[str, Any],
    session_state: dict[str, Any],
    widget_keys: dict[str, str],
    *,
    defaults: dict[str, Any],
    force: bool = False,
) -> None:
    """Populate empty cluster fields before widgets are created."""
    if not defaults:
        return
    scheduler_key = widget_keys["scheduler"]
    workers_key = widget_keys["workers"]
    should_fill_scheduler = force or _is_empty_scheduler(cluster_params.get("scheduler"))
    should_fill_workers = force or _is_empty_workers(cluster_params.get("workers"))

    scheduler = defaults.get("scheduler")
    if scheduler and should_fill_scheduler and (force or _is_empty_scheduler(session_state.get(scheduler_key))):
        scheduler_value = str(scheduler)
        cluster_params["scheduler"] = scheduler_value
        session_state[scheduler_key] = scheduler_value

    workers = defaults.get("workers")
    if isinstance(workers, dict) and workers and should_fill_workers and (
        force or _is_empty_workers(session_state.get(workers_key))
    ):
        cluster_params["workers"] = workers
        session_state[workers_key] = json.dumps(workers, indent=2)

    workers_data_path_key = widget_keys["workers_data_path"]
    workers_data_path = defaults.get("workers_data_path")
    if (
        workers_data_path
        and (force or _is_empty_workers_data_path(cluster_params.get("workers_data_path")))
        and (force or _is_empty_workers_data_path(session_state.get(workers_data_path_key)))
    ):
        workers_data_path_value = str(workers_data_path)
        cluster_params["workers_data_path"] = workers_data_path_value
        session_state[workers_data_path_key] = workers_data_path_value


def _lan_discovery_refresh_key(app_state_name: str) -> str:
    return f"cluster_lan_discovery_refresh__{app_state_name}"


def _lan_discovery_clear_key(app_state_name: str) -> str:
    return f"cluster_lan_discovery_clear__{app_state_name}"


def render_cluster_settings_ui(env: Any, deps: OrchestrateClusterDeps) -> None:
    app_settings = st.session_state.get("app_settings")
    if not isinstance(app_settings, dict):
        app_settings = {"args": {}, "cluster": {}}
        st.session_state["app_settings"] = app_settings

    cluster_params = app_settings.setdefault("cluster", {})
    app_state_name = Path(str(env.app)).name if env.app else ""
    widget_keys = cluster_widget_keys(app_state_name)

    boolean_params = ["cython", "pool"]
    if env.is_managed_pc:
        cluster_params["rapids"] = False
    else:
        boolean_params.append("rapids")
    cols_other = st.columns(len(boolean_params))
    for idx, param in enumerate(boolean_params):
        current_value = cluster_params.get(param, False)
        widget_key = widget_keys[param]
        if widget_key not in st.session_state:
            st.session_state[widget_key] = bool(current_value)
        updated_value = cols_other[idx].checkbox(
            param.replace("_", " ").capitalize(),
            key=widget_key,
            help=f"Enable or disable {param}.",
        )
        cluster_params[param] = updated_value

    cluster_enabled_key = widget_keys["cluster_enabled"]
    cluster_share_problem = _cluster_share_problem(env)
    reset_cluster_toggle_key = f"{cluster_enabled_key}__reset"
    if st.session_state.pop(reset_cluster_toggle_key, False):
        st.session_state[cluster_enabled_key] = False
    if bool(cluster_params.get("cluster_enabled", False)) and cluster_share_problem:
        cluster_params["cluster_enabled"] = False
        if cluster_enabled_key not in st.session_state:
            st.session_state[cluster_enabled_key] = False

    if cluster_enabled_key not in st.session_state:
        st.session_state[cluster_enabled_key] = bool(cluster_params.get("cluster_enabled", False))
    cluster_requested = st.toggle(
        "Enable Cluster",
        key=cluster_enabled_key,
        help="Enable cluster: provide a scheduler IP and workers configuration.",
    )
    if cluster_requested and cluster_share_problem:
        st.error(
            f"{cluster_share_problem} Fix the cluster share before enabling cluster mode; "
            "the setting was not saved."
        )
        cluster_enabled = False
        cluster_params["cluster_enabled"] = False
        st.session_state[reset_cluster_toggle_key] = True
    else:
        cluster_enabled = bool(cluster_requested)
        cluster_params["cluster_enabled"] = bool(cluster_enabled)

    if cluster_enabled:
        st.markdown(f"**agi_share_path:** {_describe_share_path(env)}")

        scheduler_widget_key = widget_keys["scheduler"]
        cluster_share_candidate = _env_cluster_share_candidate(env)
        lan_action_cols = st.columns(2)
        lan_refresh_clicked = bool(
            lan_action_cols[0].button(
                "Refresh LAN discovery",
                key=_lan_discovery_refresh_key(app_state_name),
                help=(
                    "Run LAN discovery, refresh "
                    f"`{LAN_DISCOVERY_CACHE.as_posix()}`, and reload scheduler/worker defaults."
                ),
            )
        )
        env_home = _env_home_path(env)
        lan_cache_path = _default_lan_discovery_cache_path(env_home)
        lan_clear_clicked = bool(
            lan_action_cols[1].button(
                "Clear LAN cache",
                key=_lan_discovery_clear_key(app_state_name),
                help=(
                    "Delete the cached LAN discovery inventory. Run LAN discovery again "
                    "before refreshing if the network changed."
                ),
            )
        )
        if lan_clear_clicked:
            cleared, clear_error = _clear_lan_discovery_cache(lan_cache_path)
            if cleared:
                st.info(f"LAN discovery cache cleared: `{lan_cache_path}`.")
            elif clear_error == "missing":
                st.info("LAN discovery cache is already clear.")
            else:
                st.error(f"Could not clear LAN discovery cache `{lan_cache_path}`: {clear_error}")
        lan_refresh_failed = False
        if lan_refresh_clicked and not lan_clear_clicked:
            remote_user = (
                str(st.session_state.get(widget_keys["user"]) or cluster_params.get("user") or getattr(env, "user", "") or "")
                .strip()
            )
            scheduler_value = st.session_state.get(scheduler_widget_key) or cluster_params.get("scheduler") or ""
            refreshed, refresh_message = _refresh_lan_discovery_cache(
                lan_cache_path,
                remote_user=remote_user,
                scheduler=str(scheduler_value or ""),
                manager_user=str(getattr(env, "user", "") or ""),
            )
            if refreshed:
                st.info(refresh_message)
            else:
                lan_refresh_failed = True
                st.error(f"LAN discovery refresh failed: {refresh_message}")
        lan_cache_defaults = {} if lan_clear_clicked else _lan_discovery_cluster_defaults(cache_path=lan_cache_path)
        invalid_lan_workers = set() if lan_clear_clicked else _lan_discovery_invalid_worker_hosts(lan_cache_path)
        _prune_invalid_lan_workers(
            cluster_params,
            st.session_state,
            widget_keys["workers"],
            invalid_lan_workers,
        )
        lan_defaults = lan_cache_defaults
        if cluster_share_candidate is not None:
            lan_defaults = {**lan_defaults, "workers_data_path": str(cluster_share_candidate)}
            workers_data_path_key = widget_keys["workers_data_path"]
            current_workers_data_path = st.session_state.get(
                workers_data_path_key,
                cluster_params.get("workers_data_path"),
            )
            if _workers_data_path_points_to_local_share(current_workers_data_path, env):
                cluster_share_value = str(cluster_share_candidate)
                cluster_params["workers_data_path"] = cluster_share_value
                st.session_state[workers_data_path_key] = cluster_share_value
        _apply_lan_discovery_defaults(
            cluster_params,
            st.session_state,
            widget_keys,
            defaults=lan_defaults,
            force=lan_refresh_clicked,
        )
        if lan_refresh_clicked:
            if lan_cache_defaults:
                st.info("LAN discovery defaults applied.")
            elif not lan_refresh_failed:
                st.info("LAN discovery produced no usable scheduler/worker defaults. Check local IP/CIDR and SSH prerequisites.")
        if scheduler_widget_key not in st.session_state:
            st.session_state[scheduler_widget_key] = cluster_params.get("scheduler", "")
        user_widget_key = widget_keys["user"]
        stored_user = cluster_params.get("user")
        if stored_user in (None, ""):
            stored_user = env.user or ""
        if user_widget_key not in st.session_state:
            st.session_state[user_widget_key] = stored_user
        auth_toggle_key = widget_keys["use_key"]
        auth_method = cluster_params.get("auth_method")
        default_use_key = bool(cluster_params.get("ssh_key_path"))
        if isinstance(auth_method, str):
            default_use_key = auth_method.lower() == "ssh_key"
        if auth_toggle_key not in st.session_state:
            st.session_state[auth_toggle_key] = default_use_key

        auth_row = st.container()
        scheduler_col, user_col, credential_col, toggle_col = auth_row.columns(4, vertical_alignment="top")
        with scheduler_col:
            scheduler_input = st.text_input(
                "Scheduler IP Address",
                key=scheduler_widget_key,
                placeholder="e.g., 192.168.0.100 or 192.168.0.100:8786",
                help="Provide a scheduler IP address (optionally with :PORT).",
            )
        with user_col:
            user_input = st.text_input(
                "SSH User",
                key=user_widget_key,
                placeholder="e.g., ubuntu",
                help="Remote account used for cluster SSH connections.",
            )
        sanitized_user = (user_input or "").strip()
        if not sanitized_user and stored_user:
            sanitized_user = str(stored_user).strip()

        env.user = sanitized_user
        cluster_params["user"] = sanitized_user
        if not sanitized_user:
            persist_env_var_if_changed(
                key="CLUSTER_CREDENTIALS",
                value="",
                set_env_var=deps.set_env_var,
                agi_env_envars=deps.agi_env_envars,
            )

        sanitized_key = None
        password_value = ""
        with toggle_col:
            use_ssh_key = st.toggle(
                "Use SSH key",
                key=auth_toggle_key,
                help="Toggle between SSH key-based auth (recommended) and password auth for cluster workers.",
            )
        cluster_params["auth_method"] = "ssh_key" if use_ssh_key else "password"

        if use_ssh_key:
            ssh_key_widget_key = widget_keys["ssh_key_path"]
            stored_key = cluster_params.get("ssh_key_path")
            if stored_key in (None, ""):
                stored_key = env.ssh_key_path or ""
            if ssh_key_widget_key not in st.session_state:
                st.session_state[ssh_key_widget_key] = stored_key
            with credential_col:
                ssh_key_input = st.text_input(
                    "SSH Key Path",
                    key=ssh_key_widget_key,
                    placeholder="e.g., ~/.ssh/id_rsa",
                    help="Private key used for SSH authentication.",
                )
            sanitized_key = (ssh_key_input or "").strip()
            if not sanitized_key and stored_key:
                sanitized_key = str(stored_key).strip()
        else:
            password_widget_key = widget_keys["password"]
            # Never read passwords from persisted cluster_params; only from
            # the transient env object so credentials don't leak into
            # serializable session state dicts.
            stored_password = env.password or ""
            cluster_params.pop("password", None)
            if password_widget_key not in st.session_state:
                st.session_state[password_widget_key] = stored_password
            with credential_col:
                password_input = st.text_input(
                    "SSH Password",
                    key=password_widget_key,
                    type="password",
                    placeholder="Enter SSH password",
                    help="Password for SSH authentication. Leave blank if workers use key-based auth.",
                )
            password_value = password_input or ""

        if use_ssh_key:
            cluster_params["ssh_key_path"] = sanitized_key
            env.password = None
            env.ssh_key_path = sanitized_key or None

            credentials_value = _cluster_credentials_value(sanitized_user, use_ssh_key=True)
            if credentials_value:
                persist_env_var_if_changed(
                    key="CLUSTER_CREDENTIALS",
                    value=credentials_value,
                    set_env_var=deps.set_env_var,
                    agi_env_envars=deps.agi_env_envars,
                )
            persist_env_var_if_changed(
                key="AGI_SSH_KEY_PATH",
                value=sanitized_key,
                set_env_var=deps.set_env_var,
                agi_env_envars=deps.agi_env_envars,
            )
        else:
            cluster_params.pop("password", None)
            env.password = password_value or None
            env.ssh_key_path = None

            credentials_value = _cluster_credentials_value(
                sanitized_user,
                password=password_value,
                use_ssh_key=False,
            )
            if credentials_value:
                persist_env_var_if_changed(
                    key="CLUSTER_CREDENTIALS",
                    value=credentials_value,
                    set_env_var=deps.set_env_var,
                    agi_env_envars=deps.agi_env_envars,
                )
            else:
                persist_env_var_if_changed(
                    key="CLUSTER_CREDENTIALS",
                    value="",
                    set_env_var=deps.set_env_var,
                    agi_env_envars=deps.agi_env_envars,
                )
            persist_env_var_if_changed(
                key="AGI_SSH_KEY_PATH",
                value="",
                set_env_var=deps.set_env_var,
                agi_env_envars=deps.agi_env_envars,
            )
        if scheduler_input:
            scheduler = deps.parse_and_validate_scheduler(scheduler_input)
            if scheduler:
                cluster_params["scheduler"] = scheduler

        workers_data_path_widget_key = widget_keys["workers_data_path"]
        if workers_data_path_widget_key not in st.session_state:
            st.session_state[workers_data_path_widget_key] = cluster_params.get("workers_data_path", "")

        workers_data_path_input = st.text_input(
            "Workers Data Path",
            key=workers_data_path_widget_key,
            placeholder="/path/to/data",
            help="Path to data directory on workers.",
        )
        if workers_data_path_input:
            cluster_params["workers_data_path"] = workers_data_path_input

        workers_widget_key = widget_keys["workers"]
        workers_dict = cluster_params.get("workers", {})
        if workers_widget_key not in st.session_state:
            st.session_state[workers_widget_key] = json.dumps(workers_dict, indent=2) if isinstance(workers_dict, dict) else "{}"
        workers_input = st.text_area(
            "Workers Configuration",
            key=workers_widget_key,
            placeholder='e.g., {"192.168.0.1": 2, "192.168.0.2": 3}',
            help="Provide a dictionary of worker IP addresses and capacities.",
        )
        if workers_input:
            workers = deps.parse_and_validate_workers(workers_input)
            if workers:
                cluster_params["workers"] = workers

    st.session_state.dask = cluster_enabled
    mode_value = compute_cluster_mode(cluster_params, cluster_enabled)
    st.session_state["mode"] = mode_value
    st.info(f"Run mode {RUN_MODE_LABELS[mode_value]}")
    st.session_state.app_settings["cluster"] = cluster_params

    st.session_state.app_settings = deps.write_app_settings_toml(
        env.app_settings_file,
        st.session_state.app_settings,
    )
    try:
        deps.clear_load_toml_cache()
    except (AttributeError, RuntimeError):
        pass
