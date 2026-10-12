"""Run a verified local app with its own directory and fresh project imports."""
from __future__ import annotations

import importlib.util
from importlib.metadata import PackageNotFoundError, version
import os
from contextlib import contextmanager
from pathlib import Path
import runpy
import shlex
import shutil
import sys
from threading import RLock

# All embedded demos share process-wide imports, paths and working directory.
# Their execution contexts must use the same lock, even across different demos.
APP_EXECUTION_LOCK = RLock()

# These are real runtime imports of the sealed apps and their local helpers.
# Keep the variants distinct: the RTX free-threading app uses only stdlib.
_DEMO_DEPENDENCIES = {
    "iris": ("matplotlib", "pandas", "sklearn"),
    "iris_local": ("matplotlib", "numpy", "pandas", "sklearn"),
    "iris_rtx": ("matplotlib", "numpy", "pandas", "sklearn"),
    "forecast": ("altair", "chronos", "numpy", "pandas", "torch"),
    "forecast_astra": ("altair", "chronos", "numpy", "pandas", "torch"),
    "forecast_rtx": ("altair", "chronos", "numpy", "pandas", "torch"),
    "text": ("altair", "numpy", "pandas", "sklearn", "threadpoolctl"),
    "text_astra": ("altair", "numpy", "pandas", "sklearn", "threadpoolctl"),
    "text_rtx": ("altair", "numpy", "pandas", "sklearn", "threadpoolctl"),
    "threading": ("altair", "numpy", "pandas"),
    "threading_astra": ("PIL", "altair"),
    "threading_rtx": (),
    "milp": ("altair", "highspy", "linopy", "numpy", "pandas", "pypsa"),
    "milp_astra": ("altair", "highspy", "linopy", "pandas", "psutil", "pypsa"),
    "milp_rtx": ("highspy", "linopy", "pandas", "pypsa"),
}
_MODULE_DISTRIBUTIONS = {"sklearn": "scikit-learn", "PIL": "Pillow", "chronos": "chronos-forecasting"}


def missing_demo_dependencies(demo: str) -> tuple[str, ...]:
    """Check top-level modules without importing scientific stacks or local workers."""
    return tuple(
        _MODULE_DISTRIBUTIONS.get(module, module)
        for module in _DEMO_DEPENDENCIES[demo]
        if importlib.util.find_spec(module) is None
    )


def render_demo_dependency_guidance(ui, missing: tuple[str, ...]) -> None:
    """Keep optional demos readable and explain an explicit same-environment install."""
    ui.warning("This demo needs optional scientific packages: " + ", ".join(missing) + ".")
    ui.caption("The verified build evidence and app download remain available. "
               "Install the notebook-agent extra in this AGILAB environment, then restart AGILAB.")
    try:
        requirement = f"agilab[notebook-agent]=={version('agilab')}"
    except PackageNotFoundError:
        ui.info("This source checkout has no installed AGILAB version metadata. "
                "Enable its notebook-agent extra with the checkout's development setup, then restart.")
        return
    if installer := shutil.which("uv"):
        command = [installer, "pip", "install", "--python", sys.executable, requirement]
    elif importlib.util.find_spec("pip") is not None:
        command = [sys.executable, "-m", "pip", "install", requirement]
    else:
        ui.info("Install uv first, then run this command to target the current AGILAB environment.")
        command = ["uv", "pip", "install", "--python", sys.executable, requirement]
    if sys.platform == "win32":
        # PowerShell needs an invocation operator before a quoted executable.
        ui.code("& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in command),
                language="powershell")
    else:
        ui.code(shlex.join(command), language="bash")


@contextmanager
def app_session_state(state, name: str, keys: tuple[str, ...]):
    """Scope a fixed app's non-widget state without rewriting its sealed source.

    Widget state remains owned by the view session. Callers list only persistent results
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
    names.update(path.name for path in project.iterdir() if path.is_dir())
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
