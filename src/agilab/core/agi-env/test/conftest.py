"""Test-only UI shims for agi-env's optional Streamlit helpers."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

import pytest


_ORIGINAL_PATH_HOME = Path.home


def _home_from_env() -> Path:
    """Resolve ``Path.home()`` while honouring an overridden ``HOME`` env var.

    On Windows ``Path.home()`` reads ``USERPROFILE``/``HOMEDRIVE``+``HOMEPATH``
    before ``HOME``, which makes tests that only ``monkeypatch.setenv("HOME", ...)``
    leak into the real user profile.  We prefer ``HOME`` when set so tests stay
    fully isolated across platforms.
    """

    home = os.environ.get("HOME")
    if home:
        return Path(home)
    return _ORIGINAL_PATH_HOME()


_F = TypeVar("_F", bound=Callable[..., Any])


class _SessionState(dict[str, Any]):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class _NoopContainer:
    def __getattr__(self, _name: str) -> Callable[..., None]:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


class _StreamlitStub(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("streamlit")
        self.session_state = _SessionState()
        self.sidebar = _NoopContainer()
        self.query_params: dict[str, Any] = {}

    def cache_data(self, func: _F | None = None, **_kwargs: Any) -> _F | Callable[[_F], _F]:
        def _decorate(inner: _F) -> _F:
            return inner

        if func is None:
            return _decorate
        return _decorate(func)

    def checkbox(self, _label: str, value: bool = False, **_kwargs: Any) -> bool:
        return value

    def number_input(self, _label: str, **kwargs: Any) -> Any:
        return kwargs.get("value")

    def text_area(self, _label: str, value: str = "", **_kwargs: Any) -> str:
        return value

    def text_input(self, _label: str, value: str = "", **_kwargs: Any) -> str:
        return value

    def selectbox(self, _label: str, options: list[Any], index: int = 0, **_kwargs: Any) -> Any:
        return options[index]

    def date_input(self, _label: str, value: date, **_kwargs: Any) -> date:
        return value

    def __getattr__(self, _name: str) -> Callable[..., None]:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


if "streamlit" not in sys.modules and importlib.util.find_spec("streamlit") is None:
    sys.modules["streamlit"] = _StreamlitStub()


def _posix_marker_path(
    *,
    os_name: str | None = None,
    home: str | Path | None = None,
    localappdata: str | Path | None = None,
) -> Path:
    """Test-only marker resolver that always lives under ``HOME``.

    Production code stores ``.agilab-path`` under ``%LOCALAPPDATA%\\agilab`` on
    Windows, but the test suite seeds the posix-style location under the fake
    home directory.  Honouring that path on every platform keeps tests that
    only override ``HOME`` portable across operating systems.
    """

    if home is not None:
        root = Path(home)
    else:
        root = Path(os.environ.get("HOME", str(Path.home())))
    return root / ".local/share/agilab/.agilab-path"


@pytest.fixture(autouse=True)
def isolate_agi_env_test_environment(tmp_path_factory, monkeypatch):
    """Keep agi-env tests independent from developer-local AGILAB state."""

    monkeypatch.setattr(Path, "home", staticmethod(_home_from_env))

    fake_home = tmp_path_factory.mktemp("agilab_fake_home")
    fake_agilab = fake_home / ".agilab"
    fake_localappdata = fake_home / "AppData" / "Local"
    fake_agilab.mkdir(parents=True)
    fake_localappdata.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOMEDRIVE", str(fake_home.drive) if fake_home.drive else "")
    monkeypatch.setenv("HOMEPATH", str(fake_home)[len(fake_home.drive):] if fake_home.drive else str(fake_home))
    monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))
    monkeypatch.setenv("APPDATA", str(fake_home / "AppData" / "Roaming"))
    monkeypatch.delenv("AGI_CLUSTER_ENABLED", raising=False)
    monkeypatch.setenv("AGI_CLUSTER_SHARE", "")
    monkeypatch.setenv("AGI_LOCAL_SHARE", "")
    monkeypatch.delenv("APPS_REPOSITORY", raising=False)
    monkeypatch.delenv("APPS_PATH", raising=False)
    monkeypatch.delenv("AGILAB_LOG_ABS", raising=False)
    monkeypatch.delenv("CLUSTER_CREDENTIALS", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

    repo_agilab_dir = Path(__file__).resolve().parents[3]
    share_dir = fake_home / ".local" / "share" / "agilab"
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / ".agilab-path").write_text(str(repo_agilab_dir) + "\n", encoding="utf-8")
    (fake_localappdata / "agilab").mkdir(parents=True, exist_ok=True)
    (fake_localappdata / "agilab" / ".agilab-path").write_text(
        str(repo_agilab_dir) + "\n",
        encoding="utf-8",
    )
    (fake_agilab / ".env").write_text(
        "AGI_CLUSTER_SHARE=\nAGI_LOCAL_SHARE=\nAPPS_REPOSITORY=\n",
        encoding="utf-8",
    )

    from agi_env import AgiEnv
    from agi_env import ui_support
    from agi_env import agi_env as _agi_env_module

    monkeypatch.setattr(_agi_env_module, "installation_marker_path", _posix_marker_path)

    original_logger = AgiEnv.logger
    original_global_state_file = ui_support._GLOBAL_STATE_FILE
    original_legacy_last_app_file = ui_support._LEGACY_LAST_APP_FILE
    AgiEnv.reset()
    AgiEnv.resources_path = fake_agilab
    AgiEnv.envars = {}
    yield
    AgiEnv.logger = original_logger
    AgiEnv.reset()
    ui_support._GLOBAL_STATE_FILE = original_global_state_file
    ui_support._LEGACY_LAST_APP_FILE = original_legacy_last_app_file
