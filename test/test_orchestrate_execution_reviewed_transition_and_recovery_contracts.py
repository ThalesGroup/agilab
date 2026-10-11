"""Exercise native ORCHESTRATE transitions through the SDK boundary."""
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from agi_web import python_ui
from agi_web.testing import AppTest

execute = importlib.import_module("agilab.orchestrate.orchestrate_execute")
page_support = importlib.import_module("agilab.orchestrate.orchestrate_page_support")


def _native_case(tmp_path, monkeypatch, *, loaded=False, sdk_error=None, stderr=""):
    project = tmp_path / "owned_project"
    (project / ".venv").mkdir(parents=True)
    logs = project / "run_logs"
    profile_file = project / "profile.html"
    export_file = project / "export.csv"
    frame = pd.DataFrame({"sample": [1, 2], "value": [3, 4]})
    case = SimpleNamespace(
        calls=[], events=[" \n", "SDK step completed\n"], profile_calls=[],
        opened=[], project=project, logs=logs, profile_file=profile_file,
        export_file=export_file, frame=frame, ready=True, visible=True,
        show_panel=True, worker_required=False, profile_error=None,
    )

    async def run_agi(command, *, log_callback, venv):
        case.calls.append({"command": command, "runtime": Path(venv)})
        for event in case.events:
            log_callback(event)
        if sdk_error is not None:
            raise sdk_error
        return "", stderr

    env = SimpleNamespace(
        app="owned_project", target="owned", wenv_abs=project / "workers",
        dataframe_path=project, app_data_rel=None, runenv=logs,
        snippet_tail="await reviewed_main()", python_version="3.13",
        run_agi=run_agi,
    )
    case.env = env
    monkeypatch.setattr(execute, "st", python_ui)
    monkeypatch.setattr(execute, "open_new_tab", case.opened.append)

    def render():
        state = python_ui.session_state

        def update_log(_placeholder, message):
            state["log_text"] = state.get("log_text", "") + str(message)

        def generate_profile_report(dataframe):
            case.profile_calls.append(dataframe.copy())

            def to_file(path, *, silent):
                assert silent is False
                if case.profile_error:
                    raise case.profile_error
                Path(path).write_text("<html>owned statistics</html>", encoding="utf-8")

            return SimpleNamespace(to_file=to_file)

        deps = execute.OrchestrateExecuteDeps(
            clear_log=lambda: state.__setitem__("log_text", ""),
            update_log=update_log,
            strip_ansi=str,
            reset_traceback_skip=lambda: None,
            append_log_lines=lambda lines, line: lines.append(line),
            display_log=lambda body, error: python_ui.code(f"{body}\n{error}"),
            rerun_fragment_or_app=python_ui.rerun,
            update_delete_confirm_state=lambda key, **kwargs: page_support.update_delete_confirm_state(
                state, key, **kwargs
            ),
            capture_dataframe_preview_state=lambda: page_support.capture_dataframe_preview_state(state),
            restore_dataframe_preview_state=lambda payload: page_support.restore_dataframe_preview_state(
                state, payload
            ),
            generate_profile_report=generate_profile_report,
            log_display_max_lines=20, live_log_min_height=100, install_log_height=100,
        )
        asyncio.run(execute.render_execute_section(
            env=env, project_path=project, app_state_name=env.app,
            controls_visible=case.visible, show_run_panel=case.show_panel,
            cmd="asyncio.run(main())", deps=deps, install_ready=case.ready,
            install_disabled_reason="" if case.ready else "Manager environment is unavailable.",
            worker_env_required=case.worker_required,
        ))

    case.app = AppTest.from_function(render)
    case.app.session_state.update({
        "app_settings": {"args": {}, "cluster": {"cluster_enabled": False}},
        "loaded_df": frame.copy() if loaded else None,
        "loaded_graph": None, "df_cols": list(frame.columns) if loaded else [],
        "selected_cols": list(frame.columns) if loaded else [],
        "check_all": loaded, "df_export_file": str(export_file),
        "profile_report_file": profile_file,
    })
    return case


