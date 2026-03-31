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


def test_sanitize_for_toml_recursively_drops_none_and_converts_tuples():
    payload = {
        "a": None,
        "b": (Path("/tmp/x"), None, {"nested": None, "kept": Path("/tmp/y")}),
    }

    assert orchestrate_support.sanitize_for_toml(payload) == {
        "b": ["/tmp/x", {"kept": "/tmp/y"}]
    }


def test_extract_result_dict_from_output_uses_last_valid_dict():
    raw_output = "\n".join(
        [
            "plain log line",
            "{'ignored': 'first'}",
            "not a dict",
            "{'result': 42, 'status': 'ok'}",
        ]
    )

    assert orchestrate_support.extract_result_dict_from_output(raw_output) == {
        "result": 42,
        "status": "ok",
    }


def test_extract_result_dict_from_output_returns_none_for_non_dict_payload():
    raw_output = "\n".join(["[]", "still no dict", "{invalid"])

    assert orchestrate_support.extract_result_dict_from_output(raw_output) is None


def test_parse_benchmark_normalizes_numeric_keys():
    parsed = orchestrate_support.parse_benchmark("{1: {'score': 2}, 'name': 'ok'}")

    assert parsed == {1: {"score": 2}, "name": "ok"}


def test_coerce_setting_helpers_cover_string_and_bounds():
    assert orchestrate_support.coerce_bool_setting("YES", False) is True
    assert orchestrate_support.coerce_bool_setting("off", True) is False
    assert orchestrate_support.coerce_int_setting("-5", 3, minimum=0) == 0
    assert orchestrate_support.coerce_int_setting("bad", 3, minimum=0) == 3
    assert orchestrate_support.coerce_float_setting("9.2", 0.3, maximum=1.0) == 1.0
    assert orchestrate_support.coerce_float_setting("-1", 0.3, minimum=0.0) == 0.0


def test_safe_eval_reports_type_mismatch():
    errors: list[str] = []

    result = orchestrate_support.safe_eval(
        "['not', 'a', 'dict']",
        dict,
        "bad type",
        on_error=errors.append,
    )

    assert result is None
    assert errors == ["bad type"]


def test_parse_and_validate_workers_rejects_invalid_ips():
    errors: list[str] = []

    result = orchestrate_support.parse_and_validate_workers(
        "{'bad-host': 2}",
        is_valid_ip=lambda ip: ip == "127.0.0.1",
        on_error=errors.append,
        default_workers={"127.0.0.1": 1},
    )

    assert result == {"127.0.0.1": 1}
    assert errors == ["The following worker IPs are invalid: bad-host"]


def test_looks_like_shared_path_uses_shared_filesystem_hint(monkeypatch, tmp_path):
    share_path = tmp_path / "share"
    project_root = tmp_path / "project"

    monkeypatch.setattr(orchestrate_support, "fstype_for_path", lambda path: "nfs")

    assert orchestrate_support.looks_like_shared_path(share_path, project_root=project_root) is True


def test_looks_like_shared_path_rejects_paths_under_project_root(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    candidate = project_root / "data"
    candidate.mkdir(parents=True)

    monkeypatch.setattr(orchestrate_support, "fstype_for_path", lambda path: None)

    assert orchestrate_support.looks_like_shared_path(candidate, project_root=project_root) is False
