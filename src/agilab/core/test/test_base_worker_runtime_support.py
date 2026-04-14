from __future__ import annotations

import builtins
import logging
import sys
import types
from types import SimpleNamespace

import pytest

from agi_node.agi_dispatcher import BaseWorker
from agi_node.agi_dispatcher import base_worker as base_worker_mod
from agi_node.agi_dispatcher import base_worker_runtime_support as runtime_support


def teardown_function(_fn):
    BaseWorker._env = None
    BaseWorker.env = None


def test_capture_logs_and_result_respects_verbosity_and_restores_level():
    test_logger = logging.getLogger("agilab.base_worker_runtime_support")
    test_logger.handlers.clear()
    test_logger.setLevel(logging.ERROR)
    test_logger.propagate = False

    def _logged() -> int:
        test_logger.info("hello")
        return 9

    logs, result = runtime_support.capture_logs_and_result(
        _logged,
        verbosity=1,
        root_logger=test_logger,
    )
    debug_logs, debug_result = runtime_support.capture_logs_and_result(
        _logged,
        verbosity=2,
        root_logger=test_logger,
    )
    warning_logs, warning_result = runtime_support.capture_logs_and_result(
        _logged,
        verbosity=0,
        root_logger=test_logger,
    )

    assert result == 9
    assert debug_result == 9
    assert warning_result == 9
    assert "hello" in logs
    assert debug_logs
    assert warning_logs == ""
    assert test_logger.level == logging.ERROR


def test_exec_command_handles_success_warning_and_failure(tmp_path):
    ok = SimpleNamespace(returncode=0, stderr="", stdout="done")
    warning = SimpleNamespace(returncode=1, stderr="WARNING: notice", stdout="")
    error = SimpleNamespace(returncode=1, stderr="fatal boom", stdout="")
    responses = iter([ok, warning, error])
    errors: list[str] = []
    logger_obj = SimpleNamespace(
        error=lambda message, *args: errors.append(message % args if args else message)
    )

    def _fake_run(*_args, **_kwargs):
        return next(responses)

    assert runtime_support.exec_command(
        "echo ok",
        tmp_path,
        "worker",
        normalize_path_fn=lambda value: str(value),
        subprocess_run=_fake_run,
        logger_obj=logger_obj,
    ) is ok
    assert runtime_support.exec_command(
        "echo warn",
        tmp_path,
        "worker",
        normalize_path_fn=lambda value: str(value),
        subprocess_run=_fake_run,
        logger_obj=logger_obj,
    ) is warning
    with pytest.raises(RuntimeError, match="fatal boom"):
        runtime_support.exec_command(
            "echo fail",
            tmp_path,
            "worker",
            normalize_path_fn=lambda value: str(value),
            subprocess_run=_fake_run,
            logger_obj=logger_obj,
        )

    assert any("warning: worker worker - echo warn" in message for message in errors)
    assert any("WARNING: notice" in message for message in errors)


def test_load_module_and_is_cython_installed(monkeypatch):
    fake_module = types.ModuleType("demo.module")
    fake_module.Target = "loaded"
    original_import = builtins.__import__

    def _fake_import(name, fromlist=(), *args, **kwargs):
        if name in {"demo.module", "demo_worker_cy"}:
            return fake_module
        return original_import(name, fromlist, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    assert runtime_support.load_module("demo.module", "Target") == "loaded"
    env = SimpleNamespace(target_worker="demo_worker", target_worker_class="Target")
    assert runtime_support.is_cython_installed(env) is True

    monkeypatch.setattr(
        builtins,
        "__import__",
        lambda name, fromlist=(), *args, **kwargs: (_ for _ in ()).throw(
            ModuleNotFoundError(name)
        ),
    )

    assert runtime_support.is_cython_installed(env) is False
    with pytest.raises(ModuleNotFoundError, match="module missing.module is not installed"):
        runtime_support.load_module("missing.module", "Target")


def test_baseworker_runtime_wrapper_loading_and_logging(monkeypatch):
    error_logs: list[str] = []
    monkeypatch.setattr(
        base_worker_mod.logger,
        "error",
        lambda message, *args: error_logs.append(str(message % args if args else message)),
    )

    BaseWorker._log_import_error("demo.module", "Target", "target.module")
    assert any("__import__('demo.module'" in message for message in error_logs)
    assert any("getattr('target.module Target')" in message for message in error_logs)

    BaseWorker.env = SimpleNamespace(
        module="demo",
        target_class="Target",
        target_worker="demo_worker",
        target_worker_class="TargetWorker",
    )
    monkeypatch.setitem(sys.modules, "demo.demo", object())
    monkeypatch.setitem(sys.modules, "demo_worker", object())

    loaded_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        BaseWorker,
        "_load_module",
        staticmethod(
            lambda module_name, module_class: loaded_calls.append(
                (module_name, module_class)
            )
            or module_name
        ),
    )

    assert BaseWorker._load_manager() == "demo.demo"
    assert BaseWorker._load_worker(0) == "demo_worker.demo_worker"
    assert BaseWorker._load_worker(2) == "demo_worker_cy"
    assert ("demo.demo", "Target") in loaded_calls
    assert ("demo_worker.demo_worker", "TargetWorker") in loaded_calls
    assert ("demo_worker_cy", "TargetWorker") in loaded_calls


def test_baseworker_runtime_wrappers_delegate(monkeypatch, tmp_path):
    calls: dict[str, object] = {}

    def _fake_capture(func, *args, verbosity=logging.CRITICAL, **kwargs):
        calls["capture"] = (func, args, verbosity, kwargs)
        return "logs", 7

    def _fake_exec(cmd, path, worker, *, normalize_path_fn, logger_obj):
        calls["exec"] = (cmd, path, worker, normalize_path_fn, logger_obj)
        return "exec-result"

    def _fake_load_module(module_name, module_class):
        calls["load_module"] = (module_name, module_class)
        return "module-result"

    def _fake_is_cython_installed(env):
        calls["is_cython_installed"] = env
        return True

    monkeypatch.setattr(base_worker_mod.runtime_support, "capture_logs_and_result", _fake_capture)
    monkeypatch.setattr(base_worker_mod.runtime_support, "exec_command", _fake_exec)
    monkeypatch.setattr(base_worker_mod.runtime_support, "load_module", _fake_load_module)
    monkeypatch.setattr(base_worker_mod.runtime_support, "is_cython_installed", _fake_is_cython_installed)

    def _logged():
        return 7

    assert BaseWorker._get_logs_and_result(_logged, "arg", verbosity=2, demo=True) == ("logs", 7)
    assert calls["capture"] == (_logged, ("arg",), 2, {"demo": True})

    assert BaseWorker._exec("echo ok", tmp_path, "worker-1") == "exec-result"
    exec_call = calls["exec"]
    assert exec_call[0:3] == ("echo ok", tmp_path, "worker-1")
    assert exec_call[3] is base_worker_mod.normalize_path
    assert exec_call[4] is base_worker_mod.logger

    assert BaseWorker._load_module("demo.module", "Target") == "module-result"
    assert calls["load_module"] == ("demo.module", "Target")

    env = SimpleNamespace(target_worker="demo_worker", target_worker_class="Target")
    assert BaseWorker._is_cython_installed(env) is True
    assert calls["is_cython_installed"] is env
