import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import streamlit as st


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


def render_cluster_settings_ui(env: Any, deps: OrchestrateClusterDeps) -> None:
    app_settings = st.session_state.get("app_settings")
    if not isinstance(app_settings, dict):
        app_settings = {"args": {}, "cluster": {}}
        st.session_state["app_settings"] = app_settings

    cluster_params = app_settings.setdefault("cluster", {})

    boolean_params = ["cython", "pool"]
    if env.is_managed_pc:
        cluster_params["rapids"] = False
    else:
        boolean_params.append("rapids")
    cols_other = st.columns(len(boolean_params))
    for idx, param in enumerate(boolean_params):
        current_value = cluster_params.get(param, False)
        updated_value = cols_other[idx].checkbox(
            param.replace("_", " ").capitalize(),
            value=current_value,
            key=f"cluster_{param}",
            help=f"Enable or disable {param}.",
        )
        cluster_params[param] = updated_value

    app_state_name = Path(str(env.app)).name if env.app else ""
    cluster_enabled_key = f"cluster_enabled__{app_state_name}"
    if cluster_enabled_key not in st.session_state:
        st.session_state[cluster_enabled_key] = bool(cluster_params.get("cluster_enabled", False))
    cluster_enabled = st.toggle(
        "Enable Cluster",
        key=cluster_enabled_key,
        help="Enable cluster: provide a scheduler IP and workers configuration.",
    )
    cluster_params["cluster_enabled"] = bool(cluster_enabled)

    if cluster_enabled:
        share_raw = env.agi_share_path
        share_display: str
        resolved_display: Optional[Path] = None
        if share_raw:
            share_display = str(share_raw)
            try:
                share_root = env.share_root_path()
            except Exception:
                share_root = None
            if share_root is not None:
                resolved_display = share_root
                try:
                    resolved_target = share_root.resolve(strict=False)
                except Exception:
                    resolved_target = share_root
                if resolved_target != share_root:
                    resolved_display = resolved_target
            if resolved_display and str(resolved_display) != share_display:
                share_display = f"{share_display} → {resolved_display}"
        else:
            share_display = (
                "not set. Set `AGI_SHARE_DIR` to a shared mount (or symlink to one) so remote workers can read outputs."
            )
        st.markdown(f"**agi_share_path:** {share_display}")

        scheduler_widget_key = f"cluster_scheduler__{app_state_name}"
        if scheduler_widget_key not in st.session_state:
            st.session_state[scheduler_widget_key] = cluster_params.get("scheduler", "")
        user_widget_key = f"cluster_user__{app_state_name}"
        stored_user = cluster_params.get("user")
        if stored_user in (None, ""):
            stored_user = env.user or ""
        if user_widget_key not in st.session_state:
            st.session_state[user_widget_key] = stored_user
        auth_toggle_key = f"cluster_use_key__{app_state_name}"
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
            ssh_key_widget_key = f"cluster_ssh_key__{app_state_name}"
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
            password_widget_key = f"cluster_password__{app_state_name}"
            stored_password = cluster_params.get("password")
            if stored_password is None:
                stored_password = env.password or ""
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

            if sanitized_user:
                persist_env_var_if_changed(
                    key="CLUSTER_CREDENTIALS",
                    value=sanitized_user,
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

            if sanitized_user:
                credentials_value = sanitized_user if not password_value else f"{sanitized_user}:{password_value}"
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

        workers_data_path_widget_key = f"cluster_workers_data_path__{app_state_name}"
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

        workers_widget_key = f"cluster_workers__{app_state_name}"
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
    benchmark_enabled = st.session_state.get("benchmark", False)

    run_mode_label = [
        "0: python", "1: pool of process", "2: cython", "3: pool and cython",
        "4: dask", "5: dask and pool", "6: dask and cython", "7: dask and pool and cython",
        "8: rapids", "9: rapids and pool", "10: rapids and cython", "11: rapids and pool and cython",
        "12: rapids and dask", "13: rapids and dask and pool", "14: rapids and dask and cython",
        "15: rapids and dask and pool and cython",
    ]

    if benchmark_enabled:
        st.session_state["mode"] = None
        st.info("Run mode benchmark (all modes)")
    else:
        mode_value = compute_cluster_mode(cluster_params, cluster_enabled)
        st.session_state["mode"] = mode_value
        st.info(f"Run mode {run_mode_label[mode_value]}")
    st.session_state.app_settings["cluster"] = cluster_params

    st.session_state.app_settings = deps.write_app_settings_toml(
        env.app_settings_file,
        st.session_state.app_settings,
    )
    try:
        deps.clear_load_toml_cache()
    except Exception:
        pass
