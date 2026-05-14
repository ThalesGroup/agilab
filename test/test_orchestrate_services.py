from __future__ import annotations

import asyncio
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


def test_service_mode_flags_and_defaults_are_named_constants():
    assert orchestrate_services.SERVICE_MODE_POOL == 1
    assert orchestrate_services.SERVICE_MODE_CYTHON == 2
    assert orchestrate_services.SERVICE_MODE_ENABLED == 4
    assert orchestrate_services.SERVICE_MODE_RAPIDS == 8
    assert orchestrate_services.SERVICE_SESSION_DEFAULTS["service_cleanup_done_ttl_hours"] == (
        orchestrate_services.DEFAULT_SERVICE_CLEANUP_DONE_TTL_HOURS
    )
    assert orchestrate_services.SERVICE_SESSION_DEFAULTS["service_cleanup_failed_ttl_hours"] == (
        orchestrate_services.DEFAULT_SERVICE_CLEANUP_FAILED_TTL_HOURS
    )
    assert orchestrate_services.SERVICE_SESSION_DEFAULTS["service_cleanup_heartbeat_ttl_hours"] == (
        orchestrate_services.DEFAULT_SERVICE_CLEANUP_HEARTBEAT_TTL_HOURS
    )


def test_service_health_gate_key_helpers_initialize_session_state():
    keys = orchestrate_services.service_health_gate_keys("demo")
    session_state = {}

    returned = orchestrate_services.ensure_service_health_gate_defaults(
        session_state,
        app="demo",
        defaults={
            "allow_idle": False,
            "max_unhealthy": 2,
            "max_restart_rate": 0.5,
        },
    )

    assert returned == keys
    assert session_state == {
        "service_health_allow_idle__demo": False,
        "service_health_max_unhealthy__demo": 2,
        "service_health_max_restart_rate__demo": 0.5,
    }


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


def test_resolve_service_health_defaults_ignores_non_mapping_settings():
    deps = _deps()

    resolved = orchestrate_services.resolve_service_health_defaults(
        {"service_health": "not-a-dict"},
        deps,
    )

    assert resolved == {
        "allow_idle": False,
        "max_unhealthy": 0,
        "max_restart_rate": 0.25,
    }


