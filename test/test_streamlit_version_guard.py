from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path("src/agilab/streamlit_version_guard.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("agilab_streamlit_version_guard_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_streamlit_version_guard_accepts_156_and_newer() -> None:
    streamlit_version_guard = _load_module()

    assert streamlit_version_guard.is_streamlit_version_supported("1.56.0") is True
    assert streamlit_version_guard.is_streamlit_version_supported("1.57.1") is True


def test_streamlit_version_guard_rejects_older_versions() -> None:
    streamlit_version_guard = _load_module()

    assert streamlit_version_guard.is_streamlit_version_supported("1.55.9") is False
    assert streamlit_version_guard.is_streamlit_version_supported("") is False


def test_require_streamlit_min_version_stops_with_actionable_message() -> None:
    streamlit_version_guard = _load_module()
    messages: list[str] = []
    commands: list[str] = []

    class _Stop(RuntimeError):
        pass

    fake_st = SimpleNamespace(
        __version__="1.55.0",
        error=lambda message: messages.append(str(message)),
        code=lambda command, language=None: commands.append(f"{language}:{command}"),
        stop=lambda: (_ for _ in ()).throw(_Stop("stopped")),
    )

    with pytest.raises(_Stop):
        streamlit_version_guard.require_streamlit_min_version(fake_st, runtime_label="Test UI")

    assert "Test UI requires Streamlit >= 1.56.0" in messages[0]
    assert "Streamlit 1.55.0" in messages[0]
    assert commands == [
        "bash:uv --preview-features extra-build-dependencies sync --upgrade-package streamlit"
    ]


def test_require_streamlit_min_version_raises_without_streamlit_error_api() -> None:
    streamlit_version_guard = _load_module()
    fake_st = SimpleNamespace(__version__="1.55.0")

    with pytest.raises(RuntimeError, match="requires Streamlit >= 1.56.0"):
        streamlit_version_guard.require_streamlit_min_version(fake_st)
