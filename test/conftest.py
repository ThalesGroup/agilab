from __future__ import annotations

from pathlib import Path
import importlib.util
import shutil
import sys
from unittest.mock import patch
import warnings

import pytest

warnings.filterwarnings(
    "ignore",
    message=r".*ast\.Num is deprecated and will be removed in Python 3\.14.*",
    category=DeprecationWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"Theme names and color schemes are lowercase in IPython 9\.0 use nocolor instead",
    category=DeprecationWarning,
)

from streamlit.testing.v1 import AppTest

from agi_env import AgiEnv


REAL_HOME = Path.home().resolve()
REPO_ROOT = Path(__file__).resolve().parents[1]
AGILAB_PACKAGE_ROOT = REPO_ROOT / "src" / "agilab"


def _ensure_agilab_package_spec() -> None:
    """Keep synthetic test-package shims compatible with importlib.find_spec."""
    package = sys.modules.get("agilab")
    if package is None or not hasattr(package, "__path__"):
        return
    if getattr(package, "__spec__", None) is not None:
        return
    package.__spec__ = importlib.util.spec_from_file_location(
        "agilab",
        AGILAB_PACKAGE_ROOT / "__init__.py",
        submodule_search_locations=[str(AGILAB_PACKAGE_ROOT)],
    )
    package.__file__ = str(AGILAB_PACKAGE_ROOT / "__init__.py")
    package.__package__ = "agilab"


@pytest.fixture(autouse=True)
def normalize_agilab_package_spec_for_root_tests():
    _ensure_agilab_package_spec()
    yield
    _ensure_agilab_package_spec()


@pytest.fixture(autouse=True)
def reset_agienv_singleton():
    """Keep singleton state from leaking across tests."""
    AgiEnv.reset()
    yield
    AgiEnv.reset()


@pytest.fixture(autouse=True)
def isolate_home_for_root_tests(tmp_path, monkeypatch):
    """Keep runner-local ~/.agilab state from leaking into root test imports."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("AGI_CLUSTER_ENABLED", raising=False)
    monkeypatch.delenv("AGI_CLUSTER_SHARE", raising=False)
    monkeypatch.delenv("AGI_SHARE_DIR", raising=False)
    monkeypatch.delenv("APPS_REPOSITORY", raising=False)
    monkeypatch.delenv("AGILAB_APPS_REPOSITORY", raising=False)
    monkeypatch.delenv("APP_DEFAULT", raising=False)
    # Root tests must not inherit developer-shell secrets. Individual tests that
    # need these values should opt in explicitly with monkeypatch/setenv.
    monkeypatch.delenv("CLUSTER_CREDENTIALS", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    # Some UI support modules are imported during pytest collection, before this
    # fixture can set HOME. Rebind their module-level state paths for every test
    # so page AppTests never read or write the developer's real last-active app.
    from agi_env import ui_support

    monkeypatch.setattr(ui_support, "_GLOBAL_STATE_FILE", share_dir / "app_state.toml")
    monkeypatch.setattr(ui_support, "_LEGACY_LAST_APP_FILE", share_dir / ".last-active-app")
    monkeypatch.setattr(ui_support, "_DOCS_ALREADY_OPENED", False, raising=False)
    monkeypatch.setattr(ui_support, "_LAST_DOCS_URL", None, raising=False)

    repo_agilab_dir = (Path(__file__).resolve().parents[1] / "src" / "agilab").resolve()
    (share_dir / ".agilab-path").write_text(str(repo_agilab_dir) + "\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def preserve_real_user_state_for_root_tests(tmp_path):
    """
    Root tests, especially Streamlit AppTests, must not leak writes into the
    developer's real ~/.agilab, ~/.local/share/agilab, or ~/export trees.
    """

    tracked_files = [
        REAL_HOME / ".agilab" / ".env",
        REAL_HOME / ".local" / "share" / "agilab" / "app_state.toml",
        REAL_HOME / ".local" / "share" / "agilab" / ".last-active-app",
    ]
    tracked_export_root = REAL_HOME / "export"
    backup_root = tmp_path / "real_user_state_backup"

    for src in tracked_files:
        if not src.exists():
            continue
        dst = backup_root / src.relative_to(REAL_HOME)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    export_snapshots: list[tuple[Path, Path]] = []
    if tracked_export_root.exists():
        for src in tracked_export_root.rglob("AGI_*.py"):
            dst = backup_root / src.relative_to(REAL_HOME)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            export_snapshots.append((src, dst))

    yield

    for src in tracked_files:
        backup = backup_root / src.relative_to(REAL_HOME)
        if backup.exists():
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, src)
        elif src.exists():
            src.unlink()

    if tracked_export_root.exists():
        current_exports = list(tracked_export_root.rglob("AGI_*.py"))
        for src in current_exports:
            backup = backup_root / src.relative_to(REAL_HOME)
            if not backup.exists():
                src.unlink()

    for src, backup in export_snapshots:
        if not backup.exists():
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, src)


@pytest.fixture
def create_temp_app_project(tmp_path):
    """Create a minimal temporary AGILAB app project for page-level tests."""

    apps_dir = tmp_path / "apps"
    apps_dir.mkdir(exist_ok=True)

    def _create(
        project_name: str,
        package_name: str | None = None,
        app_settings_text: str = "",
        pyproject_name: str | None = None,
    ) -> Path:
        package_name_local = package_name or project_name.removesuffix("_project")
        project_dir = apps_dir / project_name
        (project_dir / "src" / package_name_local).mkdir(parents=True, exist_ok=True)
        (project_dir / "pyproject.toml").write_text(
            f"[project]\nname='{pyproject_name or project_name.replace('_', '-')}'\n",
            encoding="utf-8",
        )
        (project_dir / "src" / "app_settings.toml").write_text(app_settings_text, encoding="utf-8")
        (project_dir / "src" / package_name_local / "__init__.py").write_text("", encoding="utf-8")
        return project_dir

    return _create


@pytest.fixture
def run_page_app_test(monkeypatch, tmp_path):
    """Run a Streamlit page AppTest with a temporary active app and isolated shares."""

    def _run(page_path: str, project_dir: Path, export_root: Path | None = None, timeout: int = 20) -> AppTest:
        resolved_export_root = export_root or (tmp_path / "export")
        argv = [Path(page_path).name, "--active-app", str(project_dir)]
        with patch.object(sys, "argv", argv):
            monkeypatch.setenv("AGI_EXPORT_DIR", str(resolved_export_root))
            monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
            monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
            monkeypatch.setenv("OPENAI_API_KEY", "dummy")
            monkeypatch.setenv("IS_SOURCE_ENV", "1")
            app_test = AppTest.from_file(page_path, default_timeout=timeout)
            app_test.run()
        return app_test

    return _run