def test_build_service_snippet_embeds_core_parameters():
    snippet = orchestrate_services.build_service_snippet(
        env=SimpleNamespace(apps_path="/tmp/apps", app="demo", is_source_env=False),
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


def test_build_service_snippet_preserves_builtin_apps_path(tmp_path):
    apps_path = tmp_path / "apps"
    builtin_apps = apps_path / "builtin"
    (builtin_apps / "flight_telemetry_project").mkdir(parents=True)

    snippet = orchestrate_services.build_service_snippet(
        env=SimpleNamespace(apps_path=apps_path, app="flight_telemetry_project", is_source_env=True),
        verbose=2,
        service_action="status",
        service_mode=7,
        scheduler="None",
        workers="None",
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
        args_serialized="",
    )

    assert f'APPS_PATH = "{builtin_apps}"' in snippet


def test_build_service_snippet_does_not_inject_source_core_paths_for_source_env():
    snippet = orchestrate_services.build_service_snippet(
        env=SimpleNamespace(apps_path="/repo/src/agilab/apps", app="demo", is_source_env=True),
        verbose=2,
        service_action="status",
        service_mode=7,
        scheduler="None",
        workers="None",
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
        args_serialized="foo=1",
    )

    assert "import sys" not in snippet
    assert "from pathlib import Path" not in snippet
    assert "def _inject_source_core_paths() -> None:" not in snippet

def test_build_service_operator_summary_counts_health_state_and_gate_values():
    summary = orchestrate_services.build_service_operator_summary(
        status="running",
        worker_health=[
            {
                "worker": "w1",
                "healthy": False,
                "reason": "timeout",
                "heartbeat_state": "late",
                "heartbeat_age_sec": 12.5,
            },
            {
                "worker": "w2",
                "healthy": True,
                "reason": "",
                "heartbeat_state": "missing",
                "heartbeat_age_sec": 2.0,
            },
            "bad-row",
        ],
        allow_idle=False,
        max_unhealthy=0,
        max_restart_rate=0.25,
        heartbeat_timeout_sec=10.0,
    )

    assert summary["tracked_workers"] == 2
    assert summary["unhealthy_workers"] == 1
    assert summary["late_heartbeats"] == 1
    assert summary["missing_heartbeats"] == 1
    assert summary["max_heartbeat_age_sec"] == 12.5
    assert summary["reason_examples"] == ["timeout"]
    assert any("Status: `running`" in line for line in summary["lines"])
    assert any("max_restart_rate=0.25" in line for line in summary["lines"])


def test_build_service_operator_snapshot_and_path_are_compact_and_stable(tmp_path):
    snapshot = orchestrate_services.build_service_operator_snapshot(
        app="demo_project",
        target="demo",
        status="running",
        worker_health=[{"worker": "w1", "healthy": True, "heartbeat_state": "fresh"}],
        allow_idle=False,
        max_unhealthy=0,
        max_restart_rate=0.25,
        heartbeat_timeout_sec=10.0,
    )

    path = orchestrate_services.service_operator_snapshot_path("demo", home_dir=tmp_path)

    assert path == tmp_path / "log" / "execute" / "demo" / "service_operator_snapshot.json"
    assert snapshot["schema"] == "agilab.service.operator_snapshot.v1"
    assert snapshot["app"] == "demo_project"
    assert snapshot["target"] == "demo"
    assert snapshot["health_gate"]["max_unhealthy"] == 0
    assert snapshot["summary"]["tracked_workers"] == 1


def test_build_orchestrate_service_state_blocks_actions_when_cluster_disabled():
    state = orchestrate_services.build_orchestrate_service_state(
        session_state={},
        cluster_params={"cluster_enabled": False, "pool": True},
        allow_idle=False,
        max_unhealthy=0,
        max_restart_rate=0.25,
        heartbeat_timeout_sec=10.0,
    )

    assert state.enabled is False
    assert state.mode == 1
    assert state.status is orchestrate_services.ServiceWorkflowStatus.DISABLED
    assert state.available_actions == ()
    assert state.blocked_actions[orchestrate_services.OrchestrateServiceAction.START].startswith(
        "Enable Cluster"
    )
    assert state.summary["tracked_workers"] == 0


def test_build_orchestrate_service_state_classifies_running_degraded_and_snapshot():
    state = orchestrate_services.build_orchestrate_service_state(
        session_state={
            "service_status_cache": "running",
            "service_health_cache": [
                {"worker": "w1", "healthy": True, "heartbeat_state": "fresh"},
                {"worker": "w2", "healthy": False, "reason": "timeout", "heartbeat_state": "late"},
                "bad-row",
            ],
            "service_snapshot_path_cache": "/tmp/service_operator_snapshot.json",
        },
        cluster_params={"cluster_enabled": True, "pool": True, "cython": True},
        allow_idle=False,
        max_unhealthy=0,
        max_restart_rate=0.25,
        heartbeat_timeout_sec=10.0,
    )

    assert state.enabled is True
    assert state.mode == 7
    assert state.status is orchestrate_services.ServiceWorkflowStatus.DEGRADED
    assert state.worker_health == (
        {"worker": "w1", "healthy": True, "heartbeat_state": "fresh"},
        {"worker": "w2", "healthy": False, "reason": "timeout", "heartbeat_state": "late"},
    )
    assert orchestrate_services.OrchestrateServiceAction.HEALTH_GATE in state.available_actions
    assert state.blocked_actions == {}
    assert state.snapshot_path == "/tmp/service_operator_snapshot.json"
    assert state.summary["unhealthy_workers"] == 1


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Placeholder:
    def __init__(self):
        self.last_code = None
        self.last_df = None
        self.last_info = None
        self.last_caption = None

    def code(self, value, **kwargs):
        self.last_code = value

    def dataframe(self, value, **kwargs):
        self.last_df = value

    def info(self, value, **kwargs):
        self.last_info = value

    def caption(self, value, **kwargs):
        self.last_caption = value

    def empty(self):
        self.last_code = None
        self.last_df = None
        self.last_info = None
        self.last_caption = None


def _service_st(session_state, *, clicked: str | None = None):
    info_messages = []
    caption_messages = []
    code_blocks = []
    success_messages = []
    warning_messages = []
    error_messages = []
    placeholders = []

    def number_input(_label, **kwargs):
        return kwargs["value"]

    def toggle(_label, **kwargs):
        return kwargs.get("value", session_state.get(kwargs.get("key"), False))

    def selectbox(_label, options, index=0, **kwargs):
        return options[index]

    def columns(count):
        keys = [
            "service_start_btn",
            "service_status_btn",
            "service_health_gate_btn",
            "service_export_btn",
            "service_stop_btn",
        ]

        def make_button(key):
            return SimpleNamespace(button=lambda *_args, **_kwargs: clicked == key)

        return [make_button(keys[idx]) for idx in range(count)]

    def empty():
        holder = _Placeholder()
        placeholders.append(holder)
        return holder

    st = SimpleNamespace(
        session_state=session_state,
        expander=lambda *_args, **_kwargs: _Ctx(),
        spinner=lambda *_args, **_kwargs: _Ctx(),
        info=lambda message: info_messages.append(str(message)),
        number_input=number_input,
        toggle=toggle,
        caption=lambda message: caption_messages.append(str(message)),
        selectbox=selectbox,
        code=lambda value, **kwargs: code_blocks.append(value),
        columns=columns,
        empty=empty,
        success=lambda message: success_messages.append(str(message)),
        warning=lambda message: warning_messages.append(str(message)),
        error=lambda message: error_messages.append(str(message)),
    )
    st._info_messages = info_messages
    st._caption_messages = caption_messages
    st._code_blocks = code_blocks
    st._success_messages = success_messages
    st._warning_messages = warning_messages
    st._error_messages = error_messages
    st._placeholders = placeholders
    return st


def test_render_service_panel_renders_preview_without_actions(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
        }
    )
    fake_st = _service_st(session_state)
    monkeypatch.setattr(orchestrate_services, "st", fake_st)

    env = SimpleNamespace(app="demo", apps_path=tmp_path, app_settings_file=tmp_path / "app_settings.toml")

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": False},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=_deps(),
        )
    )

    assert any("Enable Cluster" in msg for msg in fake_st._info_messages)
    assert any("APP = \"demo\"" in block for block in fake_st._code_blocks)
    assert session_state["service_status_cache"] == "idle"
    assert session_state["service_health_allow_idle__demo"] is False
    assert fake_st._placeholders[2].last_info is not None
    assert "Tracked workers: `0`" in fake_st._placeholders[2].last_info