def _queue(case, action):
    execute.queue_pending_execute_action(case.app.session_state, action)
    case.app.run()
    assert not case.app.exception


@pytest.mark.parametrize("cached_log", ["", "a previous reviewed run\n"])
@pytest.mark.parametrize("settings_present", [True, False])
def test_sdk_run_is_consumed_once_and_preserves_command_runtime_and_evidence(
    tmp_path, monkeypatch, cached_log, settings_present
):
    case = _native_case(tmp_path, monkeypatch)
    case.app.session_state["run_log_cache"] = cached_log
    if not settings_present:
        case.app.session_state.pop("app_settings")
    _queue(case, "run")

    assert case.calls == [{"command": "await reviewed_main()", "runtime": case.project}]
    assert case.app.session_state["_last_execute_failed"] is False
    assert Path(case.app.session_state["last_run_log_path"]).read_text() == "SDK step completed\n"
    plan = Path(case.app.session_state["last_run_plan_path"])
    report = Path(case.app.session_state["last_run_report_path"])
    assert "asyncio.run(main())" in plan.read_text()
    assert "success" in report.read_text().lower()
    assert Path(case.app.session_state["last_run_evidence_manifest_path"]).is_file()

    case.app.run()
    assert not case.app.exception
    assert len(case.calls) == 1
    assert report.is_file()


@pytest.mark.parametrize("action", ["run", "combo"])
def test_cluster_run_needs_a_new_request_after_approval_was_missing(tmp_path, monkeypatch, action):
    case = _native_case(tmp_path, monkeypatch)
    case.app.session_state["app_settings"]["cluster"]["cluster_enabled"] = True
    _queue(case, action)
    assert case.calls == []
    assert any("Approve the cluster execution plan" in item.value for item in case.app.error)

    case.app.session_state["orchestrate_run_approval__owned_project"] = True
    case.app.run()
    assert not case.app.exception
    assert case.calls == []
    _queue(case, action)
    assert len(case.calls) == 1


@pytest.mark.parametrize("unavailable", ["manager", "controls", "panel", "worker"])
def test_unavailable_execution_discards_request_instead_of_replaying_when_ready(
    tmp_path, monkeypatch, unavailable
):
    case = _native_case(tmp_path, monkeypatch)
    if unavailable == "manager":
        case.ready = False
    elif unavailable == "controls":
        case.visible = False
    elif unavailable == "panel":
        case.show_panel = False
    else:
        case.worker_required = True
    _queue(case, "run")
    assert case.calls == []

    case.ready = case.visible = case.show_panel = True
    case.worker_required = False
    case.app.run()
    assert not case.app.exception
    assert case.calls == []
    _queue(case, "run")
    assert len(case.calls) == 1


@pytest.mark.parametrize(
    "sdk_error",
    [RuntimeError("SDK unavailable"), OSError("SDK transport closed"), TypeError("SDK result invalid"),
     ValueError("SDK configuration invalid"), AttributeError("SDK capability unavailable"),
     KeyError("SDK worker unavailable")],
)
def test_sdk_failure_is_visible_has_evidence_and_is_not_retried(tmp_path, monkeypatch, sdk_error):
    case = _native_case(tmp_path, monkeypatch, sdk_error=sdk_error)
    _queue(case, "run")
    assert len(case.calls) == 1
    assert case.app.session_state["_last_execute_failed"] is True
    assert any("AGI execution failed" in item.value for item in case.app.error)
    report = Path(case.app.session_state["last_run_report_path"])
    assert "failed" in report.read_text().lower()
    assert str(sdk_error) in report.read_text()
    case.app.run()
    assert not case.app.exception
    assert len(case.calls) == 1


