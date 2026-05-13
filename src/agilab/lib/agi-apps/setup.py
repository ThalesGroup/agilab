from __future__ import annotations

import importlib.util
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist


def _load_build_support():
    module_path = Path(__file__).resolve().parents[4] / "src" / "agilab" / "lib" / "app_project_build_support.py"
    if not module_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("agilab_app_project_build_support", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load app project build support from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_payload(target_src_root: Path) -> None:
    support = _load_build_support()
    if support is None:
        return
    support.copy_agi_apps_umbrella_payload(target_src_root)
    support.write_agi_apps_catalog(target_src_root / "agi_apps")


class build_py(_build_py):
    def run(self):
        super().run()
        _copy_payload(Path(self.build_lib))


class sdist(_sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        _copy_payload(Path(base_dir) / "src")


setup(cmdclass={"build_py": build_py, "sdist": sdist})
