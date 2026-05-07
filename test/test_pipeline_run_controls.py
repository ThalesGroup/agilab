from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import types
from types import SimpleNamespace


def _import_pipeline_run_controls():
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
        pkg.__file__ = str(package_root / "__init__.py")
        sys.modules["agilab"] = pkg
    elif package_root_str not in list(pkg.__path__):
        pkg.__path__ = [package_root_str, *list(pkg.__path__)]
    importlib.invalidate_caches()
    return importlib.import_module("agilab.pipeline_run_controls")


class _FakePlaceholder:
    def __init__(self) -> None:
        self.codes: list[str] = []
        self.captions: list[str] = []

    def code(self, value: str) -> None:
        self.codes.append(value)

    def caption(self, value: str) -> None:
        self.captions.append(value)


class _FakeStreamlit:
    def __init__(self, session_state: dict | None = None) -> None:
        self.session_state = session_state or {}
        self.messages: list[tuple[str, str]] = []

    def error(self, message: str) -> None:
        self.messages.append(("error", str(message)))

    def warning(self, message: str) -> None:
        self.messages.append(("warning", str(message)))

    def info(self, message: str) -> None:
        self.messages.append(("info", str(message)))

    def success(self, message: str) -> None:
        self.messages.append(("success", str(message)))

    @contextmanager
    def spinner(self, message: str):
        self.messages.append(("spinner", str(message)))
        yield


def test_pipeline_run_controls_payloads_logs_and_log_file_setup(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module._pipeline_runtime, "mlflow_tracking_uri", lambda _env: "sqlite:///mlflow.db")
    monkeypatch.setattr(module._pipeline_steps, "step_summary", lambda _entry, width=80: f"summary:{width}")

    env = SimpleNamespace(app="demo", runenv=tmp_path / "logs")
    run_name, tags, params, text_artifacts = module._mlflow_parent_payload(
        env,
        tmp_path / "lab",
        tmp_path / "lab_steps.toml",
        [0, 2],
    )

    assert run_name == "demo:lab:pipeline"
    assert tags["agilab.tracking_uri"] == "sqlite:///mlflow.db"
    assert params == {"sequence": "1,3", "step_count": 2}
    assert json.loads(text_artifacts["pipeline_metadata/sequence.json"])["sequence"] == [1, 3]

    step_name, step_tags, step_params, step_artifacts = module._mlflow_step_payload(
        env,
        tmp_path / "lab",
        tmp_path / "lab_steps.toml",
        step_index=1,
        entry={"D": "desc", "Q": "question", "M": "model", "C": "print(1)"},
        engine="agi.run",
        runtime_root="/runtime",
    )

    assert step_name == "demo:lab:step_2"
    assert step_tags["agilab.summary"] == "summary:80"
    assert step_params["engine"] == "agi.run"
    assert json.loads(step_artifacts["step_2/step_entry.json"])["step_index"] == 2

    for idx in range(205):
        module._append_run_log("trim", f"log-{idx}")
    assert len(fake_st.session_state["trim__run_logs"]) == 200
    assert fake_st.session_state["trim__run_logs"][0] == "log-5"

    log_file = tmp_path / "nested" / "run.log"
    placeholder = _FakePlaceholder()
    fake_st.session_state["page__run_log_file"] = str(log_file)
    module._push_run_log("page", "line one\n", placeholder)

    assert log_file.read_text(encoding="utf-8") == "line one\n"
    assert placeholder.codes[-1].endswith("line one\n")

    prepared, error = module._prepare_run_log_file("page", env, "bad prefix !")
    assert error is None
    assert prepared is not None
    assert prepared.name.startswith("bad_prefix_")
    assert fake_st.session_state["page__last_run_log_file"] == str(prepared)

    bad_env = SimpleNamespace(app="demo", runenv=object())
    prepared, error = module._prepare_run_log_file("broken", bad_env, "run")
    assert prepared is None
    assert error
    assert "broken__run_log_file" not in fake_st.session_state


