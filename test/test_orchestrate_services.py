from __future__ import annotations

import importlib
from types import SimpleNamespace

from pathlib import Path
import sys
import types


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


orchestrate_services = _import_agilab_module("agilab.orchestrate_services")


def _deps():
    return orchestrate_services.OrchestrateServiceDeps(
        reset_traceback_skip=lambda: None,
        append_log_lines=lambda lines, payload: lines.append(payload),
        extract_result_dict_from_output=lambda raw: None,
        evaluate_service_health_gate=lambda *args, **kwargs: (0, "ok", {}),
        coerce_bool_setting=lambda value, default: default if value is None else bool(value),
        coerce_int_setting=lambda value, default, minimum=0: max(minimum, default if value is None else int(value)),
        coerce_float_setting=lambda value, default, minimum=0.0, maximum=1.0: min(
            maximum,
            max(minimum, default if value is None else float(value)),
        ),
        write_app_settings_toml=lambda path, payload: payload,
        clear_load_toml_cache=lambda: None,
        log_display_max_lines=100,
        install_log_height=320,
    )


def test_ensure_service_session_defaults_preserves_existing_values():
    session_state = {"service_poll_interval": 2.5}

    orchestrate_services.ensure_service_session_defaults(session_state)

    assert session_state["service_poll_interval"] == 2.5
    assert session_state["service_status_cache"] == "idle"
    assert session_state["service_health_cache"] == []


def test_compute_service_mode_uses_expected_bitmask():
    result = orchestrate_services.compute_service_mode(
        {"pool": True, "cython": True, "rapids": True},
        service_enabled=True,
    )

    assert result == 15


def test_resolve_service_health_defaults_uses_coercers():
    deps = _deps()

    resolved = orchestrate_services.resolve_service_health_defaults(
        {"service_health": {"allow_idle": 1, "max_unhealthy": "-3", "max_restart_rate": "3.0"}},
        deps,
    )

    assert resolved == {
        "allow_idle": True,
        "max_unhealthy": 0,
        "max_restart_rate": 1.0,
    }


def test_build_service_snippet_embeds_core_parameters():
    snippet = orchestrate_services.build_service_snippet(
        env=SimpleNamespace(apps_path="/tmp/apps", app="demo"),
        verbose=2,
        service_action="status",
        service_mode=7,
        scheduler='"127.0.0.1:8786"',
        workers="{'127.0.0.1': 1}",
        service_poll_interval=1.5,
        service_shutdown_on_stop=True,
        service_stop_timeout=42.0,
        service_heartbeat_timeout=9.5,
        service_cleanup_done_ttl_hours=24.0,
        service_cleanup_failed_ttl_hours=48.0,
        service_cleanup_heartbeat_ttl_hours=12.0,
        service_cleanup_done_max_files=11,
        service_cleanup_failed_max_files=22,
        service_cleanup_heartbeat_max_files=33,
        args_serialized="foo=1, bar=2",
    )

    assert 'action="status"' in snippet
    assert "mode=7" in snippet
    assert 'APP = "demo"' in snippet
    assert "cleanup_failed_max_files=22" in snippet
    assert "foo=1, bar=2" in snippet
