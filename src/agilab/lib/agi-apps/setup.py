from __future__ import annotations

import importlib.util
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist


def _load_sanitizer():
    repo_root = Path(__file__).resolve().parents[4]
    module_path = repo_root / "tools" / "package_wheel_sanitizer.py"
    spec = importlib.util.spec_from_file_location("agi_apps_package_wheel_sanitizer", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load package wheel sanitizer from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class build_py(_build_py):
    def run(self):
        super().run()
        sanitizer = _load_sanitizer()
        removed = sanitizer.purge_packaged_builtin_app_artifacts(self.build_lib)
        for artifact_path in removed:
            print(f"[build_py] removed packaged app artifact: {artifact_path}")
        changed = sanitizer.sanitize_packaged_builtin_app_pyprojects(self.build_lib)
        for pyproject_path in changed:
            print(f"[build_py] sanitized packaged app manifest: {pyproject_path}")


class sdist(_sdist):
    def run(self):
        raise RuntimeError(
            "agi-apps is wheel-only: its public app/example payload is assembled "
            "from the AGILAB monorepo source tree during wheel build."
        )


setup(cmdclass={"build_py": build_py, "sdist": sdist})
