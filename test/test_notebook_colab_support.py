from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "notebook_colab_support.py"
MODULE_SPEC = importlib.util.spec_from_file_location("agilab.notebook_colab_support", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
colab_support = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = colab_support
MODULE_SPEC.loader.exec_module(colab_support)


def test_ensure_pathlib_unsupported_operation_injects_fallback():
    fake_pathlib = SimpleNamespace()

    colab_support.ensure_pathlib_unsupported_operation(fake_pathlib)

    assert fake_pathlib.UnsupportedOperation is colab_support.IOUnsupportedOperation


def test_prepend_sys_path_entries_deduplicates(monkeypatch, tmp_path: Path):
    existing = str(tmp_path / "existing")
    fresh = tmp_path / "fresh"
    monkeypatch.setattr(colab_support.sys, "path", [existing])

    colab_support.prepend_sys_path_entries([fresh, Path(existing)])

    assert colab_support.sys.path[0] == str(fresh)
    assert colab_support.sys.path.count(existing) == 1


def test_worker_venv_path_uses_target_name(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(colab_support.Path, "home", staticmethod(lambda: tmp_path))

    path = colab_support.worker_venv_path(SimpleNamespace(target="demo", app="demo"))

    assert path == tmp_path / "wenv" / "demo_worker" / ".venv"


@pytest.mark.asyncio
async def test_install_if_needed_skips_existing_worker(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(colab_support.Path, "home", staticmethod(lambda: tmp_path))
    existing = tmp_path / "wenv" / "demo_worker" / ".venv"
    existing.mkdir(parents=True, exist_ok=True)
    calls: list[tuple] = []

    class _AGI:
        @staticmethod
        async def install(*args, **kwargs):
            calls.append((args, kwargs))

    installed = await colab_support.install_if_needed(
        _AGI,
        SimpleNamespace(target="demo", app="demo"),
    )

    assert installed is False
    assert calls == []


@pytest.mark.asyncio
async def test_install_if_needed_runs_install_when_worker_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(colab_support.Path, "home", staticmethod(lambda: tmp_path))
    calls: list[tuple] = []
    messages: list[str] = []
    env = SimpleNamespace(target="demo", app="demo")

    class _AGI:
        @staticmethod
        async def install(*args, **kwargs):
            calls.append((args, kwargs))

    installed = await colab_support.install_if_needed(
        _AGI,
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        modes_enabled=0,
        print_fn=messages.append,
    )

    assert installed is True
    assert messages == ["Installing worker for demo..."]
    assert calls == [((env,), {"scheduler": "127.0.0.1", "workers": {"127.0.0.1": 1}, "modes_enabled": 0})]