def test_pipeline_run_controls_lock_helpers_cover_owner_and_lifecycle_edges(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)

    env = SimpleNamespace(
        app="demo",
        target="",
        home_abs=tmp_path,
        resolve_share_path=lambda relative: tmp_path / "share" / relative,
    )
    lock_path = module._pipeline_lock_path(env)
    assert lock_path == tmp_path / "share" / ".control" / "pipeline" / "demo" / "pipeline_run.lock"

    fallback_env = SimpleNamespace(app="fallback", target="", home_abs=tmp_path)
    fallback_path = module._pipeline_lock_path(fallback_env)
    assert fallback_path == (tmp_path / ".agilab_pipeline" / "fallback" / "pipeline_run.lock").resolve(
        strict=False
    )

    host = socket.gethostname()
    assert module._pipeline_lock_owner_alive({"host": "other", "pid": os.getpid()}) is None
    assert module._pipeline_lock_owner_alive({"host": host, "pid": "bad"}) is None
    assert module._pipeline_lock_owner_alive({"host": host, "pid": 0}) is None

    monkeypatch.setattr(module.os, "kill", lambda *_args: (_ for _ in ()).throw(ProcessLookupError()))
    assert module._pipeline_lock_owner_alive({"host": host, "pid": 123}) is False
    monkeypatch.setattr(module.os, "kill", lambda *_args: (_ for _ in ()).throw(PermissionError()))
    assert module._pipeline_lock_owner_alive({"host": host, "pid": 123}) is True
    monkeypatch.setattr(module.os, "kill", lambda *_args: (_ for _ in ()).throw(OSError()))
    assert module._pipeline_lock_owner_alive({"host": host, "pid": 123}) is None

    direct_lock = tmp_path / "direct.lock"
    monkeypatch.setattr(module, "_pipeline_lock_path", lambda _env: direct_lock)
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "1")

    assert module._inspect_pipeline_run_lock(env) is None

    direct_lock.write_text(json.dumps({"host": "remote", "pid": 123, "app": "demo"}), encoding="utf-8")
    old = module.time.time() - 10
    os.utime(direct_lock, (old, old))
    state = module._inspect_pipeline_run_lock(env)

    assert state is not None
    assert state["is_stale"] is True
    assert "heartbeat expired" in state["stale_reason"]
    assert "host=remote" in state["owner_text"]

    assert module._clear_pipeline_run_lock(env, "page", reason="test") is True
    assert not direct_lock.exists()
    assert module._clear_pipeline_run_lock(env, "page", reason="already gone") is True


def test_pipeline_run_controls_acquire_refresh_release_and_busy_lock(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "1")

    env = SimpleNamespace(
        app="demo",
        target="demo-target",
        home_abs=tmp_path,
        resolve_share_path=lambda relative: tmp_path / "share" / relative,
    )

    handle = module._acquire_pipeline_run_lock(env, "page")
    assert handle is not None
    lock_path = Path(handle["path"])
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["schema"] == module.PIPELINE_LOCK_SCHEMA

    before = payload["heartbeat_at"]
    module._refresh_pipeline_run_lock(handle)
    refreshed = json.loads(lock_path.read_text(encoding="utf-8"))
    assert refreshed["heartbeat_at"] >= before

    module._release_pipeline_run_lock(handle, "page")
    assert not lock_path.exists()
    assert any("Pipeline lock released" in line for line in fake_st.session_state["page__run_logs"])

    lock_path.write_text(json.dumps({"host": "remote", "pid": 123, "app": "demo"}), encoding="utf-8")
    busy = module._acquire_pipeline_run_lock(env, "page")
    assert busy is None
    assert any(kind == "warning" and "already running" in message for kind, message in fake_st.messages)

    old = module.time.time() - 10
    os.utime(lock_path, (old, old))
    stale_handle = module._acquire_pipeline_run_lock(env, "page")
    assert stale_handle is not None
    assert Path(stale_handle["path"]).exists()
    module._release_pipeline_run_lock(stale_handle, "page")

    monkeypatch.setattr(module, "_clear_pipeline_run_lock", lambda *_args, **_kwargs: False)
    assert module._acquire_pipeline_run_lock(env, "page", force=True) is None


