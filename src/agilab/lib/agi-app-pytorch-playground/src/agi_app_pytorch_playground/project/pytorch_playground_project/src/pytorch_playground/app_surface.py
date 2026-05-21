from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_APP_SRC = Path(__file__).resolve().parents[1]
_SCRIPT_DIR = Path(__file__).resolve().parent


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
        shadows_package = Path(module_file).resolve() == (_SCRIPT_DIR / "pytorch_playground.py").resolve()
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
    spec = importlib.util.spec_from_file_location("_pytorch_playground_app_args_form_surface", entrypoint)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Unable to load PyTorch Playground app form from {entrypoint}")
    module = importlib.util.module_from_spec(spec)
    module._AGILAB_APP_ARGS_FORM_IMPORT_ONLY = True
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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

    env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    args_model = app_args.ensure_defaults(app_args.load_args(env.app_settings_file), env=env)
    return env, args_model


def _append_unique_path(paths: list[Path], path: Path) -> None:
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        resolved = path.expanduser()
    if resolved not in paths:
        paths.append(resolved)


def _analysis_evidence_dirs(env: Any, args_model: Any, active_app_path: Path) -> list[Path]:
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


def _has_evidence(paths: list[Path]) -> bool:
    return any((path / "manifest.json").is_file() for path in paths)


def _render_missing_evidence(paths: list[Path]) -> None:
    import streamlit as st

    st.set_page_config(page_title="PyTorch Playground", layout="wide")
    st.title("PyTorch Playground")
    st.info("No exported PyTorch evidence found yet. Run the app once from ORCHESTRATE, then return to ANALYSIS.")
    if paths:
        st.caption("Checked evidence locations:")
        st.code("\n".join(str(path) for path in paths), language="text")


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
    if surface_mode in {"analysis", "full"}:
        active_app_path = _resolve_active_app_path(active_app)

        if active_app_path is None:
            from pytorch_playground import playground_ui

            playground_ui.main()
            return
        try:
            runtime_env, args_model = _load_orchestrate_args(active_app_path)
            evidence_dirs = _analysis_evidence_dirs(runtime_env, args_model, active_app_path)
            if not _has_evidence(evidence_dirs):
                _render_missing_evidence(evidence_dirs)
                return
            from pytorch_playground import app_args, playground_ui

            config = app_args.to_playground_config(args_model)
        except Exception as exc:
            import streamlit as st

            st.error(f"Unable to load ORCHESTRATE app arguments: {exc}")
            return
        playground_ui.main(
            config_override=config,
            preset_label="ORCHESTRATE args",
            interactive_controls=False,
            compute_loss_landscape=args_model.compute_loss_landscape,
            landscape_resolution=args_model.landscape_resolution,
            landscape_span=args_model.landscape_span,
            evidence_dirs=evidence_dirs,
        )
        return
    raise ValueError(f"Unsupported PyTorch Playground app surface mode: {mode}")


def main() -> None:
    render(mode="analysis")


if __name__ == "__main__":
    main()
