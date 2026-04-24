import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import streamlit as st

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
    session_state[widget_keys["cluster_enabled"]] = bool(cluster_params.get("cluster_enabled", False))
    session_state[widget_keys["cython"]] = bool(cluster_params.get("cython", False))
    session_state[widget_keys["pool"]] = bool(cluster_params.get("pool", False))
    if is_managed_pc:
        session_state[widget_keys["rapids"]] = False
    else:
        session_state[widget_keys["rapids"]] = bool(cluster_params.get("rapids", False))

    session_state[widget_keys["scheduler"]] = str(cluster_params.get("scheduler", "") or "")
    session_state[widget_keys["user"]] = str(cluster_params.get("user", "") or "")
    session_state[widget_keys["ssh_key_path"]] = str(cluster_params.get("ssh_key_path", "") or "")
    session_state[widget_keys["workers_data_path"]] = str(cluster_params.get("workers_data_path", "") or "")

    workers_value = cluster_params.get("workers", {})
    if isinstance(workers_value, dict):
        session_state[widget_keys["workers"]] = json.dumps(workers_value, indent=2)
    elif workers_value in (None, ""):
        session_state[widget_keys["workers"]] = ""
    else:
        session_state[widget_keys["workers"]] = str(workers_value)

    auth_method = cluster_params.get("auth_method")
    use_key = bool(cluster_params.get("ssh_key_path"))
    if isinstance(auth_method, str):
        use_key = auth_method.lower() == "ssh_key"
    session_state[widget_keys["use_key"]] = use_key
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
    if cluster_enabled_key not in st.session_state:
        st.session_state[cluster_enabled_key] = bool(cluster_params.get("cluster_enabled", False))
    cluster_enabled = st.toggle(
        "Enable Cluster",
        key=cluster_enabled_key,
        help="Enable cluster: provide a scheduler IP and workers configuration.",
    )
    cluster_params["cluster_enabled"] = bool(cluster_enabled)

    if cluster_enabled:
        st.markdown(f"**agi_share_path:** {_describe_share_path(env)}")

        scheduler_widget_key = widget_keys["scheduler"]
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
