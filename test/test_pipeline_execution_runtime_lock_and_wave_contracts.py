"""Execution dispatch, evidence paths and lock ownership fail safely."""

from contextlib import nullcontext
import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


class PipelineUI:
    def __init__(self):
        self.session_state = {}
        self.messages = []

    def __getattr__(self, name):
        if name in {"error", "warning", "info", "success", "caption", "code"}:
            return lambda message, **_kwargs: self.messages.append((name, str(message)))
        raise AttributeError(name)

    def spinner(self, *_args, **_kwargs):
        return nullcontext()


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    module = importlib.import_module("agilab.pipeline.pipeline_run_controls")
    ui = PipelineUI()
    monkeypatch.setattr(module, "st", ui)
    env = SimpleNamespace(app="demo", target="demo", home_abs=tmp_path, runenv=tmp_path / "logs",
        active_app=tmp_path / "app", resolve_share_path=lambda relative: tmp_path / "share" / relative)
    return module, ui, env


def test_manifest_uses_the_selected_run_log_and_tolerates_malformed_output_inventory(pipeline, tmp_path):
    module, ui, env = pipeline
    chosen_log = tmp_path / "selected-run" / "pipeline.trace.log"
    ui.session_state["page__run_log_file"] = str(chosen_log)
    run, latest = module._pipeline_manifest_paths(env, "page", "owned-run")
    assert run == chosen_log.with_suffix(".pipeline_manifest.json")
    assert latest.parent == chosen_log.parent
    assert not chosen_log.parent.exists(), "Evidence path discovery must not create directories"
    rows = module._automation_manifest_output_rows({"stages": [None, "bad", {"stage_index": 2,
        "status": "completed", "outputs": [None, "bad", {"spec": "data.csv", "exists": True, "is_file": True}]}]})
    assert len(rows) == 1
    assert rows[0]["stage"] == 2 and rows[0]["spec"] == "data.csv" and rows[0]["exists"] is True


def test_missing_distribution_version_does_not_invent_manifest_provenance(pipeline, monkeypatch):
    module, _ui, _env = pipeline
    def absent(_name):
        raise module.PackageNotFoundError("agilab")
    monkeypatch.setattr(module, "package_version", absent)
    assert module._pipeline_automation_producer_version() == ""


@pytest.mark.parametrize("first", [
    {"id": "disabled", "enabled": False, "C": "print(1)"},
    {"id": "satisfied", "C": "print(1)", "automation": {"skip_if_outputs_exist": True, "outputs": ["done.txt"]}},
])
def test_parallel_dispatch_refuses_disabled_or_already_satisfied_stages(pipeline, tmp_path, first):
    module, _ui, env = pipeline
    (tmp_path / "done.txt").write_text("verified output")
    env.runenv = tmp_path
    env.AGILAB_EXPORT_ABS = tmp_path
    reason = module._parallel_agi_wave_ineligibility_reason([first, {"id": "next", "C": "print(2)"}], [0, 1],
        profile="balanced", env=env, stages_file=tmp_path / "stages.toml", selected_map={}, engine_map={}, default_runtime="")
    assert reason and ("disabled" in reason if first["id"] == "disabled" else "already satisfied" in reason)


def test_parallel_dispatch_requires_multiple_unsatisfied_stages(pipeline, tmp_path):
    module, _ui, env = pipeline
    args = dict(profile="balanced", env=env, stages_file=tmp_path / "stages.toml", selected_map={}, engine_map={}, default_runtime="")
    assert "fewer than two" in module._parallel_agi_wave_ineligibility_reason([{"C": "print(1)"}], [0], **args)
    reason = module._parallel_agi_wave_ineligibility_reason([{"C": "print(1)"}, {"C": "print(2)"}], [0, 1], **args)
    assert "parallel output contract" in reason


