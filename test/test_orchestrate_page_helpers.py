from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path, PosixPath
from types import SimpleNamespace

from streamlit.errors import StreamlitAPIException


def _load_orchestrate_module():
    module_path = Path("src/agilab/pages/2_▶️ ORCHESTRATE.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_page_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
