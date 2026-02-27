from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "service_health_check.py"
SPEC = importlib.util.spec_from_file_location("service_health_check", MODULE_PATH)
assert SPEC and SPEC.loader
service_health_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service_health_check)


class _DummyEnv:
    def __init__(self, apps_path, app, verbose=0):
        self.apps_path = Path(apps_path)
        self.app = app
        self.verbose = verbose


def test_service_health_check_ok(monkeypatch):
    async def _serve(_env, **_kwargs):
        return {"status": "running", "workers_unhealthy_count": 0}

    monkeypatch.setattr(service_health_check, "AgiEnv", _DummyEnv)
    monkeypatch.setattr(service_health_check.AGI, "serve", staticmethod(_serve))

    code = service_health_check.main(["--app", "mycode_project"])
    assert code == 0


def test_service_health_check_fails_when_unhealthy(monkeypatch):
    async def _serve(_env, **_kwargs):
        return {"status": "running", "workers_unhealthy_count": 3}

    monkeypatch.setattr(service_health_check, "AgiEnv", _DummyEnv)
    monkeypatch.setattr(service_health_check.AGI, "serve", staticmethod(_serve))

    code = service_health_check.main(["--app", "mycode_project"])
    assert code == 2


def test_service_health_check_idle_requires_allow_idle(monkeypatch):
    async def _serve(_env, **_kwargs):
        return {"status": "idle", "workers_unhealthy_count": 0}

    monkeypatch.setattr(service_health_check, "AgiEnv", _DummyEnv)
    monkeypatch.setattr(service_health_check.AGI, "serve", staticmethod(_serve))

    code = service_health_check.main(["--app", "mycode_project"])
    assert code == 4


def test_service_health_check_idle_allowed(monkeypatch):
    async def _serve(_env, **_kwargs):
        return {"status": "idle", "workers_unhealthy_count": 0}

    monkeypatch.setattr(service_health_check, "AgiEnv", _DummyEnv)
    monkeypatch.setattr(service_health_check.AGI, "serve", staticmethod(_serve))

    code = service_health_check.main(["--app", "mycode_project", "--allow-idle"])
    assert code == 0


def test_service_health_check_forwards_output_path(monkeypatch, tmp_path):
    captured = {}

    async def _serve(_env, **kwargs):
        captured.update(kwargs)
        return {"status": "running", "workers_unhealthy_count": 0}

    output_path = tmp_path / "health.json"
    monkeypatch.setattr(service_health_check, "AgiEnv", _DummyEnv)
    monkeypatch.setattr(service_health_check.AGI, "serve", staticmethod(_serve))

    code = service_health_check.main(
        [
            "--app",
            "mycode_project",
            "--health-output-path",
            str(output_path),
        ]
    )
    assert code == 0
    assert captured.get("action") == "health"
    assert captured.get("health_output_path") == str(output_path)