def test_an_unreadable_lock_timestamp_retains_the_owner_and_does_not_authorize_stale_cleanup(pipeline, tmp_path, monkeypatch):
    module, _ui, env = pipeline
    lock = module._pipeline_lock_path(env)
    lock.write_text(json.dumps({"pid": os.getpid(), "host": module.socket.gethostname(), "token": "owned"}))
    original_stat = Path.stat
    calls = 0
    def transient_stat(path, *_args, **kwargs):
        nonlocal calls
        if path == lock:
            calls += 1
            if calls > 1:
                raise PermissionError("timestamp unavailable")
        return original_stat(path, *_args, **kwargs)
    monkeypatch.setattr(Path, "stat", transient_stat)
    result = module._inspect_pipeline_run_lock(env)
    assert result["age_sec"] is None and result["owner_alive"] is True
    assert result["is_stale"] is False and result["payload"]["token"] == "owned"


def test_an_empty_lock_payload_remains_unverified(pipeline):
    module, _ui, env = pipeline
    lock = module._pipeline_lock_path(env)
    lock.write_text("{}")
    assert module._inspect_pipeline_run_lock(env) is None
    assert lock.exists()


def test_forced_cleanup_refusal_never_attempts_acquisition(pipeline, monkeypatch):
    module, _ui, env = pipeline
    attempt = Mock()
    monkeypatch.setattr(module, "_clear_pipeline_run_lock", Mock(return_value=False))
    monkeypatch.setattr(module, "_try_pipeline_file_lock", attempt)
    assert module._acquire_pipeline_run_lock(env, "page", force=True) is None
    attempt.assert_not_called()


def test_repeated_stale_cleanup_is_bounded_and_closes_every_acquisition_fd(pipeline, monkeypatch):
    module, ui, env = pipeline
    opened = []
    class RecordingOS:
        def __getattr__(self, name):
            return getattr(os, name)
        def open(self, *args, **kwargs):
            fd = os.open(*args, **kwargs)
            opened.append(fd)
            return fd
    monkeypatch.setattr(module, "os", RecordingOS())
    monkeypatch.setattr(module, "_try_pipeline_file_lock", lambda _fd: False)
    monkeypatch.setattr(module, "_inspect_pipeline_run_lock", lambda _env: {"is_stale": True})
    clear = Mock(return_value=True)
    monkeypatch.setattr(module, "_clear_pipeline_run_lock", clear)
    assert module._acquire_pipeline_run_lock(env, "page") is None
    assert clear.call_count == 2 and len(opened) == 2
    assert any("after stale cleanup retries" in message for _kind, message in ui.messages)
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_lock_metadata_failure_closes_the_fd_even_if_unlock_itself_fails(pipeline, monkeypatch):
    module, ui, env = pipeline
    descriptors = []
    original_write = module._write_pipeline_lock_payload
    def malformed(fd, _payload):
        descriptors.append(fd)
        raise ValueError("invalid lock metadata")
    monkeypatch.setattr(module, "_write_pipeline_lock_payload", malformed)
    monkeypatch.setattr(module, "_unlock_pipeline_file", Mock(side_effect=OSError("unlock unavailable")))
    assert module._acquire_pipeline_run_lock(env, "page") is None
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert any("invalid lock metadata" in message for _kind, message in ui.messages)
    monkeypatch.setattr(module, "_write_pipeline_lock_payload", original_write)