def test_render_service_panel_health_gate_action(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
        }
    )
    fake_st = _service_st(session_state, clicked="service_health_gate_btn")
    monkeypatch.setattr(orchestrate_services, "st", fake_st)

    health_payload = {
        "status": "running",
        "worker_health": [
            {
                "worker": "w1",
                "healthy": False,
                "reason": "timeout",
                "heartbeat_state": "late",
                "heartbeat_age_sec": 12.5,
            }
        ],
        "restarted_workers": ["w1"],
        "restart_reasons": {"w1": "late heartbeat"},
        "cleanup": {"done": 1, "failed": 0, "heartbeats": 2},
        "heartbeat_timeout_sec": 10.0,
        "health_path": "/tmp/health.json",
    }

    deps = orchestrate_services.OrchestrateServiceDeps(
        reset_traceback_skip=lambda: None,
        append_log_lines=lambda lines, payload: lines.append(payload),
        extract_result_dict_from_output=lambda raw: health_payload,
        evaluate_service_health_gate=lambda *args, **kwargs: (0, "ok", {
            "status": "running",
            "workers_unhealthy_count": 1,
            "workers_restarted_count": 1,
            "workers_running_count": 1,
            "restart_rate": 0.5,
        }),
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

    async def fake_run_agi(*_args, **kwargs):
        callback = kwargs["log_callback"]
        callback("streamed line")
        return ("{'status': 'running'}", "")

    env = SimpleNamespace(
        app="demo",
        apps_path=tmp_path,
        app_settings_file=tmp_path / "app_settings.toml",
        run_agi=fake_run_agi,
        snippet_tail="print('tail')",
    )

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": True, "pool": True, "service_health": {}},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=deps,
        )
    )

    assert session_state["service_status_cache"] == "running"
    assert session_state["service_health_cache"] == health_payload["worker_health"]
    assert any("HEALTH gate passed." in msg for msg in fake_st._success_messages)
    assert any("restart_rate=0.500" in msg for msg in fake_st._caption_messages)
    assert fake_st._placeholders[0].last_code is not None
    assert fake_st._placeholders[1].last_df is not None
    assert fake_st._placeholders[2].last_info is not None
    assert "Unhealthy workers: `1`" in fake_st._placeholders[2].last_info


