from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace


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