@pytest.mark.parametrize("visible_output", [False, True])
def test_parallel_scripts_normalize_sdk_requests_and_record_an_empty_stdout_success(pipeline, tmp_path, monkeypatch, visible_output):
    module, ui, env = pipeline
    legacy = "from agi_cluster.agi_distributor import AGI, RunRequest, StepRequest\nsteps = [StepRequest(name='demo', args={})]\nrequest = RunRequest(mode=4, steps=steps)\n"
    stages = [{"id": "first", "C": legacy, "R": "agi.run", "E": str(tmp_path)},
        {"id": "second", "C": "print('second')", "R": "agi.run", "E": str(tmp_path)}]
    monkeypatch.setattr(module._pipeline_runtime, "python_for_stage", lambda *_args, **_kwargs: sys.executable)
    monkeypatch.setattr(module._pipeline_runtime, "build_mlflow_process_env", lambda *_args, **_kwargs: {})
    received = []
    def execute_boundary(command, *, cwd, extra_env):
        source = Path(command[-1]).read_text()
        received.append((source, cwd, extra_env))
        return "completed first stage" if visible_output and "StageRequest" in source else ""
    monkeypatch.setattr(module, "_run_stage_subprocess", execute_boundary)
    records = []
    assert module._run_parallel_agi_wave(stages=stages, wave=[0, 1], profile="balanced", env=env, index_page="page",
        stages_file=tmp_path / "stages.toml", run_id="owned-wave", selected_map={}, engine_map={}, default_runtime=str(tmp_path),
        target_base=tmp_path, max_workers=2, manifest_stage_records=records, log_placeholder=None) == 2
    assert any("StageRequest" in source for source, _cwd, _env in received)
    assert all("StepRequest" not in source for source, _cwd, _env in received)
    assert all(item[2]["AGILAB_PIPELINE_RUN_ID"] == "owned-wave" for item in received)
    assert all(record["status"] == "completed" and record["parallel_wave"] for record in records)
    assert any("no captured stdout" in line for line in ui.session_state["page__run_logs"])


def configured_adapter(module, ui, env, tmp_path, entry, ui_engine=""):
    snippet = tmp_path / "snippet.py"
    snippet.write_text("# source is prepared by the execution adapter\n")
    ui.session_state.update({"page": [0, "", "", "", "", "", 0], "snippet_file": str(snippet)})
    plan = module.PipelineExecutionPlan(stages=[entry], sequence=[0], waves=[[0]], profile="balanced", max_workers=1,
        stage_ids={0: "owned"}, stage_deps={0: []})
    streams = []
    def stream(_env, _page, command, **kwargs):
        streams.append((Path(command[-1]).read_text(), kwargs))
        return "No such file or directory: upstream.csv"
    adapter = module._PipelineExecutionAdapter(lab_dir=tmp_path, index_page_str="page", stages_file=tmp_path / "stages.toml",
        env=env, stream_run_command_fn=stream, log_placeholder=None, plan=plan,
        selected_map={}, engine_map={0: ui_engine} if ui_engine else {}, details_store={}, original_stage=0,
        original_selected="", original_engine="", snippet_file=str(snippet), lock_handle=None)
    state = module.PipelineRunState(run_id="owned-adapter", started_at="2026-10-12T00:00:00Z", started_monotonic=module.time.time())
    return adapter, state, streams


