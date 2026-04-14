from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path, PosixPath
from types import SimpleNamespace

from streamlit.errors import StreamlitAPIException


def _load_orchestrate_page_helpers_module():
    module_path = Path("src/agilab/orchestrate_page_helpers.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_page_helpers_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_orchestrate_module():
    module_path = Path("src/agilab/pages/2_▶️ ORCHESTRATE.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_page_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_page_helpers_rerun_fragment_or_app_falls_back_on_streamlit_api_error():
    module = _load_orchestrate_page_helpers_module()
    calls: list[tuple[str, object | None]] = []

    def _rerun(*, scope=None):
        calls.append(("rerun", scope))
        if scope == "fragment":
            raise StreamlitAPIException("bad scope")

    module.rerun_fragment_or_app(_rerun, StreamlitAPIException)

    assert calls == [("rerun", "fragment"), ("rerun", None)]


def test_page_helpers_delegate_scheduler_worker_and_safe_eval(monkeypatch):
    module = _load_orchestrate_page_helpers_module()
    captured = {}

    def _fake_scheduler(value, *, is_valid_ip, on_error):
        captured["scheduler"] = (value, is_valid_ip("127.0.0.1"))
        on_error("scheduler-error")
        return "scheduler"

    def _fake_workers(value, *, is_valid_ip, on_error, default_workers=None):
        captured["workers"] = (value, is_valid_ip("127.0.0.1"), default_workers)
        on_error("workers-error")
        return {"127.0.0.1": 2}

    def _fake_safe_eval(expression, expected_type, error_message, *, on_error):
        captured["safe_eval"] = (expression, expected_type, error_message)
        on_error("safe-eval-error")
        return 7

    monkeypatch.setattr(module, "_parse_and_validate_scheduler_impl", _fake_scheduler)
    monkeypatch.setattr(module, "_parse_and_validate_workers_impl", _fake_workers)
    monkeypatch.setattr(module, "_safe_eval_impl", _fake_safe_eval)

    errors: list[str] = []
    assert module.parse_and_validate_scheduler("127.0.0.1:9000", is_valid_ip=lambda ip: ip == "127.0.0.1", on_error=errors.append) == "scheduler"
    assert module.parse_and_validate_workers("127.0.0.1:2", is_valid_ip=lambda ip: ip == "127.0.0.1", on_error=errors.append, default_workers={"a": 1}) == {"127.0.0.1": 2}
    assert module.safe_eval("1 + 1", int, "bad", on_error=errors.append) == 7

    assert captured["scheduler"] == ("127.0.0.1:9000", True)
    assert captured["workers"] == ("127.0.0.1:2", True, {"a": 1})
    assert captured["safe_eval"] == ("1 + 1", int, "bad")
    assert errors == ["scheduler-error", "workers-error", "safe-eval-error"]


def test_page_helpers_looks_like_shared_path_delegates_project_root(monkeypatch, tmp_path):
    module = _load_orchestrate_page_helpers_module()
    captured = {}

    def _fake_impl(path, *, project_root):
        captured["value"] = (path, project_root)
        return True

    monkeypatch.setattr(module, "_looks_like_shared_path_impl", _fake_impl)

    candidate = tmp_path / "clustershare"
    project_root = tmp_path / "repo"

    assert module.looks_like_shared_path(candidate, project_root) is True
    assert captured["value"] == (candidate, project_root)


def test_update_delete_confirm_state_sets_and_clears_flag(monkeypatch):
    module = _load_orchestrate_module()
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(module, "st", fake_st)

    rerun_needed = module._update_delete_confirm_state(
        "delete_key",
        delete_armed_clicked=True,
        delete_cancel_clicked=False,
    )
    assert rerun_needed is True
    assert fake_st.session_state["delete_key"] is True

    rerun_needed = module._update_delete_confirm_state(
        "delete_key",
        delete_armed_clicked=False,
        delete_cancel_clicked=True,
    )
    assert rerun_needed is True
    assert "delete_key" not in fake_st.session_state

    rerun_needed = module._update_delete_confirm_state(
        "delete_key",
        delete_armed_clicked=False,
        delete_cancel_clicked=False,
    )
    assert rerun_needed is False


def test_is_app_installed_requires_manager_and_worker_venvs():
    module = _load_orchestrate_module()

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        active_app = root / "flight_trajectory_project"
        worker_root = root / "wenv" / "flight_trajectory_worker"
        active_app.mkdir(parents=True)
        worker_root.mkdir(parents=True)

        env = SimpleNamespace(active_app=active_app, wenv_abs=worker_root)

        status = module._app_install_status(env)
        assert status["manager_ready"] is False
        assert status["worker_ready"] is False
        assert module._is_app_installed(env) is False

        (active_app / ".venv").mkdir()
        status = module._app_install_status(env)
        assert status["manager_ready"] is True
        assert status["worker_ready"] is False
        assert module._is_app_installed(env) is False

        (worker_root / ".venv").mkdir()
        status = module._app_install_status(env)
        assert status["manager_ready"] is True
        assert status["worker_ready"] is True
        assert module._is_app_installed(env) is True


def test_set_active_app_query_param_ignores_streamlit_api_errors(monkeypatch):
    module = _load_orchestrate_module()

    class _BrokenQueryParams(dict):
        def __setitem__(self, key, value):
            raise StreamlitAPIException("no runtime")

    monkeypatch.setattr(module, "st", SimpleNamespace(query_params=_BrokenQueryParams()))

    module._set_active_app_query_param("demo_project")


def test_clear_cached_distribution_calls_clear_when_available():
    module = _load_orchestrate_module()
    called = {"count": 0}
    module.load_distribution.clear = lambda: called.__setitem__("count", called["count"] + 1)

    module._clear_cached_distribution()

    assert called["count"] == 1


def test_clear_mount_table_cache_calls_cache_clear_when_available(monkeypatch):
    module = _load_orchestrate_module()
    called = {"count": 0}
    monkeypatch.setattr(module, "_mount_table", SimpleNamespace(cache_clear=lambda: called.__setitem__("count", called["count"] + 1)))

    module._clear_mount_table_cache()

    assert called["count"] == 1


def test_resolve_share_candidate_falls_back_when_resolve_fails(monkeypatch):
    module = _load_orchestrate_module()

    class _BrokenPath(PosixPath):

        def resolve(self, strict=False):
            raise OSError("broken link")

    monkeypatch.setattr(module, "Path", _BrokenPath)

    resolved = module._resolve_share_candidate("clustershare", "/home/agi")

    assert str(resolved) == "/home/agi/clustershare"


def test_benchmark_display_date_uses_mtime_fallback(tmp_path: Path, monkeypatch):
    module = _load_orchestrate_module()
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(os.path, "getmtime", lambda _path: 0)

    date_value = module._benchmark_display_date(benchmark, "")

    assert date_value == module.datetime.fromtimestamp(0).strftime("%Y-%m-%d %H:%M:%S")


def test_benchmark_display_date_returns_empty_string_when_stat_fails(tmp_path: Path, monkeypatch):
    module = _load_orchestrate_module()
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text("{}", encoding="utf-8")

    def _raise_stat(_path):
        raise OSError("missing")

    monkeypatch.setattr(os.path, "getmtime", _raise_stat)

    date_value = module._benchmark_display_date(benchmark, "")

    assert date_value == ""
