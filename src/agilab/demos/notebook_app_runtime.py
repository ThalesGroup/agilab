"""Run a verified local app with its own directory and fresh project imports."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
import runpy
import sys
from threading import RLock

# All embedded demos share process-wide imports, paths and working directory.
# Their execution contexts must use the same lock, even across different demos.
APP_EXECUTION_LOCK = RLock()


@contextmanager
def app_session_state(state, name: str, keys: tuple[str, ...]):
    """Scope a fixed app's non-widget state without rewriting its sealed source.

    Widget state remains Streamlit-owned. Callers list only persistent results
    and submitted parameters, which may otherwise collide with another app.
    """
    storage_key = f"_agilab_notebook_{name}_state"
    previous = {key: state[key] for key in keys if key in state}
    local = state.get(storage_key, {})
    for key in keys:
        state.pop(key, None)
        if key in local:
            state[key] = local[key]
    try:
        yield
    finally:
        state[storage_key] = {key: state[key] for key in keys if key in state}
        for key in keys:
            state.pop(key, None)
            if key in previous:
                state[key] = previous[key]


def run_app(project: Path) -> None:
    project = project.resolve()
    names = {path.stem for path in project.glob("*.py")}
    names.update(path.name for path in project.iterdir() if path.is_dir() and (path / "__init__.py").is_file())
    with APP_EXECUTION_LOCK:
        saved = {name: module for name, module in sys.modules.copy().items()
                 if name.split(".", 1)[0] in names}
        for name in saved:
            sys.modules.pop(name, None)
        old_cwd, old_path = Path.cwd(), sys.path[:]
        sys.path.insert(0, str(project))
        try:
            os.chdir(project)
            runpy.run_path(str(project / "app.py"), run_name="__main__")
        finally:
            os.chdir(old_cwd)
            sys.path[:] = old_path
            for name in list(sys.modules):
                if name.split(".", 1)[0] in names:
                    sys.modules.pop(name, None)
            sys.modules.update(saved)
