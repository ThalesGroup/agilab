"""App switching method for the ``AgiEnv`` singleton."""

import logging
import shutil
from pathlib import Path


logger = logging.getLogger(__name__)


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
    # Never delete a project directory that already existed before this switch:
    # change_app is called on pre-existing targets (project selection, page load),
    # and only owns cleanup of a destination it materialises during a failed clone.
    existed_before = active_app.exists()
    env_cls = type(env)
    try:
        reinitialize = getattr(env, "reinitialize_for_app", None)
        if callable(reinitialize):
            reinitialize(
                apps_path=active_app.parent,
                app=requested_name,
                verbose=getattr(env, "verbose", 0),
            )
        else:
            lock = getattr(env_cls, "_lock", None)
            context = lock if lock is not None else _NullContext()
            with context:
                env_cls.__init__(
                    env,
                    apps_path=active_app.parent,
                    app=requested_name,
                    verbose=getattr(env, "verbose", 0),
                    _agilab_reinitialize=True,
                )
    except BaseException:
        # Catch only THIS reinit's failure — probing sys.exc_info() would also
        # fire for an unrelated exception being handled in an outer frame.
        if not existed_before and active_app.exists():
            logger.warning(
                "change_app: removing partially created project %s after failed reinit",
                active_app,
            )
            shutil.rmtree(active_app, ignore_errors=True)
        raise


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


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