def test_render_service_panel_source_env_uses_controller_runtime(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
        }
    )
    fake_st = _service_st(session_state, clicked="service_status_btn")
    monkeypatch.setattr(orchestrate_services, "st", fake_st)

    captured: dict[str, object] = {}

    async def fake_run_agi(*_args, **kwargs):
        captured["venv"] = kwargs.get("venv")
        return ("{'status': 'running'}", "")

    env = SimpleNamespace(
        app="demo",
        apps_path=tmp_path,
        app_settings_file=tmp_path / "app_settings.toml",
        run_agi=fake_run_agi,
        snippet_tail="print('tail')",
        is_source_env=True,
        is_worker_env=False,
        agi_cluster=tmp_path / "controller",
    )
    env.agi_cluster.mkdir()

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path / "project",
            cluster_params={"cluster_enabled": True, "pool": True},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=_deps(),
        )
    )

    assert Path(captured["venv"]) == env.agi_cluster


def test_render_service_panel_health_gate_skips_non_mapping_worker_health_rows(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
        }
    )
    fake_st = _service_st(session_state, clicked="service_health_gate_btn")
    monkeypatch.setattr(orchestrate_services, "st", fake_st)

    health_payload = {
        "status": "running",
        "worker_health": [
            "bad-row",
            {
                "worker": "w1",
                "healthy": True,
                "reason": "",
                "heartbeat_state": "fresh",
                "heartbeat_age_sec": 0.5,
            },
        ],
    }

    deps = orchestrate_services.OrchestrateServiceDeps(
        reset_traceback_skip=lambda: None,
        append_log_lines=lambda lines, payload: lines.append(payload),
        extract_result_dict_from_output=lambda raw: health_payload,
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

    async def fake_run_agi(*_args, **_kwargs):
        return ("{'status': 'running'}", "")

    env = SimpleNamespace(
        app="demo",
        apps_path=tmp_path,
        app_settings_file=tmp_path / "app_settings.toml",
        run_agi=fake_run_agi,
        snippet_tail="print('tail')",
    )

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": True, "pool": True, "service_health": {}},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=deps,
        )
    )

    assert session_state["service_health_cache"] == health_payload["worker_health"]
    assert fake_st._placeholders[1].last_df is not None


