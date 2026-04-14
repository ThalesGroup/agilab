from __future__ import annotations

import asyncio
import io
import json
import pickle
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_cluster.agi_distributor import runtime_misc_support


def test_ensure_asyncio_run_signature_patches_pydevd_shim():
    def _fake_run(main, debug=None):
        return ("orig", main, debug)

    _fake_run.__module__ = "pydevd.fake"
    fake_asyncio = SimpleNamespace(
        run=_fake_run,
        set_event_loop=lambda _loop: None,
    )

    runtime_misc_support.ensure_asyncio_run_signature(asyncio_module=fake_asyncio)

    patched = fake_asyncio.run
    assert patched is not _fake_run
    assert patched("task", debug=True) == ("orig", "task", True)

    async def _coro():
        return 7

    assert patched(_coro(), loop_factory=asyncio.new_event_loop) == 7


def test_ensure_asyncio_run_signature_tolerates_event_loop_runtime_errors():
    def _fake_run(main, debug=None):
        return ("orig", main, debug)

    _fake_run.__module__ = "pydevd.fake"
    set_calls = []

    def _fake_set_event_loop(loop):
        set_calls.append(loop)
        raise RuntimeError("loop policy locked")

    fake_asyncio = SimpleNamespace(
        run=_fake_run,
        set_event_loop=_fake_set_event_loop,
    )

    runtime_misc_support.ensure_asyncio_run_signature(asyncio_module=fake_asyncio)

    class _Loop:
        def __init__(self):
            self.debug = None
            self.closed = False
            self.awaited = []

        def set_debug(self, value):
            self.debug = value

        def run_until_complete(self, main):
            self.awaited.append(main)
            return "done"

        def close(self):
            self.closed = True

    loop = _Loop()
    patched = fake_asyncio.run
    assert patched("task", debug=True, loop_factory=lambda: loop) == "done"
    assert loop.debug is True
    assert loop.closed is True
    assert set_calls == [loop, None]


def test_ensure_asyncio_run_signature_leaves_non_pydevd_shim_untouched():
    def _fake_run(main, debug=None):
        return ("orig", main, debug)

    _fake_run.__module__ = "custom.runner"
    fake_asyncio = SimpleNamespace(
        run=_fake_run,
        set_event_loop=lambda _loop: None,
    )

    runtime_misc_support.ensure_asyncio_run_signature(asyncio_module=fake_asyncio)

    assert fake_asyncio.run is _fake_run


def test_ensure_asyncio_run_signature_handles_uninspectable_run():
    def _fake_run(main, debug=None):
        return ("orig", main, debug)

    fake_asyncio = SimpleNamespace(
        run=_fake_run,
        set_event_loop=lambda _loop: None,
    )

    runtime_misc_support.ensure_asyncio_run_signature(
        asyncio_module=fake_asyncio,
        inspect_signature_fn=lambda *_a, **_k: (_ for _ in ()).throw(ValueError("no signature")),
    )

    assert fake_asyncio.run is _fake_run


def test_agi_version_missing_on_pypi_detection(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)

    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False

    pyproject = project / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo'\n", encoding="utf-8")
    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False

    pyproject.write_text('agi-core = "==1.2.3"\n', encoding="utf-8")

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return io.StringIO(json.dumps(self._payload))

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        runtime_misc_support.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Resp({"releases": {"1.2.3": [{}]}}),
    )
    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False

    monkeypatch.setattr(
        runtime_misc_support.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Resp({"releases": {"1.2.4": [{}]}}),
    )
    assert runtime_misc_support.agi_version_missing_on_pypi(project) is True

    monkeypatch.setattr(
        runtime_misc_support.urllib.request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(urllib.error.URLError("network down")),
    )
    assert runtime_misc_support.agi_version_missing_on_pypi(project) is False


def test_agi_version_missing_on_pypi_propagates_unexpected_lookup_bug(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "pyproject.toml").write_text('agi-core = "==1.2.3"\n', encoding="utf-8")

    monkeypatch.setattr(
        runtime_misc_support.urllib.request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("programmer bug")),
    )

    with pytest.raises(RuntimeError, match="programmer bug"):
        runtime_misc_support.agi_version_missing_on_pypi(project)


def test_format_exception_chain_compacts_causes():
    try:
        try:
            raise ValueError("inner")
        except ValueError as exc:
            raise RuntimeError("RuntimeError: inner") from exc
    except Exception as exc:
        text = runtime_misc_support.format_exception_chain(exc)

    assert "inner" in text
    assert ("RuntimeError" in text) or ("ValueError" in text)


def test_format_exception_chain_strips_generic_error_prefixes():
    class CustomError(Exception):
        pass

    text = runtime_misc_support.format_exception_chain(CustomError("CustomError: precise detail"))

    assert text.endswith("CustomError: precise detail")


def test_load_capacity_predictor_returns_loaded_value(tmp_path):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda stream: {"size": len(stream.read())},
    )

    assert loaded == {"size": len(b"pickle-bytes")}


def test_load_capacity_predictor_retrains_when_missing(tmp_path):
    calls = {"retrain": 0}

    loaded = runtime_misc_support.load_capacity_predictor(
        tmp_path / "missing.pkl",
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
    )

    assert loaded is None
    assert calls["retrain"] == 1


def test_load_capacity_predictor_handles_legacy_module_error(tmp_path):
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"pickle-bytes")
    calls = {"retrain": 0, "warnings": []}
    log = SimpleNamespace(warning=lambda message, path, exc: calls["warnings"].append((message, path, str(exc))))

    loaded = runtime_misc_support.load_capacity_predictor(
        model_path,
        load_fn=lambda _stream: (_ for _ in ()).throw(ModuleNotFoundError("numpy.core.numeric")),
        retrain_fn=lambda: calls.__setitem__("retrain", calls["retrain"] + 1),
        log=log,
    )

    assert loaded is None
    assert calls["retrain"] == 1
    assert calls["warnings"]
    assert "numpy.core.numeric" in calls["warnings"][0][2]


def test_hardware_supports_rapids_true_and_false(monkeypatch):
    monkeypatch.setattr(runtime_misc_support.subprocess, "run", lambda *_a, **_k: None)
    assert runtime_misc_support.hardware_supports_rapids() is True

    monkeypatch.setattr(
        runtime_misc_support.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("nvidia-smi missing")),
    )
    assert runtime_misc_support.hardware_supports_rapids() is False


def test_should_install_pip_checks_user_and_scripts_path(tmp_path):
    assert runtime_misc_support.should_install_pip(
        getuser_fn=lambda: "agi",
        sys_prefix=str(tmp_path),
    ) is False

    assert runtime_misc_support.should_install_pip(
        getuser_fn=lambda: "T01234",
        sys_prefix=str(tmp_path),
    ) is True

    scripts_dir = tmp_path / "Scripts"
    scripts_dir.mkdir()
    (scripts_dir / "pip.exe").write_text("", encoding="utf-8")
    assert runtime_misc_support.should_install_pip(
        getuser_fn=lambda: "T01234",
        sys_prefix=str(tmp_path),
    ) is False


def test_format_elapsed_uses_precisedelta_callback():
    text = runtime_misc_support.format_elapsed(
        12.5,
        precisedelta_fn=lambda delta: f"{delta.total_seconds():.1f}s",
    )

    assert text == "12.5s"
