from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys

import tomllib


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


orchestrate_support = _load_module("agilab.orchestrate_support", "src/agilab/orchestrate_support.py")


def test_write_app_settings_toml_sanitizes_none_and_paths(tmp_path):
    settings_file = tmp_path / "app_settings.toml"
    payload = {
        "args": {
            "data_in": Path("/tmp/input"),
            "unused": None,
            "items": [Path("/tmp/a"), None, "b"],
        }
    }

    sanitized = orchestrate_support.write_app_settings_toml(settings_file, payload)
    written = tomllib.loads(settings_file.read_text(encoding="utf-8"))

    assert sanitized == {"args": {"data_in": "/tmp/input", "items": ["/tmp/a", "b"]}}
    assert written == sanitized


def test_evaluate_service_health_gate_detects_restart_rate():
    code, message, details = orchestrate_support.evaluate_service_health_gate(
        {
            "status": "ok",
            "workers_unhealthy_count": 0,
            "workers_running_count": 2,
            "workers_restarted_count": 2,
        },
        allow_idle=False,
        max_unhealthy=0,
        max_restart_rate=0.5,
    )

    assert code == 5
    assert "restart rate" in message
    assert details["restart_rate"] == 1.0


def test_parse_and_validate_workers_reports_invalid_values():
    errors: list[str] = []

    result = orchestrate_support.parse_and_validate_workers(
        "{'127.0.0.1': 0, '192.168.0.10': 2}",
        is_valid_ip=lambda ip: True,
        on_error=errors.append,
    )

    assert result == {"127.0.0.1": 1}
    assert errors == [
        "All worker capacities must be positive integers. Invalid entries: 127.0.0.1: 0"
    ]


def test_parse_and_validate_scheduler_rejects_invalid_port():
    errors: list[str] = []

    result = orchestrate_support.parse_and_validate_scheduler(
        "127.0.0.1:99999",
        is_valid_ip=lambda ip: ip == "127.0.0.1",
        on_error=errors.append,
    )

    assert result is None
    assert errors == ["The scheduler port in '127.0.0.1:99999' is invalid."]
