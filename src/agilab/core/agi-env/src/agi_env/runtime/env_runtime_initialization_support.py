"""Runtime environment variable initialization for :mod:`agi_env.agi_env`."""

from pathlib import Path
from typing import Callable, Mapping, MutableMapping

from agi_env.connector_registry import resolve_connector_root
from agi_env.credential_store_support import read_cluster_credentials
from agi_env.defaults import get_default_openai_model
from agi_env.env_config_support import clean_envar_value


def initialize_app_runtime(
    env,
    envars: MutableMapping[str, str],
    *,
    environ: Mapping[str, str],
    default_account: str,
    read_agilab_path_fn: Callable[[], str | Path | None],
    optional_agi_pages_bundles_root_fn: Callable[[], Path | None],
    ensure_dir_fn: Callable[[str | Path], Path],
    logger,
) -> None:
    """Cache app runtime paths and credentials on an ``AgiEnv`` instance."""

    env.CLUSTER_CREDENTIALS = read_cluster_credentials(
        envars.get("CLUSTER_CREDENTIALS", None),
        environ=environ,
        default_account=default_account,
        logger=logger,
    )
    if env.CLUSTER_CREDENTIALS:
        envars["CLUSTER_CREDENTIALS"] = env.CLUSTER_CREDENTIALS

    env.OPENAI_API_KEY = envars.get("OPENAI_API_KEY", None)
    env.OPENAI_MODEL = envars.get("OPENAI_MODEL") or get_default_openai_model()

    log_connector = resolve_connector_root(
        env,
        connector_id="log_root",
        label="Log root",
        attr_name="AGILAB_LOG_ABS",
        env_key="AGI_LOG_DIR",
        default_child="log",
        ensure=True,
        prefer_attr=False,
        description="Root for execution logs and run manifests.",
    )
    env.AGILAB_LOG_ABS = log_connector.path
    runenv_base = env.AGILAB_LOG_ABS / "execute"
    ensure_dir_fn(runenv_base)
    env.runenv = runenv_base / env.target
    ensure_dir_fn(env.runenv)

    export_connector = resolve_connector_root(
        env,
        connector_id="export_root",
        label="Export root",
        attr_name="AGILAB_EXPORT_ABS",
        env_key="AGI_EXPORT_DIR",
        default_child="export",
        ensure=True,
        prefer_attr=False,
        description="Root for app and page output artifacts.",
    )
    env.AGILAB_EXPORT_ABS = export_connector.path
    env.export_apps = env.AGILAB_EXPORT_ABS / "apps-zip"
    ensure_dir_fn(env.export_apps)

    mlflow_tracking_override = clean_envar_value(envars, "MLFLOW_TRACKING_DIR")
    if mlflow_tracking_override:
        mlflow_tracking_dir = Path(mlflow_tracking_override).expanduser()
        if not mlflow_tracking_dir.is_absolute():
            mlflow_tracking_dir = env.home_abs / mlflow_tracking_dir
        env.MLFLOW_TRACKING_DIR = mlflow_tracking_dir
    else:
        env.MLFLOW_TRACKING_DIR = env.home_abs / ".mlflow"

    env.AGILAB_PAGES_ABS = _resolve_pages_root(
        envars,
        agilab_pck=env.agilab_pck,
        read_agilab_path_fn=read_agilab_path_fn,
        optional_agi_pages_bundles_root_fn=optional_agi_pages_bundles_root_fn,
    )
    if not env.AGILAB_PAGES_ABS.exists():
        if logger:
            logger.info(f"AGILAB_PAGES_ABS missing: {env.AGILAB_PAGES_ABS}")

    env.copilot_file = env.agilab_pck / "agi_codex.py"


def _resolve_pages_root(
    envars: MutableMapping[str, str],
    *,
    agilab_pck: Path,
    read_agilab_path_fn: Callable[[], str | Path | None],
    optional_agi_pages_bundles_root_fn: Callable[[], Path | None],
) -> Path:
    pages_override = clean_envar_value(envars, "AGI_PAGES_DIR")
    if pages_override:
        return Path(pages_override).expanduser()

    candidates = [
        agilab_pck / "apps-pages",
        agilab_pck / "agilab/apps-pages",
    ]

    repo_hint = read_agilab_path_fn()
    if repo_hint:
        repo_hint = Path(repo_hint)
        for suffix in ("apps-pages", "agilab/apps-pages"):
            candidates.append(repo_hint / suffix)

    agi_pages_root = optional_agi_pages_bundles_root_fn()
    if agi_pages_root is not None:
        candidates.append(agi_pages_root)

    return next((candidate.resolve() for candidate in candidates if candidate and candidate.exists()), candidates[0])
