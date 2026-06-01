from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_APP_SRC = Path(__file__).resolve().parents[1]
_APP_PROJECT = _APP_SRC.parent
_SCRIPT_DIR = Path(__file__).resolve().parent
_LAST_MANIFEST_SESSION_KEY = "pytorch_playground_last_manifest"


def _prepend_sys_path(path: Path) -> None:
    entry = str(path)
    sys.path[:] = [existing for existing in sys.path if existing != entry]
    sys.path.insert(0, entry)


def _drop_shadowed_package_module() -> None:
    module = sys.modules.get("pytorch_playground")
    module_file = getattr(module, "__file__", None)
    if module_file is None:
        return
    try:
        shadows_package = (
            Path(module_file).resolve()
            == (_SCRIPT_DIR / "pytorch_playground.py").resolve()
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return
    if not shadows_package:
        return
    for name in list(sys.modules):
        if name == "pytorch_playground" or name.startswith("pytorch_playground."):
            sys.modules.pop(name, None)


_prepend_sys_path(_APP_SRC)
_drop_shadowed_package_module()


def _load_app_args_form() -> ModuleType:
    entrypoint = _APP_SRC / "app_args_form.py"
    spec = importlib.util.spec_from_file_location(
        "_pytorch_playground_app_args_form_surface", entrypoint
    )
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(
            f"Unable to load PyTorch Playground app form from {entrypoint}"
        )
    module = importlib.util.module_from_spec(spec)
    module._AGILAB_APP_ARGS_FORM_IMPORT_ONLY = True
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _render_dependency_import_error(
    exc: BaseException,
    *,
    configure_page: bool = True,
    container: Any | None = None,
) -> None:
    import streamlit as st

    root = container or st
    if configure_page:
        st.set_page_config(page_title="PyTorch Playground", layout="wide")
        st.title("PyTorch Playground")
    root.error("PyTorch Playground scientific dependencies are not importable.")
    root.caption(f"{type(exc).__name__}: {exc}")
    root.caption(
        "Reinstall the AGILAB environment or rerun the installer before opening this surface."
    )


def _load_playground_ui_or_report(
    *,
    configure_page: bool = True,
    container: Any | None = None,
) -> Any | None:
    try:
        from pytorch_playground import playground_ui
    except (ImportError, OSError, ValueError) as exc:
        _render_dependency_import_error(
            exc, configure_page=configure_page, container=container
        )
        return None
    return playground_ui


def _resolve_active_app_path(active_app: Path | None = None) -> Path | None:
    if active_app is not None:
        candidate = Path(active_app).expanduser()
        return candidate.resolve() if candidate.exists() else None

    for index, arg in enumerate(sys.argv):
        if arg == "--active-app" and index + 1 < len(sys.argv):
            candidate = Path(sys.argv[index + 1]).expanduser()
            return candidate.resolve() if candidate.exists() else None
        if arg.startswith("--active-app="):
            candidate = Path(arg.split("=", 1)[1]).expanduser()
            return candidate.resolve() if candidate.exists() else None
    return None


def _load_orchestrate_args(active_app_path: Path):
    from agi_env import AgiEnv
    from pytorch_playground import app_args

    env = getattr(AgiEnv, "for_app", AgiEnv)(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    args_model = app_args.ensure_defaults(
        app_args.load_args(env.app_settings_file), env=env
    )
    return env, args_model


def _append_unique_path(paths: list[Path], path: Path) -> None:
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        resolved = path.expanduser()
    if resolved not in paths:
        paths.append(resolved)


def _analysis_evidence_dirs(
    env: Any, args_model: Any, active_app_path: Path
) -> list[Path]:
    paths: list[Path] = []
    export_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export"))
    for target in (
        str(getattr(env, "target", "") or ""),
        str(getattr(env, "app", "") or ""),
        active_app_path.name,
    ):
        if target:
            _append_unique_path(paths, export_root / target / "pytorch_playground")

    data_out = Path(getattr(args_model, "data_out", "pytorch_playground/evidence"))
    if not data_out.is_absolute():
        resolve_share_path = getattr(env, "resolve_share_path", None)
        if callable(resolve_share_path):
            data_out = Path(resolve_share_path(data_out))
    _append_unique_path(paths, data_out)
    return paths


def _manifest_path_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve())
    except OSError:
        return str(path.expanduser())


def _record_latest_manifest_path(
    active_app_path: Path, evidence_dirs: list[Path]
) -> None:
    import streamlit as st

    latest_candidate = None
    for raw_path in evidence_dirs:
        manifest_path = Path(raw_path).expanduser() / "manifest.json"
        try:
            mtime = manifest_path.stat().st_mtime_ns
        except OSError:
            continue
        path_key = _manifest_path_key(manifest_path.parent)
        if latest_candidate is None or mtime > latest_candidate[0]:
            latest_candidate = (mtime, path_key)

    if latest_candidate is None:
        return

    st.session_state[f"{_LAST_MANIFEST_SESSION_KEY}:{active_app_path.name}"] = latest_candidate


def _consume_last_manifest_token(active_app_path: Path | None) -> tuple[int, str] | None:
    import streamlit as st

    if active_app_path is None:
        return None

    session_key = f"{_LAST_MANIFEST_SESSION_KEY}:{active_app_path.name}"
    token = st.session_state.get(session_key)
    if token is None:
        return None

    if not isinstance(token, tuple) or len(token) != 2:
        return None

    raw_timestamp, root_key = token
    try:
        timestamp = int(raw_timestamp)
    except (TypeError, ValueError):
        return None

    return timestamp, str(root_key)


def _has_evidence(paths: list[Path]) -> bool:
    return any((path / "manifest.json").is_file() for path in paths)


def _render_missing_evidence(paths: list[Path], *, configure_page: bool = True) -> None:
    import streamlit as st

    if configure_page:
        st.set_page_config(page_title="PyTorch Playground", layout="wide")
        st.title("PyTorch Playground")
    st.info(
        "No exported PyTorch evidence found yet. Run the app once from ORCHESTRATE, then return to ANALYSIS."
    )
    if paths:
        st.caption("Checked evidence locations:")
        st.code("\n".join(str(path) for path in paths), language="text")


def _render_analysis_surface(
    active_app_path: Path | None,
    *,
    configure_page: bool = True,
    compact: bool = False,
) -> None:
    if active_app_path is None:
        playground_ui = _load_playground_ui_or_report(
            configure_page=configure_page
        )
        if playground_ui is None:
            return
        playground_ui.main(configure_page=configure_page, compact=compact)
        return
    try:
        runtime_env, args_model = _load_orchestrate_args(active_app_path)
        evidence_dirs = _analysis_evidence_dirs(
            runtime_env, args_model, active_app_path
        )
    except Exception as exc:
        import streamlit as st

        st.error(f"Unable to load ORCHESTRATE app arguments: {exc}")
        return
    if not _has_evidence(evidence_dirs):
        _render_missing_evidence(evidence_dirs, configure_page=configure_page)
        return
    try:
        from pytorch_playground import app_args

        config = app_args.to_playground_config(args_model)
    except (ImportError, OSError, ValueError) as exc:
        _render_dependency_import_error(exc, configure_page=configure_page)
        return
    except Exception as exc:
        import streamlit as st

        st.error(f"Unable to build PyTorch Playground config: {exc}")
        return
    playground_ui = _load_playground_ui_or_report(
        configure_page=configure_page
    )
    if playground_ui is None:
        return
    playground_kwargs = dict(
        config_override=config,
        preset_label="ORCHESTRATE args",
        interactive_controls=False,
        compute_loss_landscape=args_model.compute_loss_landscape,
        landscape_resolution=args_model.landscape_resolution,
        landscape_span=args_model.landscape_span,
        evidence_dirs=evidence_dirs,
        configure_page=configure_page,
        compact=compact,
    )
    manifest_token = _consume_last_manifest_token(active_app_path)
    if manifest_token is not None:
        playground_kwargs["evidence_manifest_token"] = manifest_token
    playground_ui.main(**playground_kwargs)


def _run_playground_once(runtime_env: Any, args_model: Any):
    from pytorch_playground_worker.pytorch_playground_worker import (
        PytorchPlaygroundWorker,
    )

    worker = PytorchPlaygroundWorker.__new__(PytorchPlaygroundWorker)
    dump = getattr(args_model, "model_dump", None)
    worker.args = dump(mode="json") if callable(dump) else args_model
    worker.env = runtime_env
    worker._worker_id = 0
    worker.start()
    return worker.work_pool("pytorch_playground")


def _render_run_button(
    active_app_path: Path, *, container: Any, app_args_form: Any | None = None
) -> None:
    import streamlit as st

    if not container.button(
        "Refresh evidence",
        type="primary",
        width="stretch",
        key=f"pytorch_playground:refresh_evidence:{active_app_path.name}",
    ):
        return
    try:
        runtime_env, args_model = _load_orchestrate_args(active_app_path)
        persist_current_args = getattr(
            app_args_form or _load_app_args_form(), "persist_current_args", None
        )
        if callable(persist_current_args):
            args_model = persist_current_args(env=runtime_env)
        evidence_dirs = _analysis_evidence_dirs(runtime_env, args_model, active_app_path)
        with st.spinner("Refreshing PyTorch evidence"):
            summary = _run_playground_once(runtime_env, args_model)
        _record_latest_manifest_path(active_app_path, evidence_dirs)
        rerun = getattr(st, "rerun", None)
    except Exception as exc:
        container.error(f"Run failed: {exc}")
        return
    rows = len(summary) if hasattr(summary, "__len__") else 1
    row_label = "row" if rows == 1 else "rows"
    container.success(f"Run complete. Evidence refreshed ({rows} {row_label}).")
    if callable(rerun):
        rerun()


def _render_surface_styles() -> None:
    import streamlit as st

    markdown = getattr(st, "markdown", None)
    if not callable(markdown):
        return
    markdown(
        """
<style>
.block-container,
[data-testid="stMainBlockContainer"] {
  padding-top: 0.85rem !important;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _query_param_is_truthy(name: str) -> bool:
    import streamlit as st

    try:
        value = st.query_params.get(name)
    except Exception:
        value = None
    if isinstance(value, (list, tuple)):
        value = value[-1] if value else ""
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _hide_embedded_streamlit_sidebar() -> None:
    import streamlit as st

    st.markdown(
        """
        <style>
        html, body,
        [data-testid="stApp"],
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        .main {
          margin-left: 0 !important;
          padding-left: 0 !important;
          width: 100% !important;
          max-width: 100% !important;
        }
        section[data-testid="stSidebar"],
        [data-testid="stSidebar"],
        [data-testid="stSidebarContent"],
        [data-testid="stSidebarHeader"],
        [data-testid="stSidebarNav"],
        [data-testid="stSidebarUserContent"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"],
        [aria-label="Sidebar"],
        [aria-label="sidebar"],
        button[title="Open sidebar"],
        button[title="Close sidebar"] {
          display: none !important;
          visibility: hidden !important;
          width: 0 !important;
          min-width: 0 !important;
          max-width: 0 !important;
        }
        header[data-testid="stHeader"] {
          left: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_controls_surface(
    active_app_path: Path,
    *,
    env: Any | None = None,
    container: Any | None = None,
) -> None:
    import streamlit as st

    controls_container = container or st.sidebar
    try:
        runtime_env, _args_model = _load_orchestrate_args(active_app_path)
    except Exception as exc:
        controls_container.error(f"Unable to load ORCHESTRATE app arguments: {exc}")
        return

    with controls_container:
        controls_container.markdown("**Run**")
        try:
            app_args_form = _load_app_args_form()
        except (ImportError, OSError, ValueError) as exc:
            _render_dependency_import_error(
                exc, configure_page=False, container=controls_container
            )
        else:
            _render_run_button(
                active_app_path,
                container=controls_container,
                app_args_form=app_args_form,
            )
            app_args_form.render(
                env=env or runtime_env,
                container=controls_container,
                wide=False,
                compact=True,
            )


def _render_full_surface(
    active_app_path: Path | None,
    *,
    env: Any | None = None,
    container: Any | None = None,
) -> None:
    if active_app_path is None:
        playground_ui = _load_playground_ui_or_report()
        if playground_ui is None:
            return
        playground_ui.main()
        return

    import streamlit as st

    playground_ui = _load_playground_ui_or_report(
        configure_page=container is None, container=container
    )
    if playground_ui is None:
        return

    if container is None:
        embedded = _query_param_is_truthy("embed")
        st.set_page_config(
            page_title=getattr(playground_ui, "PAGE_TITLE", "PyTorch Playground"),
            layout="wide",
            initial_sidebar_state="collapsed" if embedded else "auto",
        )
        if embedded:
            _hide_embedded_streamlit_sidebar()
    else:
        embedded = False

    try:
        runtime_env, _args_model = _load_orchestrate_args(active_app_path)
    except Exception as exc:
        st.error(f"Unable to load ORCHESTRATE app arguments: {exc}")
        return

    root = container or st
    _render_surface_styles()
    if container is None:
        if not embedded:
            _render_controls_surface(active_app_path, env=env or runtime_env)
        _render_analysis_surface(active_app_path, configure_page=False, compact=True)
        return
    else:
        analysis_container, controls_container = root.columns([0.70, 0.30])

    _render_controls_surface(
        active_app_path, env=env or runtime_env, container=controls_container
    )
    with analysis_container:
        _render_analysis_surface(active_app_path, configure_page=False, compact=True)


def render(
    *,
    mode: str = "analysis",
    active_app: Path | None = None,
    env: Any | None = None,
    container: Any | None = None,
    streamlit: Any | None = None,
) -> None:
    surface_mode = str(mode or "analysis").lower()
    if surface_mode == "configure":
        app_args_form = _load_app_args_form()
        app_args_form.render(env=env, container=container)
        return
    if surface_mode == "controls":
        active_app_path = _resolve_active_app_path(active_app)
        if active_app_path is not None:
            _render_controls_surface(active_app_path, env=env, container=container)
        return
    if surface_mode == "analysis":
        active_app_path = _resolve_active_app_path(active_app)
        _render_analysis_surface(
            active_app_path,
            configure_page=container is None,
            compact=container is not None,
        )
        return
    if surface_mode == "full":
        active_app_path = _resolve_active_app_path(active_app)
        _render_full_surface(active_app_path, env=env, container=container)
        return
    raise ValueError(f"Unsupported PyTorch Playground app surface mode: {mode}")


def main() -> None:
    render(mode="full", active_app=_APP_PROJECT)


if __name__ == "__main__":
    main()