def test_render_service_panel_handles_status_error_and_cached_health_failures(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
            "service_log_cache": "cached log",
            "service_health_cache": [{"worker": "broken"}],
        }
    )
    fake_st = _service_st(session_state, clicked="service_status_btn")
    monkeypatch.setattr(orchestrate_services, "st", fake_st)
    monkeypatch.setattr(
        orchestrate_services.pd,
        "DataFrame",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("df boom")),
    )

    deps = orchestrate_services.OrchestrateServiceDeps(
        reset_traceback_skip=lambda: None,
        append_log_lines=lambda lines, payload: lines.append(payload),
        extract_result_dict_from_output=lambda raw: {"status": "stopped", "worker_health": "bad"},
        evaluate_service_health_gate=lambda *args, **kwargs: (0, "ok", {}),
        coerce_bool_setting=lambda value, default: default if value is None else bool(value),
        coerce_int_setting=lambda value, default, minimum=0: max(minimum, default if value is None else int(value)),
        coerce_float_setting=lambda value, default, minimum=0.0, maximum=1.0: min(
            maximum,
            max(minimum, default if value is None else float(value)),
        ),
        write_app_settings_toml=lambda path, payload: payload,
        clear_load_toml_cache=lambda: (_ for _ in ()).throw(RuntimeError("cache boom")),
        log_display_max_lines=100,
        install_log_height=320,
    )

    async def fake_run_agi(*_args, **_kwargs):
        return ("{'status': 'stopped'}", "")

    env = SimpleNamespace(
        app="demo",
        apps_path=tmp_path,
        app_settings_file=tmp_path / "app_settings.toml",
        run_agi=fake_run_agi,
        snippet_tail="print('tail')",
    )

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": True, "pool": True},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=deps,
        )
    )

    assert fake_st._placeholders[0].last_code is not None
    assert session_state["service_status_cache"] == "stopped"
    assert session_state["service_health_cache"] == []
    assert any("completed with status 'stopped'" in msg for msg in fake_st._success_messages)


def test_render_service_panel_handles_start_failure_and_health_parse_failure(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
        }
    )

    start_st = _service_st(session_state, clicked="service_start_btn")
    monkeypatch.setattr(orchestrate_services, "st", start_st)

    deps = orchestrate_services.OrchestrateServiceDeps(
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

    async def failing_run_agi(*_args, **_kwargs):
        raise RuntimeError("service boom")

    env = SimpleNamespace(
        app="demo",
        apps_path=tmp_path,
        app_settings_file=tmp_path / "app_settings.toml",
        run_agi=failing_run_agi,
        snippet_tail="print('tail')",
    )

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": True},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=deps,
        )
    )

    assert session_state["service_status_cache"] == "error"
    assert any("failed" in msg for msg in start_st._error_messages)

    health_st = _service_st(session_state, clicked="service_health_gate_btn")
    monkeypatch.setattr(orchestrate_services, "st", health_st)

    async def ok_run_agi(*_args, **_kwargs):
        return ("no parseable payload", "")

    env.run_agi = ok_run_agi

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": True},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=deps,
        )
    )

    assert any("unable to parse service health payload" in msg for msg in health_st._error_messages)


def test_render_service_panel_health_gate_failure_and_stop_action(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
        }
    )
    fake_st = _service_st(session_state, clicked="service_stop_btn")
    monkeypatch.setattr(orchestrate_services, "st", fake_st)

    deps = orchestrate_services.OrchestrateServiceDeps(
        reset_traceback_skip=lambda: None,
        append_log_lines=lambda lines, payload: lines.append(payload),
        extract_result_dict_from_output=lambda raw: {"status": "running"},
        evaluate_service_health_gate=lambda *args, **kwargs: (
            2,
            "too many unhealthy workers",
            {
                "status": "running",
                "workers_unhealthy_count": 2,
                "workers_restarted_count": 0,
                "workers_running_count": 1,
                "restart_rate": 0.0,
            },
        ),
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

    async def fake_run_agi(*_args, **_kwargs):
        return ("{'status': 'running'}", "")

    env = SimpleNamespace(
        app="demo",
        target="demo",
        apps_path=tmp_path,
        app_settings_file=tmp_path / "app_settings.toml",
        run_agi=fake_run_agi,
        snippet_tail="print('tail')",
    )

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": True},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=deps,
        )
    )

    assert any("completed with status 'running'" in msg for msg in fake_st._success_messages)


