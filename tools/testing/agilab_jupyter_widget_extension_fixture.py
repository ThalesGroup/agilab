"""Stage installed widget labextensions in a task-owned Jupyter data directory."""

from __future__ import annotations

import importlib
from importlib.metadata import distribution
from pathlib import Path
import shutil


def stage_installed_widget_extensions(data_dir: Path) -> list[str]:
    """Use the installed package assets even when uv runs Jupyter in an overlay."""
    staged = []
    for module_name in ("anywidget", "jupyterlab_widgets"):
        module = importlib.import_module(module_name)
        for extension in module._jupyter_labextension_paths():
            destination = extension["dest"]
            source = Path(extension["src"])
            if not source.is_absolute():
                source = Path(module.__file__).parent / source
            if not source.is_dir():
                # jupyterlab_widgets publishes an absolute path based on
                # sys.prefix; an overlay changes that prefix without moving
                # the distribution's recorded data files.
                installed = distribution(module_name)
                suffix = f"share/jupyter/labextensions/{destination}/package.json"
                recorded = [file for file in installed.files or () if str(file).endswith(suffix)]
                if len(recorded) != 1:
                    raise RuntimeError(f"Cannot locate installed widget labextension: {destination}")
                source = installed.locate_file(recorded[0]).resolve().parent
            if not (source / "package.json").is_file():
                raise RuntimeError(f"Incomplete installed widget labextension: {destination}")
            shutil.copytree(source, Path(data_dir) / "labextensions" / destination, dirs_exist_ok=True)
            staged.append(destination)
    return staged