def test_sdk_signature_mismatch_is_an_execution_failure_without_a_fallback_call(tmp_path, monkeypatch):
    case = _native_case(tmp_path, monkeypatch)

    async def unsupported_sdk(command):
        case.calls.append(command)
        return "", ""

    case.env.run_agi = unsupported_sdk
    _queue(case, "run")
    assert case.calls == []
    assert case.app.session_state["_last_execute_failed"] is True
    report = Path(case.app.session_state["last_run_report_path"]).read_text()
    assert "log_callback" in report and "failed" in report.lower()
    case.app.run()
    assert not case.app.exception
    assert case.calls == []


@pytest.mark.parametrize("stderr", ["", "An informational SDK note"])
def test_nonfatal_stderr_and_blank_log_events_keep_run_successful(tmp_path, monkeypatch, stderr):
    case = _native_case(tmp_path, monkeypatch, stderr=stderr)
    _queue(case, "run")
    assert case.app.session_state["_last_execute_failed"] is False
    assert len(case.calls) == 1
    assert Path(case.app.session_state["last_run_log_path"]).read_text() == "SDK step completed\n"
    assert "success" in Path(case.app.session_state["last_run_report_path"]).read_text().lower()


def test_delete_cancellation_keeps_the_reviewed_file_and_dataframe(tmp_path, monkeypatch):
    case = _native_case(tmp_path, monkeypatch, loaded=True)
    case.export_file.write_text("sample,value\n1,3\n2,4\n", encoding="utf-8")
    case.app.session_state["loaded_source_path"] = case.export_file
    case.app.run()
    assert not case.app.exception
    case.app.button(key="delete_data_main").click().run()
    assert not case.app.exception
    case.app.button(key="delete_data_main_cancel_btn").click().run()
    assert not case.app.exception
    assert case.export_file.read_text() == "sample,value\n1,3\n2,4\n"
    pd.testing.assert_frame_equal(case.app.session_state["loaded_df"], case.frame)
    with pytest.raises(KeyError):
        case.app.button(key="delete_data_main_cancel_btn")
    assert case.calls == []


@pytest.mark.parametrize("cached", [True, False])
def test_stats_reuses_existing_report_and_records_report_write_failure(tmp_path, monkeypatch, cached):
    case = _native_case(tmp_path, monkeypatch, loaded=True)
    if cached:
        case.profile_file.write_text("<html>reviewed statistics</html>", encoding="utf-8")
    else:
        case.profile_error = RuntimeError("Statistics serialization unavailable")
    case.app.run()
    assert not case.app.exception
    case.app.button(key="stats_report_main").click().run()
    if cached:
        assert not case.app.exception
        assert case.profile_calls == []
        assert case.opened == [case.profile_file.as_uri()]
        assert case.profile_file.read_text() == "<html>reviewed statistics</html>"
    else:
        assert len(case.app.exception) == 1
        assert "Statistics serialization unavailable" in case.app.exception[0].message
        assert len(case.profile_calls) == 1
        assert not case.profile_file.exists()
        assert case.opened == []
        case.app.run()
        assert not case.app.exception
        assert len(case.profile_calls) == 1
    pd.testing.assert_frame_equal(case.app.session_state["loaded_df"], case.frame)


def test_csv_write_failure_keeps_loaded_preview_and_does_not_claim_export_success(tmp_path, monkeypatch):
    case = _native_case(tmp_path, monkeypatch, loaded=True)
    directory = case.project / "blocked.csv"
    directory.mkdir()
    case.app.session_state["df_export_file"] = str(directory)
    case.app.run()
    assert not case.app.exception
    case.app.button(key="export_df_main").click().run()
    assert not case.app.exception
    assert len(case.app.error) >= 1
    assert not case.app.session_state.get("_experiment_reload_required", False)
    assert not any("exported successfully" in item.value for item in case.app.success)
    pd.testing.assert_frame_equal(case.app.session_state["loaded_df"], case.frame)
    assert directory.is_dir() and list(directory.iterdir()) == []
