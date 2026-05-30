"""App switching method for the ``AgiEnv`` singleton."""

import shutil
import sys
from pathlib import Path


def change_app(env, app):
    """Reinitialise ``env`` for a different app project."""

    current_name = _app_name(getattr(env, "app", None))
    requested_name = _app_name(app)

    if not requested_name:
        raise ValueError("app name must be non-empty")
    if requested_name == current_name:
        return

    apps_path = _active_apps_path(env)
    if apps_path is None:
        raise RuntimeError("apps_path is not configured on AgiEnv")

    active_app = apps_path / requested_name
    env_cls = type(env)
    try:
        env_cls.__init__(
            env,
            apps_path=active_app.parent,
            app=requested_name,
            verbose=env_cls.verbose,
            _agilab_reinitialize=True,
        )
    finally:
        if sys.exc_info()[0] is not None and active_app.exists():
            shutil.rmtree(active_app, ignore_errors=True)


def _app_name(value):
    if value is None:
        return None
    try:
        return Path(str(value)).name
    except (TypeError, ValueError):
        return str(value)


def _active_apps_path(env):
    current_app = getattr(env, "app", None)
    try:
        current_app_path = Path(str(current_app))
        if current_app_path.name:
            return current_app_path.parent
    except (TypeError, ValueError):
        pass
    return getattr(env, "apps_path", None) or type(env).apps_path