def test_pipeline_run_controls_edge_branches_for_logs_ttl_and_lock_payloads(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)

    placeholder = _FakePlaceholder()
    bad_log_path = tmp_path / "bad-log-dir"
    bad_log_path.mkdir()
    fake_st.session_state["page__run_log_file"] = str(bad_log_path)
    module._push_run_log("page", "cannot append", placeholder)
    assert placeholder.codes[-1] == "cannot append"

    calls: list[object] = []

    class _RerunStreamlit(_FakeStreamlit):
        def rerun(self, scope=None):
            calls.append(scope)
            if scope == "fragment":
                raise module.StreamlitAPIException("fragment unavailable")

    monkeypatch.setattr(module, "st", _RerunStreamlit(fake_st.session_state))
    module._rerun_fragment_or_app()
    assert calls == ["fragment", None]

    monkeypatch.delenv("AGILAB_PIPELINE_LOCK_TTL_SEC", raising=False)
    assert module._pipeline_lock_ttl_seconds() == module.PIPELINE_LOCK_DEFAULT_TTL_SEC
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "not-a-number")
    assert module._pipeline_lock_ttl_seconds() == module.PIPELINE_LOCK_DEFAULT_TTL_SEC
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "-1")
    assert module._pipeline_lock_ttl_seconds() == module.PIPELINE_LOCK_DEFAULT_TTL_SEC
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "2.5")
    assert module._pipeline_lock_ttl_seconds() == 2.5

    missing = tmp_path / "missing.lock"
    invalid = tmp_path / "invalid.lock"
    list_payload = tmp_path / "list.lock"
    invalid.write_text("{", encoding="utf-8")
    list_payload.write_text("[]", encoding="utf-8")
    assert module._read_pipeline_lock_payload(missing) == {}
    assert module._read_pipeline_lock_payload(invalid) == {}
    assert module._read_pipeline_lock_payload(list_payload) == {}

    monkeypatch.setattr(module.os, "kill", lambda *_args: None)
    assert module._pipeline_lock_owner_alive({"host": socket.gethostname(), "pid": os.getpid()}) is True

    placeholder_obj = object()
    fake_st.session_state["page__run_placeholder"] = placeholder_obj
    assert module._get_run_placeholder("page") is placeholder_obj


