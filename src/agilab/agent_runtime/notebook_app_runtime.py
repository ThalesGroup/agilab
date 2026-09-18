"""Run a verified local app with its own directory and fresh project imports."""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys
from threading import RLock

_LOCK = RLock()


def run_app(project: Path) -> None:
    project = project.resolve()
    names = {path.stem for path in project.glob("*.py")}
    names.update(path.name for path in project.iterdir() if path.is_dir() and (path / "__init__.py").is_file())
    with _LOCK:
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
