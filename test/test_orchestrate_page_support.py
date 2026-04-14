from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace


class _CaptureCodeSink:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def code(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


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


orchestrate_page_support = _import_agilab_module("agilab.orchestrate_page_support")


def test_build_install_and_run_snippets_embed_expected_values():
    env = SimpleNamespace(apps_path="/tmp/apps", app="demo_project")

    install_snippet = orchestrate_page_support.build_install_snippet(
        env=env,
        verbose=2,
        mode=7,
        scheduler='"127.0.0.1:8786"',
        workers="{'127.0.0.1': 1}",
        workers_data_path='"/tmp/share"',
    )
    run_snippet = orchestrate_page_support.build_run_snippet(
        env=env,
        verbose=3,
        run_mode=15,
        scheduler='"127.0.0.1:8786"',
        workers="{'127.0.0.1': 2}",
        args_serialized='foo="bar", n=2',
    )

    assert 'APP = "demo_project"' in install_snippet
    assert "modes_enabled=7" in install_snippet
    assert 'workers_data_path="/tmp/share"' in install_snippet
    assert "mode=15" in run_snippet
    assert 'foo="bar", n=2' in run_snippet


def test_build_distribution_snippet_omits_blank_args_payload():
    snippet = orchestrate_page_support.build_distribution_snippet(
        env=SimpleNamespace(apps_path="/tmp/apps", app="demo_project"),
        verbose=1,
        scheduler="None",
        workers="None",
        args_serialized="",
    )

    assert "get_distrib" in snippet
    assert "workers=None" in snippet
    assert ",\n        \n" not in snippet


def test_serialize_args_payload_and_optional_exprs_cover_string_and_mapping_cases():
    payload = orchestrate_page_support.serialize_args_payload(
        {"dataset": "flight/source", "limit": 5, "enabled": True}
    )

    assert payload == 'dataset="flight/source", limit=5, enabled=True'
    assert orchestrate_page_support.optional_string_expr(True, "tcp://127.0.0.1:8786") == '"tcp://127.0.0.1:8786"'
    assert orchestrate_page_support.optional_string_expr(False, "ignored") == "None"
    assert orchestrate_page_support.optional_python_expr(True, {"127.0.0.1": 1}) == "{'127.0.0.1': 1}"
    assert orchestrate_page_support.optional_python_expr(False, {"127.0.0.1": 1}) == "None"


def test_run_mode_helpers_cover_label_generation():
    run_mode = orchestrate_page_support.compute_run_mode(
        {"pool": True, "cython": True, "rapids": True},
        cluster_enabled=True,
    )

    assert run_mode == 15
    assert orchestrate_page_support.describe_run_mode(run_mode, False) == "Run mode 15: rapids and dask and pool and cython"
    assert orchestrate_page_support.describe_run_mode(None, True) == "Run mode benchmark (all modes)"


def test_reassign_distribution_plan_uses_stable_selection_keys_and_preserves_defaults():
    workers = ["10.0.0.1-1", "10.0.0.2-1"]
    work_plan_metadata = [[("A", 2)], [("B", 3)]]
    work_plan = [[["a.csv"]], [["b.csv"]]]
    selection_key = orchestrate_page_support.workplan_selection_key("A", 0, 0)

    new_metadata, new_plan = orchestrate_page_support.reassign_distribution_plan(
        workers=workers,
        work_plan_metadata=work_plan_metadata,
        work_plan=work_plan,
        selections={selection_key: "10.0.0.2-1"},
    )

    assert new_metadata == [[], [("A", 2), ("B", 3)]]
    assert new_plan == [[], [["a.csv"], ["b.csv"]]]

    unchanged_metadata, unchanged_plan = orchestrate_page_support.reassign_distribution_plan(
        workers=workers,
        work_plan_metadata=work_plan_metadata,
        work_plan=work_plan,
        selections={},
    )

    assert unchanged_metadata == [[("A", 2)], [("B", 3)]]
    assert unchanged_plan == [[["a.csv"]], [["b.csv"]]]


def test_update_distribution_payload_replaces_target_args_and_plan():
    updated = orchestrate_page_support.update_distribution_payload(
        {"workers": {"127.0.0.1": 1}, "unchanged": True},
        target_args={"foo": "bar"},
        work_plan_metadata=[[("A", 1)]],
        work_plan=[[["a.csv"]]],
    )

    assert updated == {
        "workers": {"127.0.0.1": 1},
        "unchanged": True,
        "target_args": {"foo": "bar"},
        "work_plan_metadata": [[("A", 1)]],
        "work_plan": [[["a.csv"]]],
    }


def test_strip_ansi_removes_escape_sequences():
    assert orchestrate_page_support.strip_ansi("\x1b[31merror\x1b[0m") == "error"


def test_is_dask_shutdown_noise_matches_known_lines():
    assert orchestrate_page_support.is_dask_shutdown_noise("Stream is closed")
    assert orchestrate_page_support.is_dask_shutdown_noise("File \"/usr/local/lib/python3.11/site-packages/distributed/comm.py\", line 1")
    assert orchestrate_page_support.is_dask_shutdown_noise("Traceback (most recent call last):")


def test_filter_noise_lines_removes_shutdown_lines_and_keeps_others():
    text = "\n".join(
        [
            "normal message",
            "StreamClosedError",
            "another line",
            "stream is closed",
        ]
    )
    assert orchestrate_page_support.filter_noise_lines(text) == "normal message\nanother line"


def test_format_log_block_orders_latest_first_and_limits():
    text = "\n".join(f"line {i}" for i in range(1, 6))
    assert orchestrate_page_support.format_log_block(text, newest_first=True, max_lines=3) == "line 5\nline 4\nline 3"
    assert orchestrate_page_support.format_log_block(text, newest_first=False, max_lines=3) == "line 3\nline 4\nline 5"


def test_filter_warning_messages_removes_virtual_env_mismatch():
    log = "\n".join(
        [
            "normal warning",
            "VIRTUAL_ENV=/tmp/.venv does not match the project environment path",
            "final",
        ]
    )
    assert (
        orchestrate_page_support.filter_warning_messages(log)
        == "normal warning\nfinal"
    )


def test_log_indicates_install_failure():
    assert not orchestrate_page_support.log_indicates_install_failure(["all good", "installation complete"])
    assert orchestrate_page_support.log_indicates_install_failure(["TRACEBACK", "error", "connection"])
    assert not orchestrate_page_support.log_indicates_install_failure([])


def test_append_log_lines_filters_tracebacks_and_dask_noise():
    buffer: list[str] = []
    state = {"active": False}
    orchestrate_page_support.append_log_lines(
        buffer,
        "\n".join(["normal", "Traceback (most recent call last):", "stream is closed", "", "next"]),
        cluster_verbose=1,
        traceback_state=state,
    )
    assert buffer == ["normal", "next"]
    assert state["active"] is False


def test_update_log_helper_updates_session_state_and_trims_output():
    sink = _CaptureCodeSink()
    session_state: dict[str, object] = {}
    traceback_state = {"active": False}

    for i in range(1, 5):
        orchestrate_page_support.update_log(
            session_state,
            sink,
            f"line {i}",
            max_lines=3,
            cluster_verbose=2,
            traceback_state=traceback_state,
            strip_ansi_fn=orchestrate_page_support.strip_ansi,
            is_dask_shutdown_noise_fn=orchestrate_page_support.is_dask_shutdown_noise,
            log_display_max_lines=2,
            live_log_min_height=160,
        )

    assert session_state["log_text"] == "line 2\nline 3\nline 4\n"
    assert sink.calls[-1][0][0] == "line 3\nline 4"
    assert sink.calls[-1][1]["language"] == "python"
    assert sink.calls[-1][1]["height"] == 160


def test_update_log_helper_ignores_traceback_and_dask_noise_at_low_verbosity():
    sink = _CaptureCodeSink()
    session_state: dict[str, object] = {"cluster_verbose": 1}
    traceback_state = {"active": False}

    for message in [
        "normal",
        "Traceback (most recent call last):",
        "stream is closed",
        "",
        "after traceback",
    ]:
        orchestrate_page_support.update_log(
            session_state,
            sink,
            message,
            max_lines=10,
            cluster_verbose=1,
            traceback_state=traceback_state,
            strip_ansi_fn=orchestrate_page_support.strip_ansi,
            is_dask_shutdown_noise_fn=orchestrate_page_support.is_dask_shutdown_noise,
            log_display_max_lines=10,
            live_log_min_height=100,
        )

    assert session_state["log_text"] == "normal\nafter traceback\n"
    assert traceback_state["active"] is False
    assert sink.calls[-1][0][0] == "normal\nafter traceback"


def test_display_log_helper_warns_on_warning_stderr_and_uses_stderr_path():
    warnings: list[str] = []
    errors: list[str] = []
    code_sink = _CaptureCodeSink()

    def _warn(message: str) -> None:
        warnings.append(message)

    def _err(message: str) -> None:
        errors.append(message)

    orchestrate_page_support.display_log(
        stdout="normal output\nwarning: deprecated option\n",
        stderr="",
        session_state={},
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        filter_warning_messages_fn=lambda text: text,
        format_log_block_fn=lambda text: text,
        warning_fn=_warn,
        error_fn=_err,
        code_fn=code_sink,
        log_display_max_lines=250,
        log_display_height=300,
    )

    assert warnings == ["Warnings occurred during cluster installation:"]
    assert errors == []
    assert code_sink.calls[-1][0][0] == "normal output\nwarning: deprecated option"


def test_display_log_helper_uses_cached_stdout_when_missing_and_shows_stderr_errors():
    errors: list[str] = []
    warning_messages: list[str] = []
    code_sink = _CaptureCodeSink()

    orchestrate_page_support.display_log(
        stdout="",
        stderr="something failed",
        session_state={"log_text": "fallback log"},
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        filter_warning_messages_fn=lambda text: text,
        format_log_block_fn=lambda text: text,
        warning_fn=lambda message: warning_messages.append(message),
        error_fn=lambda message: errors.append(message),
        code_fn=code_sink,
        log_display_max_lines=250,
        log_display_height=300,
    )

    assert warning_messages == []
    assert errors == ["Errors occurred during cluster installation:"]
    assert code_sink.calls[-1][0][0] == "something failed"


def test_capture_and_restore_dataframe_preview_state_round_trip():
    session_state: dict[str, object] = {
        "loaded_df": {"rows": 1},
        "loaded_graph": {"nodes": 3},
        "loaded_source_path": "/tmp/source.csv",
        "df_cols": ["a", "b"],
        "selected_cols": ["a"],
        "check_all": False,
        "_force_export_open": True,
        "dataframe_deleted": False,
        "export_col_0": True,
        "export_col_1": False,
    }

    captured = orchestrate_page_support.capture_dataframe_preview_state(session_state)
    assert captured["loaded_df"] == {"rows": 1}
    assert captured["df_cols"] == ["a", "b"]
    assert captured["selected_cols"] == ["a"]

    target: dict[str, object] = {}
    orchestrate_page_support.restore_dataframe_preview_state(
        target,
        payload={
            "loaded_df": "restored_df",
            "loaded_graph": "restored_graph",
            "loaded_source_path": "/tmp/restored.csv",
            "df_cols": ["x", "y"],
            "selected_cols": ["y"],
            "check_all": True,
            "force_export_open": False,
            "dataframe_deleted": True,
        },
    )

    assert target["loaded_df"] == "restored_df"
    assert target["loaded_graph"] == "restored_graph"
    assert target["loaded_source_path"] == "/tmp/restored.csv"
    assert target["df_cols"] == ["x", "y"]
    assert target["selected_cols"] == ["x", "y"]
    assert target["check_all"] is True
    assert target["_force_export_open"] is False
    assert target["dataframe_deleted"] is True
    assert target["export_col_0"] is True
    assert target["export_col_1"] is True


def test_select_all_state_helpers_update_columns():
    session_state: dict[str, object] = {
        "df_cols": ["a", "b", "c"],
        "selected_cols": ["a"],
        "check_all": False,
    }
    orchestrate_page_support.toggle_select_all(session_state)
    assert session_state["selected_cols"] == []

    session_state["check_all"] = True
    orchestrate_page_support.toggle_select_all(session_state)
    assert session_state["selected_cols"] == ["a", "b", "c"]

    session_state.update({"export_col_0": True, "export_col_1": True, "export_col_2": False})
    orchestrate_page_support.update_select_all(session_state)
    assert session_state["check_all"] is False
    assert session_state["selected_cols"] == ["a", "b"]