def test_pipeline_run_controls_lock_failure_branches(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    env = SimpleNamespace(app="demo", target="demo")

    locked_dir = tmp_path / "lock-as-dir"
    locked_dir.mkdir()
    monkeypatch.setattr(module, "_inspect_pipeline_run_lock", lambda _env: {"path": locked_dir})
    assert module._clear_pipeline_run_lock(env, "page", reason="unit-test") is False
    assert any(kind == "error" and "Unable to remove pipeline lock" in msg for kind, msg in fake_st.messages)

    lock_path = tmp_path / "cannot-open.lock"
    monkeypatch.setattr(module, "_pipeline_lock_path", lambda _env: lock_path)
    monkeypatch.setattr(module.os, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    assert module._acquire_pipeline_run_lock(env, "page") is None
    assert any(kind == "error" and "Unable to acquire pipeline lock" in msg for kind, msg in fake_st.messages)

    module._refresh_pipeline_run_lock(None)
    module._refresh_pipeline_run_lock({})
    module._refresh_pipeline_run_lock({"path": tmp_path / "missing.lock", "token": "token"})

    refresh_lock = tmp_path / "refresh.lock"
    refresh_lock.write_text(json.dumps({"token": "other"}), encoding="utf-8")
    module._refresh_pipeline_run_lock({"path": refresh_lock, "token": "token"})
    assert json.loads(refresh_lock.read_text(encoding="utf-8")) == {"token": "other"}

    refresh_lock.write_text(json.dumps({"token": "token"}), encoding="utf-8")
    monkeypatch.setattr(module.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))
    module._refresh_pipeline_run_lock({"path": refresh_lock, "token": "token"})

    module._release_pipeline_run_lock(None, "page")
    module._release_pipeline_run_lock({}, "page")
    module._release_pipeline_run_lock({"path": tmp_path / "missing-release.lock", "token": "token"}, "page")

    release_lock = tmp_path / "release.lock"
    release_lock.write_text(json.dumps({"token": "other"}), encoding="utf-8")
    module._release_pipeline_run_lock({"path": release_lock, "token": "token"}, "page")
    assert release_lock.exists()

    release_dir = tmp_path / "release-dir"
    release_dir.mkdir()
    module._release_pipeline_run_lock({"path": release_dir, "token": "token"}, "page")


def test_pipeline_run_controls_stale_owner_and_retry_exhaustion_branches(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "3600")
    env = SimpleNamespace(app="demo", target="demo")

    lock_path = tmp_path / "owner.lock"
    lock_path.write_text(
        json.dumps({"host": socket.gethostname(), "pid": 123456, "app": "demo"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_pipeline_lock_path", lambda _env: lock_path)
    monkeypatch.setattr(module.os, "kill", lambda *_args: (_ for _ in ()).throw(ProcessLookupError()))

    state = module._inspect_pipeline_run_lock(env)

    assert state is not None
    assert state["is_stale"] is True
    assert state["stale_reason"] == "owner process is no longer running on this host"

    missing_lock = tmp_path / "missing-clear.lock"
    monkeypatch.setattr(module, "_inspect_pipeline_run_lock", lambda _env: {"path": missing_lock})
    assert module._clear_pipeline_run_lock(env, "page", reason="race") is True

    sticky_lock = tmp_path / "sticky.lock"
    sticky_lock.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "_pipeline_lock_path", lambda _env: sticky_lock)
    monkeypatch.setattr(
        module,
        "_inspect_pipeline_run_lock",
        lambda _env: {
            "path": sticky_lock,
            "is_stale": True,
            "stale_reason": "unit stale",
            "owner_text": "owner",
        },
    )
    monkeypatch.setattr(module, "_clear_pipeline_run_lock", lambda *_args, **_kwargs: True)

    assert module._acquire_pipeline_run_lock(env, "page") is None
    assert any(
        kind == "warning" and "after stale cleanup retries" in message
        for kind, message in fake_st.messages
    )


def test_pipeline_run_controls_legacy_step_formatting_and_clean_abort(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)

    stale_steps = [
        {"step": idx, "line": idx + 10, "project": f"app-{idx}", "summary": f"summary-{idx}"}
        for idx in range(1, 7)
    ]

    formatted = module._format_legacy_step_refs(stale_steps)

    assert "step 1, line 11, app-1: summary-1" in formatted
    assert "1 more" in formatted

    assert module._abort_if_legacy_agi_run_steps(
        "page",
        tmp_path / "lab_steps.toml",
        [{"Q": "fresh", "C": "print('ok')"}],
        [0],
        None,
    ) is False

    assert module._abort_if_legacy_agi_run_steps(
        "page",
        tmp_path / "lab_steps.toml",
        [{"Q": "stale", "C": "await AGI.run(app_env, mode=0)", "R": "agi.run"}],
        [0],
        None,
    ) is True
    assert any(kind == "error" and "aborted before execution" in message for kind, message in fake_st.messages)


def test_pipeline_run_controls_run_all_steps_executes_runpy_and_agi_run(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('snippet')", encoding="utf-8")
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    steps_dir = tmp_path / "same" / "same"
    steps_dir.mkdir(parents=True)
    steps_file = steps_dir / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")
    export_file = tmp_path / "export.csv"

    fake_st = _FakeStreamlit(
        {
            "page": [99, "old desc", "old q", "old model", "old code", "old detail", 0],
            "page__run_sequence": [0, 1, 2, 99],
            "page__details": {1: "detail from editor"},
            "page__engine_map": {1: "runpy"},
            "snippet_file": str(snippet_file),
            "df_file_out": str(export_file),
            "data": module.pd.DataFrame({"x": [1]}),
            "lab_selected_venv": "",
            "lab_selected_engine": "old-engine",
        }
    )
    monkeypatch.setattr(module, "st", fake_st)

    refreshes: list[dict] = []
    releases: list[dict] = []
    artifact_calls: list[dict] = []
    stream_calls: list[dict] = []
    saved_exports: list[str] = []
    mlflow_calls: list[dict] = []

    @contextmanager
    def fake_start_mlflow_run(_env, **kwargs):
        mlflow_calls.append(kwargs)
        yield {"run": SimpleNamespace(info=SimpleNamespace(run_id=f"run-{len(mlflow_calls)}"))}

    monkeypatch.setattr(module._pipeline_runtime, "mlflow_tracking_uri", lambda _env: "sqlite:///mlflow.db")
    monkeypatch.setattr(module._pipeline_runtime, "start_mlflow_run", fake_start_mlflow_run)
    monkeypatch.setattr(
        module._pipeline_runtime,
        "log_mlflow_artifacts",
        lambda _tracking, **kwargs: artifact_calls.append(kwargs),
    )
    monkeypatch.setattr(
        module._pipeline_runtime,
        "build_mlflow_process_env",
        lambda _env, *, run_id=None: {"MLFLOW_RUN_ID": run_id or ""},
    )
    monkeypatch.setattr(module._pipeline_runtime, "wrap_code_with_mlflow_resume", lambda code: f"# wrapped\n{code}")
    monkeypatch.setattr(module._pipeline_runtime, "python_for_step", lambda *_args, **_kwargs: "pythonX")
    monkeypatch.setattr(
        module._pipeline_runtime,
        "label_for_step_runtime",
        lambda runtime, *, engine, code: f"{engine}:{Path(runtime).name if runtime else 'default'}",
    )
    monkeypatch.setattr(module._pipeline_runtime, "is_valid_runtime_root", lambda value: str(value) == str(runtime_root))
    monkeypatch.setattr(module._pipeline_steps, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_steps, "is_runnable_step", lambda entry: bool(entry.get("C")))
    monkeypatch.setattr(module._pipeline_steps, "step_summary", lambda _entry, width=80: f"summary:{width}")
    monkeypatch.setattr(module, "run_lab", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(module, "save_csv", lambda _data, target: saved_exports.append(str(target)) or True)
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: {"path": "lock", "token": "t"})
    monkeypatch.setattr(module, "_refresh_pipeline_run_lock", lambda handle: refreshes.append(handle))
    monkeypatch.setattr(module, "_release_pipeline_run_lock", lambda handle, *_args, **_kwargs: releases.append(handle))

    def fake_stream_run_command(env, index_page, cmd, cwd, **kwargs):
        stream_calls.append({"cmd": cmd, "cwd": cwd, "extra_env": kwargs.get("extra_env")})
        return "No such file or directory: missing.csv"

    steps = [
        {"D": "first", "Q": "q1", "M": "m1", "C": "print(1)"},
        {"D": "second", "Q": "q2", "M": "m2", "C": "print(2)", "E": str(runtime_root), "R": "runpy"},
        {"D": "skip", "Q": "q3", "M": "m3", "C": ""},
    ]
    env = SimpleNamespace(app="demo", active_app=str(runtime_root), copilot_file=tmp_path / "copilot.py")

    module.run_all_steps(
        tmp_path / "lab",
        "page",
        steps_file,
        tmp_path / "module.py",
        env,
        load_all_steps_fn=lambda *_args: steps,
        stream_run_command_fn=fake_stream_run_command,
    )

    assert any(kind == "success" and "Executed 2 steps." in message for kind, message in fake_st.messages)
    assert any("Run pipeline completed: 2 step(s) executed." in line for line in fake_st.session_state["page__run_logs"])
    assert any("No such file or directory" in line for line in fake_st.session_state["page__run_logs"])
    assert any("AGI_CLUSTER_SHARE" in line for line in fake_st.session_state["page__run_logs"])
    assert stream_calls[0]["cmd"][0] == "pythonX"
    assert stream_calls[0]["cwd"] == steps_dir.parent.resolve()
    assert stream_calls[0]["extra_env"]["MLFLOW_RUN_ID"] == "run-3"
    assert saved_exports == [str(export_file), str(export_file)]
    assert fake_st.session_state["df_file_in"] == str(export_file)
    assert fake_st.session_state["step_checked"] is True
    assert fake_st.session_state["page"][0] == 99
    assert fake_st.session_state["lab_selected_venv"] == ""
    assert fake_st.session_state["lab_selected_engine"] == "old-engine"
    assert fake_st.session_state["page__force_blank_q"] is True
    assert fake_st.session_state["page__q_rev"] == 1
    assert fake_st.session_state["page__venv_map"][1] == str(runtime_root)
    assert refreshes and releases == [{"path": "lock", "token": "t"}]
    assert artifact_calls
    assert mlflow_calls[1]["nested"] is True


def test_pipeline_run_controls_run_all_steps_handles_early_exits(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit({"page": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module._pipeline_steps, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_steps, "is_runnable_step", lambda entry: bool(entry.get("C")))
    env = SimpleNamespace(app="demo", active_app="", copilot_file=tmp_path / "copilot.py")

    module.run_all_steps(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_steps.toml",
        tmp_path / "module.py",
        env,
        load_all_steps_fn=lambda *_args: [],
        stream_run_command_fn=lambda *_args, **_kwargs: "",
    )
    assert any(kind == "info" and "No steps available" in message for kind, message in fake_st.messages)

    module.run_all_steps(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_steps.toml",
        tmp_path / "module.py",
        env,
        load_all_steps_fn=lambda *_args: [{"C": "print(1)"}],
        stream_run_command_fn=lambda *_args, **_kwargs: "",
    )
    assert any(kind == "error" and "Snippet file is not configured" in message for kind, message in fake_st.messages)

    fake_st.session_state["snippet_file"] = str(tmp_path / "snippet.py")
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: None)
    module.run_all_steps(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_steps.toml",
        tmp_path / "module.py",
        env,
        load_all_steps_fn=lambda *_args: [{"C": "print(1)"}],
        stream_run_command_fn=lambda *_args, **_kwargs: "",
    )
    assert fake_st.session_state["page__run_logs"].count("Run pipeline invoked.") == 3


def test_pipeline_run_controls_run_all_steps_reports_no_runnable_code(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('snippet')", encoding="utf-8")
    fake_st = _FakeStreamlit(
        {
            "page": [3, "old desc", "old q", "old model", "old code", "old detail", 0],
            "snippet_file": str(snippet_file),
            "lab_selected_venv": "",
            "lab_selected_engine": "",
        }
    )
    monkeypatch.setattr(module, "st", fake_st)
    releases: list[dict] = []

    @contextmanager
    def no_mlflow_run(*_args, **_kwargs):
        yield None

    monkeypatch.setattr(module._pipeline_runtime, "mlflow_tracking_uri", lambda _env: "")
    monkeypatch.setattr(module._pipeline_runtime, "start_mlflow_run", no_mlflow_run)
    monkeypatch.setattr(module._pipeline_steps, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_steps, "is_runnable_step", lambda entry: bool(entry.get("C")))
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: {"path": "lock", "token": "t"})
    monkeypatch.setattr(module, "_refresh_pipeline_run_lock", lambda _handle: None)
    monkeypatch.setattr(module, "_release_pipeline_run_lock", lambda handle, *_args, **_kwargs: releases.append(handle))

    env = SimpleNamespace(app="demo", active_app="", copilot_file=tmp_path / "copilot.py")
    module.run_all_steps(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_steps.toml",
        tmp_path / "module.py",
        env,
        load_all_steps_fn=lambda *_args: [{"D": "skip", "Q": "no code", "M": "model", "C": ""}],
        stream_run_command_fn=lambda *_args, **_kwargs: "should not run",
    )

    assert any(kind == "info" and "No runnable code found" in message for kind, message in fake_st.messages)
    assert any("no runnable code found" in line for line in fake_st.session_state["page__run_logs"])
    assert fake_st.session_state["page"][0] == 3
    assert releases == [{"path": "lock", "token": "t"}]


def test_pipeline_run_controls_blocks_legacy_agi_run_before_lock(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('snippet')", encoding="utf-8")
    fake_st = _FakeStreamlit(
        {
            "page": [0, "", "", "", "", "", 0],
            "page__run_sequence": [0],
            "snippet_file": str(snippet_file),
            "lab_selected_venv": "",
            "lab_selected_engine": "",
        }
    )
    monkeypatch.setattr(module, "st", fake_st)

    def fail_if_lock_acquired(*_args, **_kwargs):
        raise AssertionError("stale snippets must abort before acquiring pipeline lock")

    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", fail_if_lock_acquired)

    stale_code = (
        "from agi_cluster.agi_distributor import AGI\n"
        'APP = "flight_trajectory_project"\n'
        "async def main(app_env):\n"
        "    res = await AGI.run(app_env, mode=4, data_in='in', data_out='out')\n"
        "    return res\n"
    )
    env = SimpleNamespace(app="demo", active_app="", copilot_file=tmp_path / "copilot.py")

    module.run_all_steps(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_steps.toml",
        tmp_path / "module.py",
        env,
        load_all_steps_fn=lambda *_args: [{"Q": "Generate flight trajectories", "C": stale_code, "R": "agi.run"}],
        stream_run_command_fn=lambda *_args, **_kwargs: "should not execute",
    )

    assert any(kind == "error" and "aborted before execution" in message for kind, message in fake_st.messages)
    assert any("RunRequest" in line and "step 1" in line for line in fake_st.session_state["page__run_logs"])
    assert not any("Running step 1" in line for line in fake_st.session_state["page__run_logs"])


def test_pipeline_run_controls_run_all_steps_without_mlflow_tracks_runpy_no_output(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('snippet')", encoding="utf-8")
    fake_st = _FakeStreamlit(
        {
            "page": [7, "old desc", "old q", "old model", "old code", "old detail", 0],
            "snippet_file": str(snippet_file),
            "lab_selected_venv": "",
            "lab_selected_engine": "old-engine",
        }
    )
    monkeypatch.setattr(module, "st", fake_st)

    run_lab_calls: list[dict] = []
    releases: list[dict] = []

    @contextmanager
    def no_mlflow_run(*_args, **_kwargs):
        yield None

    monkeypatch.setattr(module._pipeline_runtime, "mlflow_tracking_uri", lambda _env: "")
    monkeypatch.setattr(module._pipeline_runtime, "start_mlflow_run", no_mlflow_run)
    monkeypatch.setattr(module._pipeline_runtime, "build_mlflow_process_env", lambda _env, *, run_id=None: {})
    monkeypatch.setattr(
        module._pipeline_runtime,
        "label_for_step_runtime",
        lambda runtime, *, engine, code: f"{engine}:{runtime or 'default'}",
    )
    monkeypatch.setattr(module._pipeline_runtime, "is_valid_runtime_root", lambda _value: False)
    monkeypatch.setattr(module._pipeline_steps, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_steps, "is_runnable_step", lambda entry: bool(entry.get("C")))
    monkeypatch.setattr(module._pipeline_steps, "step_summary", lambda entry, width=80: entry.get("Q", ""))
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: {"path": "lock", "token": "t"})
    monkeypatch.setattr(module, "_refresh_pipeline_run_lock", lambda _handle: None)
    monkeypatch.setattr(module, "_release_pipeline_run_lock", lambda handle, *_args, **_kwargs: releases.append(handle))
    monkeypatch.setattr(
        module,
        "run_lab",
        lambda payload, snippet, copilot, **kwargs: run_lab_calls.append(
            {"payload": payload, "snippet": snippet, "copilot": copilot, "kwargs": kwargs}
        ) or "",
    )

    env = SimpleNamespace(app="demo", active_app="", copilot_file=tmp_path / "copilot.py")
    module.run_all_steps(
        tmp_path / "lab",
        "page",
        tmp_path / "steps" / "lab_steps.toml",
        tmp_path / "module.py",
        env,
        load_all_steps_fn=lambda *_args: [{"D": "desc", "Q": "question", "M": "model", "C": "print(1)"}],
        stream_run_command_fn=lambda *_args, **_kwargs: "should not run",
    )

    assert run_lab_calls == [
        {
            "payload": ["desc", "question", "print(1)"],
            "snippet": str(snippet_file),
            "copilot": env.copilot_file,
            "kwargs": {"env_overrides": {}},
        }
    ]
    assert any(kind == "success" and "Executed 1 step." in message for kind, message in fake_st.messages)
    assert any("runpy executed (no captured stdout)" in line for line in fake_st.session_state["page__run_logs"])
    assert fake_st.session_state["page"][0] == 7
    assert fake_st.session_state["lab_selected_engine"] == "old-engine"
    assert releases == [{"path": "lock", "token": "t"}]


def test_pipeline_run_controls_run_all_steps_uses_active_app_for_agi_engine(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('snippet')", encoding="utf-8")
    runtime_root = tmp_path / "active_app_runtime"
    runtime_root.mkdir()
    fake_st = _FakeStreamlit(
        {
            "page": [4, "old desc", "old q", "old model", "old code", "old detail", 0],
            "snippet_file": str(snippet_file),
            "lab_selected_venv": "",
            "lab_selected_engine": "",
        }
    )
    monkeypatch.setattr(module, "st", fake_st)

    stream_calls: list[dict] = []
    releases: list[dict] = []

    @contextmanager
    def no_mlflow_run(*_args, **_kwargs):
        yield None

    monkeypatch.setattr(module._pipeline_runtime, "mlflow_tracking_uri", lambda _env: "")
    monkeypatch.setattr(module._pipeline_runtime, "start_mlflow_run", no_mlflow_run)
    monkeypatch.setattr(module._pipeline_runtime, "build_mlflow_process_env", lambda _env, *, run_id=None: {})
    monkeypatch.setattr(module._pipeline_runtime, "wrap_code_with_mlflow_resume", lambda code: code)
    monkeypatch.setattr(
        module._pipeline_runtime,
        "python_for_step",
        lambda runtime, *, engine, code: f"python-for-{Path(runtime).name}",
    )
    monkeypatch.setattr(
        module._pipeline_runtime,
        "label_for_step_runtime",
        lambda runtime, *, engine, code: f"{engine}:{Path(runtime).name if runtime else 'default'}",
    )
    monkeypatch.setattr(module._pipeline_runtime, "is_valid_runtime_root", lambda value: str(value) == str(runtime_root))
    monkeypatch.setattr(module._pipeline_steps, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_steps, "is_runnable_step", lambda entry: bool(entry.get("C")))
    monkeypatch.setattr(module._pipeline_steps, "step_summary", lambda entry, width=80: entry.get("Q", ""))
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: {"path": "lock", "token": "t"})
    monkeypatch.setattr(module, "_refresh_pipeline_run_lock", lambda _handle: None)
    monkeypatch.setattr(module, "_release_pipeline_run_lock", lambda handle, *_args, **_kwargs: releases.append(handle))

    def fake_stream_run_command(env, index_page, cmd, cwd, **kwargs):
        stream_calls.append({"cmd": cmd, "cwd": cwd, "extra_env": kwargs.get("extra_env")})
        return "completed"

    env = SimpleNamespace(app="demo", active_app=str(runtime_root), copilot_file=tmp_path / "copilot.py")
    module.run_all_steps(
        tmp_path / "lab",
        "page",
        tmp_path / "steps" / "lab_steps.toml",
        tmp_path / "module.py",
        env,
        load_all_steps_fn=lambda *_args: [{"D": "desc", "Q": "question", "M": "model", "C": "print(1)", "R": "agi.run"}],
        stream_run_command_fn=fake_stream_run_command,
    )

    assert stream_calls
    assert stream_calls[0]["cmd"][0] == "python-for-active_app_runtime"
    assert fake_st.session_state["lab_selected_venv"] == ""
    assert any(
        "engine=agi.run, env=agi.run:active_app_runtime" in line
        for line in fake_st.session_state["page__run_logs"]
    )
    assert releases == [{"path": "lock", "token": "t"}]
