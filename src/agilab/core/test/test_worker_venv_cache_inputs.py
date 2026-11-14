"""Lockfiles are authoritative optional worker-cache inputs."""

from pathlib import Path

import pytest

from agi_cluster.agi_distributor import deployment_worker_venv_cache_support as cache


def _cache_project(app, worker):
    return cache._shared_worker_venv_project(
        {"AGILAB_SHARED_WORKER_VENV": "1"},
        active_app=app,
        wenv_abs=worker,
        python_version="3.13",
        run_type="sync",
        options_worker="",
        worker_core_add_specs=[],
        hw_rapids_capable=False,
    )


@pytest.mark.parametrize("owner", ["app", "worker"])
def test_cache_lock_only_change_misses_then_recovers(tmp_path, owner):
    app = tmp_path / "app"
    worker = tmp_path / "worker"
    for path in [app, worker]:
        path.mkdir()
        (path / "pyproject.toml").write_text('[project]\nname="demo"\n')
    baseline = _cache_project(app, worker)
    assert baseline == _cache_project(app, worker)
    lock = (app if owner == "app" else worker) / "uv.lock"
    lock.write_text("version = 1\n")
    locked = _cache_project(app, worker)
    assert locked != baseline
    assert locked == _cache_project(app, worker)
    lock.write_text("version = 1\nrevision = 2\n")
    assert _cache_project(app, worker) not in {baseline, locked}
    lock.unlink()
    assert _cache_project(app, worker) == baseline


def test_cache_lock_read_error_refuses_reuse_then_recovers(tmp_path, monkeypatch):
    app, worker = tmp_path / "app", tmp_path / "worker"
    app.mkdir()
    worker.mkdir()
    baseline = _cache_project(app, worker)
    original = Path.read_bytes

    def unreadable(self):
        if self == app / "uv.lock":
            raise PermissionError("lock unavailable")
        return original(self)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", unreadable)
        with pytest.raises((OSError, RuntimeError), match="lock"):
            _cache_project(app, worker)
    assert _cache_project(app, worker) == baseline