@pytest.mark.parametrize("entry_engine,ui_engine", [("agi.run", "runpy"), ("runpy", "agi.run")])
def test_stage_adapter_preserves_sdk_dispatch_and_normalizes_the_authored_request(pipeline, tmp_path, monkeypatch, entry_engine, ui_engine):
    module, ui, env = pipeline
    root = tmp_path / "runtime"
    root.mkdir()
    code = "from agi_cluster.agi_distributor import AGI, RunRequest, StepRequest\nsteps = [StepRequest(name='demo', args={})]\nrequest = RunRequest(mode=4, steps=steps)\n"
    entry = {"C": code, "R": entry_engine, "E": str(root)}
    # These are environment/process boundaries, not worker providers or business decisions.
    monkeypatch.setattr(module._pipeline_runtime, "is_valid_runtime_root", lambda value: Path(value) == root if value else False)
    monkeypatch.setattr(module._pipeline_runtime, "start_tracker_run", lambda *_args, **_kwargs: nullcontext(None))
    monkeypatch.setattr(module._pipeline_runtime, "build_mlflow_process_env", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(module._pipeline_runtime, "python_for_stage", lambda *_args, **_kwargs: sys.executable)
    adapter, state, streams = configured_adapter(module, ui, env, tmp_path, entry, ui_engine)
    adapter._execute_stage(state, None, 0)
    assert len(streams) == 1
    assert "StageRequest" in streams[0][0] and "StepRequest" not in streams[0][0]
    assert streams[0][1]["extra_env"]["AGILAB_PIPELINE_RUN_ID"] == "owned-adapter"
    assert state.stage_records[0]["engine"] == "agi.run" and state.stage_records[0]["runtime"] == str(root)
    assert state.stage_records[0]["status"] == "completed"
    assert any("AGI_CLUSTER_SHARE" in line for line in ui.session_state["page__run_logs"])


def test_stage_without_runnable_code_is_skipped_without_dispatch(pipeline, tmp_path):
    module, ui, env = pipeline
    adapter, state, streams = configured_adapter(module, ui, env, tmp_path, {"C": ""})
    adapter._execute_stage(state, None, 0)
    assert not streams
    assert state.skipped == 1 and state.executed == 0
    assert state.stage_records[0]["status"] == "skipped_not_runnable"


def test_nonzero_real_subprocess_marks_workflow_failed_and_stops_dependents(
    pipeline, tmp_path, monkeypatch
):
    from agilab.pipeline.pipeline_execution import execute_pipeline_lifecycle
    from agilab.pipeline.pipeline_runtime_execution_support import stream_run_command
    import re
    import subprocess

    module, ui, env = pipeline
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    first = {
        "id": "first",
        "C": "import sys; sys.exit(9)",
        "R": "agi.run",
        "E": str(runtime),
    }
    second = {
        "id": "dependent",
        "C": "from pathlib import Path; Path('dependent-ran.txt').write_text('ran')",
        "R": "agi.run",
        "E": str(runtime),
    }
    monkeypatch.setattr(
        module._pipeline_runtime, "is_valid_runtime_root", lambda value: bool(value)
    )
    monkeypatch.setattr(
        module._pipeline_runtime,
        "start_tracker_run",
        lambda *_args, **_kwargs: nullcontext(None),
    )
    monkeypatch.setattr(
        module._pipeline_runtime,
        "build_mlflow_process_env",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        module._pipeline_runtime,
        "python_for_stage",
        lambda *_args, **_kwargs: sys.executable,
    )
    adapter, state, _streams = configured_adapter(module, ui, env, tmp_path, first)
    adapter.plan = module.PipelineExecutionPlan(
        stages=[first, second],
        sequence=[0, 1],
        waves=[[0], [1]],
        profile="balanced",
        max_workers=1,
        stage_ids={0: "first", 1: "dependent"},
        stage_deps={0: [], 1: ["first"]},
    )

    def real_stream(run_env, page, command, cwd, **kwargs):
        return stream_run_command(
            run_env,
            page,
            command,
            cwd,
            push_run_log=module._push_run_log,
            ansi_escape_re=re.compile(r"\x1b\[[0-9;]*m"),
            jump_exception_cls=RuntimeError,
            **kwargs,
        )

    adapter.stream_run_command_fn = real_stream
    with pytest.raises(subprocess.CalledProcessError) as failure:
        execute_pipeline_lifecycle(
            state, adapter, describe_error=str, timestamp=lambda: "2026-10-14T00:00:00Z"
        )

    assert failure.value.returncode == 9
    assert state.status == "failed"
    assert state.executed == 0
    assert [row["status"] for row in state.stage_records] == [
        "failed",
        "skipped_after_failure",
    ]
    assert not (tmp_path / "dependent-ran.txt").exists()
    assert not any(kind == "success" for kind, _message in ui.messages)


def test_an_invalid_profile_override_is_rejected_before_any_execution_or_lock(pipeline, tmp_path, monkeypatch):
    module, ui, env = pipeline
    ui.session_state.update({"page": [0, "", "", "", "", "", 0], "snippet_file": str(tmp_path / "snippet.py")})
    stage = {"C": "print('authored Python')", "profiles": {"balanced": {"kind": "template", "template_id": "not_registered"}}}
    acquire = Mock()
    stream = Mock()
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", acquire)
    module.run_all_stages(tmp_path, "page", tmp_path / "stages.toml", tmp_path, env,
        load_all_stages_fn=lambda *_args: [stage], stream_run_command_fn=stream, pipeline_max_workers="invalid")
    acquire.assert_not_called()
    stream.assert_not_called()
    assert any(kind == "error" and "template" in message.lower() for kind, message in ui.messages)