def test_render_service_panel_exports_operator_snapshot(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
            "service_status_cache": "running",
            "service_health_cache": [
                {
                    "worker": "w1",
                    "healthy": False,
                    "reason": "timeout",
                    "heartbeat_state": "late",
                    "heartbeat_age_sec": 12.5,
                }
            ],
        }
    )
    fake_st = _service_st(session_state, clicked="service_export_btn")
    monkeypatch.setattr(orchestrate_services, "st", fake_st)
    monkeypatch.setattr(orchestrate_services.Path, "home", staticmethod(lambda: tmp_path))

    env = SimpleNamespace(
        app="demo_project",
        target="demo",
        apps_path=tmp_path,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": True, "pool": True, "service_health": {}},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=_deps(),
        )
    )

    expected_path = tmp_path / "log" / "execute" / "demo" / "service_operator_snapshot.json"
    assert expected_path.exists()
    payload = __import__("json").loads(expected_path.read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["summary"]["unhealthy_workers"] == 1
    assert session_state["service_snapshot_path_cache"] == str(expected_path)
    assert fake_st._placeholders[3].last_caption is not None
    assert str(expected_path) in fake_st._placeholders[3].last_caption
    assert any("Operator snapshot exported" in msg for msg in fake_st._success_messages)


def test_render_service_panel_health_gate_failure_renders_error(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
        }
    )
    fake_st = _service_st(session_state, clicked="service_health_gate_btn")
    monkeypatch.setattr(orchestrate_services, "st", fake_st)

    deps = orchestrate_services.OrchestrateServiceDeps(
        reset_traceback_skip=lambda: None,
        append_log_lines=lambda lines, payload: lines.append(payload),
        extract_result_dict_from_output=lambda raw: {"status": "running", "worker_health": []},
        evaluate_service_health_gate=lambda *args, **kwargs: (
            3,
            "restart rate too high",
            {
                "status": "running",
                "workers_unhealthy_count": 0,
                "workers_restarted_count": 2,
                "workers_running_count": 1,
                "restart_rate": 2.0,
            },
        ),
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

    async def fake_run_agi(*_args, **_kwargs):
        return ("{'status': 'running'}", "")

    env = SimpleNamespace(
        app="demo",
        target="demo",
        apps_path=tmp_path,
        app_settings_file=tmp_path / "app_settings.toml",
        run_agi=fake_run_agi,
        snippet_tail="print('tail')",
    )

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": True, "service_health": {}},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=deps,
        )
    )

    assert any("HEALTH gate failed (code 3): restart rate too high" in msg for msg in fake_st._error_messages)


def test_render_service_panel_snapshot_export_failure_surfaces_oserror(monkeypatch, tmp_path):
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
            "service_status_cache": "running",
            "service_health_cache": [],
        }
    )
    fake_st = _service_st(session_state, clicked="service_export_btn")
    monkeypatch.setattr(orchestrate_services, "st", fake_st)
    monkeypatch.setattr(orchestrate_services.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        orchestrate_services,
        "write_service_operator_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    env = SimpleNamespace(
        app="demo_project",
        target="demo",
        apps_path=tmp_path,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={"cluster_enabled": True, "pool": True, "service_health": {}},
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=_deps(),
        )
    )

    assert any("Operator snapshot export failed: disk full" in msg for msg in fake_st._error_messages)


def test_render_service_panel_skips_redundant_service_health_write(monkeypatch, tmp_path):
    writes: list[tuple[object, object]] = []
    session_state = _SessionState(
        {
            "args_serialized": "foo=1",
            "app_settings": {"cluster": {}},
        }
    )
    fake_st = _service_st(session_state)
    monkeypatch.setattr(orchestrate_services, "st", fake_st)

    deps = orchestrate_services.OrchestrateServiceDeps(
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
        write_app_settings_toml=lambda path, payload: writes.append((path, payload)) or payload,
        clear_load_toml_cache=lambda: None,
        log_display_max_lines=100,
        install_log_height=320,
    )

    env = SimpleNamespace(app="demo", apps_path=tmp_path, app_settings_file=tmp_path / "app_settings.toml")

    asyncio.run(
        orchestrate_services.render_service_panel(
            env=env,
            project_path=tmp_path,
            cluster_params={
                "cluster_enabled": True,
                "service_health": {
                    "allow_idle": False,
                    "max_unhealthy": 0,
                    "max_restart_rate": 0.25,
                },
            },
            verbose=1,
            scheduler='"127.0.0.1:8786"',
            workers="{'127.0.0.1': 1}",
            deps=deps,
        )
    )

    assert writes == []
