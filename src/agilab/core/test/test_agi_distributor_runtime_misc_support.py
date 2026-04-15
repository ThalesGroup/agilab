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


def test_bootstrap_capacity_predictor_sets_paths_and_logs_missing_model(tmp_path):
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(resources_path=tmp_path / "resources")
    env.resources_path.mkdir(parents=True, exist_ok=True)
    calls = {"info": []}
    log = SimpleNamespace(info=lambda message, path: calls["info"].append((message, path)))

    predictor = runtime_misc_support.bootstrap_capacity_predictor(
        agi_cls,
        env,
        missing_log_message="Capacity model not found at %s; skipping bootstrap.",
        log=log,
    )

    assert predictor is None
    assert agi_cls._capacity_predictor is None
    assert agi_cls._capacity_data_file == env.resources_path / "balancer_df.csv"
    assert agi_cls._capacity_model_file == env.resources_path / "balancer_model.pkl"
    assert calls["info"] == [
        ("Capacity model not found at %s; skipping bootstrap.", agi_cls._capacity_model_file)
    ]


def test_initialize_runtime_state_sets_common_runtime_fields():
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(manager_path=Path("/tmp/manager"), target="demo", verbose=1)
    calls = {"info": []}
    log = SimpleNamespace(info=lambda message, target, verbose: calls["info"].append((message, target, verbose)))

    runtime_misc_support.initialize_runtime_state(
        agi_cls,
        env,
        workers={"127.0.0.1": 1},
        verbose=2,
        rapids_enabled=True,
        args={"secret": 1},
        workers_data_path="/tmp/data",
        args_transform_fn=lambda args: {"public": args["secret"]},
        log=log,
        log_message="runtime for %s v%s",
    )

    assert agi_cls.env is env
    assert agi_cls.target_path == env.manager_path
    assert agi_cls._target == "demo"
    assert agi_cls._rapids_enabled is True
    assert agi_cls._args == {"public": 1}
    assert agi_cls.verbose == 2
    assert agi_cls._workers == {"127.0.0.1": 1}
    assert agi_cls._workers_data_path == "/tmp/data"
    assert agi_cls._run_time == {}
    assert calls["info"] == [("runtime for %s v%s", "demo", 1)]


def test_configure_runtime_mode_supports_default_dask_mode():
    agi_cls = SimpleNamespace(_RUN_MASK=0b001111, RAPIDS_MODE=16, DASK_MODE=4)
    env = SimpleNamespace(mode2int=lambda value: {"d": 4}[value])

    mode = runtime_misc_support.configure_runtime_mode(
        agi_cls,
        env,
        None,
        default_mode=agi_cls.DASK_MODE,
        require_dask=True,
    )

    assert mode == 4
    assert agi_cls._mode == 4
    assert agi_cls._run_types[0] == "run --no-sync"


def test_configure_runtime_mode_rejects_invalid_type_with_custom_message():
    agi_cls = SimpleNamespace(_RUN_MASK=0b001111, RAPIDS_MODE=16, DASK_MODE=4)
    env = SimpleNamespace(mode2int=lambda value: value)

    with pytest.raises(ValueError, match="parameter <mode> must be an int, a list of int or a string"):
        runtime_misc_support.configure_runtime_mode(
            agi_cls,
            env,
            ["d"],
            invalid_type_message="parameter <mode> must be an int, a list of int or a string",
        )


def test_resolve_install_worker_group_supports_sb3_alias_without_import():
    assert (
        runtime_misc_support.resolve_install_worker_group(
            "Sb3TrainerWorker",
            base_worker_module="sb3_trainer_worker",
        )
        == "dag-worker"
    )


def test_resolve_install_worker_group_walks_inherited_worker_mro():
    class DagWorker:
        pass

    class CustomWorker(DagWorker):
        pass

    fake_module = SimpleNamespace(CustomWorker=CustomWorker)

    assert (
        runtime_misc_support.resolve_install_worker_group(
            "CustomWorker",
            base_worker_module="custom_worker",
            import_module_fn=lambda _name: fake_module,
        )
        == "dag-worker"
    )


def test_configure_install_worker_group_sets_resolved_alias_on_agi_cls():
    agi_cls = SimpleNamespace()
    env = SimpleNamespace(
        base_worker_cls="Sb3TrainerWorker",
        _base_worker_module="sb3_trainer_worker",
    )

    worker_group = runtime_misc_support.configure_install_worker_group(agi_cls, env)

    assert worker_group == "dag-worker"
    assert agi_cls.install_worker_group == ["dag-worker"]
    assert agi_cls.agi_workers["DagWorker"] == "dag-worker"


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
