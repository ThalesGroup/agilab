from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import socket
import sys
import time
import types
from types import SimpleNamespace


def _import_pipeline_run_controls():
    repo_root = Path(__file__).resolve().parents[1]
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    for import_root in (str(repo_root), src_root_str):
        if import_root not in sys.path:
            sys.path.insert(0, import_root)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        pkg.__file__ = str(package_root / "__init__.py")
        sys.modules["agilab"] = pkg
    elif package_root_str not in list(pkg.__path__):
        pkg.__path__ = [package_root_str, *list(pkg.__path__)]
    importlib.invalidate_caches()
    # Import the implementation directly so another test importing the legacy
    # compatibility shim first cannot leave copied helper globals behind.
    return importlib.import_module("agilab.pipeline.pipeline_run_controls")


def _pipeline_lock_process(root: str, ready, release) -> None:
    module = _import_pipeline_run_controls()
    module.st = _FakeStreamlit()
    root_path = Path(root)
    env = SimpleNamespace(
        app="demo",
        target="demo",
        home_abs=root_path,
        resolve_share_path=lambda relative: root_path / "share" / relative,
    )
    handle = module._acquire_pipeline_run_lock(env, "page")
    ready.put(bool(handle))
    release.wait(timeout=10)
    module._release_pipeline_run_lock(handle, "page")


class _FakePlaceholder:
    def __init__(self) -> None:
        self.codes: list[str] = []
        self.code_kwargs: list[dict] = []
        self.captions: list[str] = []

    def code(self, value: str, **kwargs) -> None:
        self.codes.append(value)
        self.code_kwargs.append(kwargs)

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
    monkeypatch.setattr(module._pipeline_stages, "stage_summary", lambda _entry, width=80: f"summary:{width}")

    env = SimpleNamespace(app="demo", runenv=tmp_path / "logs")
    run_name, tags, params, text_artifacts = module._mlflow_parent_payload(
        env,
        tmp_path / "lab",
        tmp_path / "lab_stages.toml",
        [0, 2],
    )

    assert run_name == "demo:lab:pipeline"
    assert tags["agilab.tracking_uri"] == "sqlite:///mlflow.db"
    assert params["sequence"] == "1,3"
    assert params["stage_count"] == 2
    assert params["profile"] == "balanced"
    assert params["max_workers"] == 1
    assert params["wave_count"] == 0
    assert params["agilab_version"]
    assert json.loads(text_artifacts["pipeline_metadata/sequence.json"])["sequence"] == [1, 3]

    stage_name, stage_tags, stage_params, stage_artifacts = module._mlflow_stage_payload(
        env,
        tmp_path / "lab",
        tmp_path / "lab_stages.toml",
        stage_index=1,
        entry={"D": "desc", "Q": "question", "M": "model", "C": "print(1)"},
        engine="agi.run",
        runtime_root="/runtime",
    )

    assert stage_name == "demo:lab:stage_2"
    assert stage_tags["agilab.summary"] == "summary:80"
    assert stage_params["engine"] == "agi.run"
    assert json.loads(stage_artifacts["stage_2/stage_entry.json"])["stage_index"] == 2

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
    assert placeholder.code_kwargs[-1]["height"] == module.PIPELINE_RUN_LOG_HEIGHT

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
    assert direct_lock.exists()
    assert module._read_pipeline_lock_payload(direct_lock) == {}
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
    assert lock_path.exists()
    assert module._read_pipeline_lock_payload(lock_path) == {}
    assert any("Workflow lock released" in line for line in fake_st.session_state["page__run_logs"])

    owner = module._acquire_pipeline_run_lock(env, "page")
    assert owner is not None
    busy = module._acquire_pipeline_run_lock(env, "page")
    assert busy is None
    assert any(kind == "warning" and "already running" in message for kind, message in fake_st.messages)
    module._release_pipeline_run_lock(owner, "page")

    lock_path.write_text(json.dumps({"host": "remote", "pid": 123, "app": "demo"}), encoding="utf-8")
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
    fake_st.session_state.pop("page__run_logs", None)
    monkeypatch.setattr(module, "_append_run_log", lambda *_args, **_kwargs: None)
    module._push_run_log("page", "", placeholder)
    assert placeholder.captions[-1] == "No runs recorded yet."

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
    monkeypatch.setattr(module, "_pipeline_lock_path", lambda _env: locked_dir)
    assert module._clear_pipeline_run_lock(env, "page", reason="unit-test") is False
    assert any(kind == "error" and "Unable to clear workflow lock" in msg for kind, msg in fake_st.messages)

    lock_path = tmp_path / "cannot-open.lock"
    monkeypatch.setattr(module, "_pipeline_lock_path", lambda _env: lock_path)
    monkeypatch.setattr(module.os, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    assert module._acquire_pipeline_run_lock(env, "page") is None
    assert any(kind == "error" and "Unable to acquire workflow lock" in msg for kind, msg in fake_st.messages)

    module._refresh_pipeline_run_lock(None)
    module._refresh_pipeline_run_lock({})
    module._refresh_pipeline_run_lock({"path": tmp_path / "unused.lock", "token": ""})
    module._refresh_pipeline_run_lock({"path": tmp_path / "missing.lock", "token": "token"})

    refresh_lock = tmp_path / "refresh.lock"
    module._refresh_pipeline_run_lock({"path": refresh_lock, "token": "token"})

    module._release_pipeline_run_lock(None, "page")
    module._release_pipeline_run_lock({}, "page")
    module._release_pipeline_run_lock({"path": tmp_path / "unused.lock", "token": ""}, "page")
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
    monkeypatch.setattr(module, "_pipeline_lock_path", lambda _env: missing_lock)
    assert module._clear_pipeline_run_lock(env, "page", reason="race") is True

    sticky_lock = tmp_path / "sticky.lock"
    sticky_lock.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "_pipeline_lock_path", lambda _env: sticky_lock)
    monkeypatch.setattr(module, "_try_pipeline_file_lock", lambda _fd: False)
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

    monkeypatch.setattr(module, "_clear_pipeline_run_lock", lambda *_args, **_kwargs: False)
    assert module._acquire_pipeline_run_lock(env, "page") is None


def test_clear_pipeline_lock_does_not_unlock_unowned_file(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    lock_path = tmp_path / "busy.lock"
    monkeypatch.setattr(module, "_pipeline_lock_path", lambda _env: lock_path)
    monkeypatch.setattr(module, "_try_pipeline_file_lock", lambda _fd: False)
    monkeypatch.setattr(
        module,
        "_inspect_pipeline_run_lock",
        lambda _env: {"owner_text": "another session"},
    )
    unlocks: list[int] = []
    monkeypatch.setattr(module, "_unlock_pipeline_file", unlocks.append)

    assert module._clear_pipeline_run_lock(
        SimpleNamespace(app="demo", target="demo"),
        "page",
        reason="unit test",
    ) is False
    assert unlocks == []


def test_pipeline_lock_holds_identity_across_refresh_release_and_stale_clear(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setenv("AGILAB_PIPELINE_LOCK_TTL_SEC", "0.15")
    env = SimpleNamespace(
        app="demo",
        target="demo",
        home_abs=tmp_path,
        resolve_share_path=lambda relative: tmp_path / "share" / relative,
    )

    first = module._acquire_pipeline_run_lock(env, "page")
    assert first is not None
    initial_heartbeat = module._read_pipeline_lock_payload(Path(first["path"]))["heartbeat_at"]
    target_base = tmp_path / "parallel-wave"
    target_base.mkdir()
    stages_file = target_base / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(module, "_resolve_stage_engine_runtime", lambda *_args, **_kwargs: ("agi.run", str(tmp_path)))
    monkeypatch.setattr(module._pipeline_stages, "stage_summary", lambda *_args, **_kwargs: "stage")
    monkeypatch.setattr(module._pipeline_runtime, "label_for_stage_runtime", lambda *_args, **_kwargs: "runtime")
    monkeypatch.setattr(module._pipeline_runtime, "wrap_code_with_mlflow_resume", lambda code: code)
    monkeypatch.setattr(module._pipeline_runtime, "python_for_stage", lambda *_args, **_kwargs: "python")
    monkeypatch.setattr(module, "_stage_output_records", lambda *_args, **_kwargs: [])

    def slow_stage(*_args, **_kwargs):
        time.sleep(0.22)
        return "ok"

    monkeypatch.setattr(module, "_run_stage_subprocess", slow_stage)
    records: list[dict] = []
    assert module._run_parallel_agi_wave(
        stages=[{"C": "print(1)"}, {"C": "print(2)"}],
        wave=[0, 1],
        profile="balanced",
        env=env,
        index_page="page",
        stages_file=stages_file,
        run_id="heartbeat",
        selected_map={},
        engine_map={},
        default_runtime="",
        target_base=target_base,
        max_workers=2,
        manifest_stage_records=records,
        log_placeholder=None,
    ) == 2
    heartbeat = module._read_pipeline_lock_payload(Path(first["path"]))["heartbeat_at"]
    assert heartbeat > initial_heartbeat
    assert module._clear_pipeline_run_lock(env, "page", reason="expired-looking metadata") is False
    module._release_pipeline_run_lock(first, "page")

    second = module._acquire_pipeline_run_lock(env, "page")
    assert second is not None
    second_token = module._read_pipeline_lock_payload(Path(second["path"]))["token"]
    module._refresh_pipeline_run_lock(first)
    module._release_pipeline_run_lock(first, "page")
    assert module._read_pipeline_lock_payload(Path(second["path"]))["token"] == second_token
    module._release_pipeline_run_lock(second, "page")


def test_pipeline_lock_is_exclusive_across_processes(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    monkeypatch.setattr(module, "st", _FakeStreamlit())
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    release = context.Event()
    process = context.Process(target=_pipeline_lock_process, args=(str(tmp_path), ready, release))
    process.start()
    assert ready.get(timeout=10) is True
    env = SimpleNamespace(
        app="demo",
        target="demo",
        home_abs=tmp_path,
        resolve_share_path=lambda relative: tmp_path / "share" / relative,
    )
    assert module._acquire_pipeline_run_lock(env, "page") is None
    release.set()
    process.join(timeout=10)
    assert process.exitcode == 0


def test_parallel_wave_rejects_equal_nested_and_aliased_declared_outputs(tmp_path):
    module = _import_pipeline_run_controls()
    env = SimpleNamespace(share_root=tmp_path)
    stages_file = tmp_path / "lab_stages.toml"
    stages = [
        {
            "id": "left",
            "deps": ["seed"],
            "C": "print('left')",
            "automation": {"parallel_safe": True, "outputs": ["out/data"]},
        },
        {
            "id": "right",
            "deps": ["seed"],
            "C": "print('right')",
            "automation": {"parallel_safe": True, "outputs": ["out/data/result.csv"]},
        },
        {"id": "seed", "C": "print('seed')"},
    ]

    waves, error, _ids, _deps = module._build_stage_waves(
        stages,
        [2, 0, 1],
        "balanced",
        env=env,
        stages_file=stages_file,
    )

    assert waves == []
    assert error is not None
    assert "overlapping output paths" in error
    assert "Add a dependency to serialize" in error
    assert module._declared_outputs_overlap("out/data", "out/data/result.csv") is True
    assert module._declared_outputs_overlap("out/data", "out/database") is False
    assert module._declared_outputs_overlap("a/../b", "b/result.json") is True
    assert module._declared_outputs_overlap("Case/Output", "case/output/result.json") is True

    real_dir = tmp_path / "real-output"
    real_dir.mkdir()
    alias_dir = tmp_path / "output-alias"
    try:
        alias_dir.symlink_to(real_dir, target_is_directory=True)
    except OSError:
        return
    assert module._declared_outputs_overlap(
        "output-alias/result",
        "real-output/result/file.json",
        env=env,
        stages_file=stages_file,
    ) is True


def test_parallel_wave_serializes_stages_without_complete_output_contracts(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    env = SimpleNamespace(share_root=tmp_path)
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "_resolve_stage_engine_runtime",
        lambda *_args, **_kwargs: ("agi.run", str(tmp_path / "runtime")),
    )

    unknown_stages = [
        {"id": "seed", "C": "print('seed')"},
        {"id": "left", "deps": ["seed"], "C": "print('left')"},
        {"id": "right", "deps": ["seed"], "C": "print('right')"},
    ]
    waves, error, _ids, _deps = module._build_stage_waves(
        unknown_stages,
        [0, 1, 2],
        "balanced",
        env=env,
        stages_file=stages_file,
    )
    assert error is None
    assert waves == [[0], [1, 2]]
    reason = module._parallel_agi_wave_ineligibility_reason(
        unknown_stages,
        [1, 2],
        profile="balanced",
        env=env,
        stages_file=stages_file,
        selected_map={},
        engine_map={},
        default_runtime="",
    )

    assert reason is not None
    assert "parallel_safe" in reason
    assert module._parallel_agi_wave_eligible(
        unknown_stages,
        [1, 2],
        profile="balanced",
        env=env,
        stages_file=stages_file,
        selected_map={},
        engine_map={},
        default_runtime="",
    ) is False

    safe_stage = {
        "id": "safe",
        "C": "print('safe')",
        "automation": {"parallel_safe": True, "outputs": ["out/safe"]},
    }
    unsafe_stages = [
        {
            "id": "default_output",
            "D": "out/inferred-default",
            "C": "print('default')",
            "automation": {"parallel_safe": True},
        },
        {
            "id": "dynamic_output",
            "C": "print('dynamic')",
            "automation": {"parallel_safe": True, "outputs": ["out/{run_id}"]},
        },
        {
            "id": "shell_variable_output",
            "C": "print('dynamic')",
            "automation": {"parallel_safe": True, "outputs": ["$RUN_ROOT/out"]},
        },
    ]
    for unsafe_stage, expected in (
        (unsafe_stages[0], "complete `automation.outputs`"),
        (unsafe_stages[1], "dynamic or invalid"),
        (unsafe_stages[2], "dynamic or invalid"),
    ):
        reason = module._parallel_agi_wave_ineligibility_reason(
            [unsafe_stage, safe_stage],
            [0, 1],
            profile="balanced",
            env=env,
            stages_file=stages_file,
            selected_map={},
            engine_map={},
            default_runtime="",
        )
        assert reason is not None
        assert expected in reason


def test_parallel_wave_accepts_explicit_disjoint_output_contracts(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    env = SimpleNamespace(share_root=tmp_path)
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    stages = [
        {"id": "seed", "C": "print('seed')"},
        {
            "id": "left",
            "deps": ["seed"],
            "C": "print('left')",
            "automation": {"parallel_safe": True, "outputs": ["out/left"]},
        },
        {
            "id": "right",
            "deps": ["seed"],
            "C": "print('right')",
            "automation": {"parallel_safe": True, "outputs": ["out/right"]},
        },
    ]
    monkeypatch.setattr(
        module,
        "_resolve_stage_engine_runtime",
        lambda *_args, **_kwargs: ("agi.run", str(tmp_path / "runtime")),
    )

    waves, error, _ids, _deps = module._build_stage_waves(
        stages,
        [0, 1, 2],
        "balanced",
        env=env,
        stages_file=stages_file,
    )
    assert error is None
    assert waves == [[0], [1, 2]]
    assert module._parallel_wave_output_conflict(
        [1, 2],
        entries_by_idx={1: stages[1], 2: stages[2]},
        stage_ids={1: "left", 2: "right"},
        env=env,
        stages_file=stages_file,
    ) is None
    assert module._parallel_agi_wave_eligible(
        stages,
        [1, 2],
        profile="balanced",
        env=env,
        stages_file=stages_file,
        selected_map={},
        engine_map={},
        default_runtime="",
    ) is True


def test_pipeline_run_controls_legacy_stage_formatting_and_clean_abort(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)

    stale_stages = [
        {"stage": idx, "line": idx + 10, "project": f"app-{idx}", "summary": f"summary-{idx}"}
        for idx in range(1, 7)
    ]

    formatted = module._format_legacy_stage_refs(stale_stages)

    assert "stage 1, line 11, app-1: summary-1" in formatted
    assert "1 more" in formatted

    assert module._abort_if_legacy_agi_run_stages(
        "page",
        tmp_path / "lab_stages.toml",
        [{"Q": "fresh", "C": "print('ok')"}],
        [0],
        None,
    ) is False

    assert module._abort_if_legacy_agi_run_stages(
        "page",
        tmp_path / "lab_stages.toml",
        [{"Q": "stale", "C": "await AGI.run(app_env, mode=0)", "R": "agi.run"}],
        [0],
        None,
    ) is True
    assert any(kind == "error" and "aborted before execution" in message for kind, message in fake_st.messages)


def test_pipeline_run_controls_run_all_stages_executes_runpy_and_agi_run(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('snippet')", encoding="utf-8")
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    stages_dir = tmp_path / "same" / "same"
    stages_dir.mkdir(parents=True)
    stages_file = stages_dir / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
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

    class FakeTracker:
        def __init__(self, run_id: str) -> None:
            self.run_id = run_id

        def __bool__(self) -> bool:
            return True

        def log_artifacts(self, **kwargs) -> None:
            artifact_calls.append(kwargs)

    @contextmanager
    def fake_start_tracker_run(_env, **kwargs):
        mlflow_calls.append(kwargs)
        yield FakeTracker(f"run-{len(mlflow_calls)}")

    monkeypatch.setattr(module._pipeline_runtime, "mlflow_tracking_uri", lambda _env: "sqlite:///mlflow.db")
    monkeypatch.setattr(module._pipeline_runtime, "start_tracker_run", fake_start_tracker_run)
    monkeypatch.setattr(
        module._pipeline_runtime,
        "build_mlflow_process_env",
        lambda _env, *, run_id=None: {"MLFLOW_RUN_ID": run_id or ""},
    )
    monkeypatch.setattr(module._pipeline_runtime, "wrap_code_with_mlflow_resume", lambda code: f"# wrapped\n{code}")
    monkeypatch.setattr(module._pipeline_runtime, "python_for_stage", lambda *_args, **_kwargs: "pythonX")
    monkeypatch.setattr(
        module._pipeline_runtime,
        "label_for_stage_runtime",
        lambda runtime, *, engine, code: f"{engine}:{Path(runtime).name if runtime else 'default'}",
    )
    monkeypatch.setattr(module._pipeline_runtime, "is_valid_runtime_root", lambda value: str(value) == str(runtime_root))
    monkeypatch.setattr(module._pipeline_stages, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_stages, "is_runnable_stage", lambda entry: bool(entry.get("C")))
    monkeypatch.setattr(module._pipeline_stages, "stage_summary", lambda _entry, width=80: f"summary:{width}")
    monkeypatch.setattr(module, "run_lab", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(module, "save_csv", lambda _data, target: saved_exports.append(str(target)) or True)
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: {"path": "lock", "token": "t"})
    monkeypatch.setattr(module, "_refresh_pipeline_run_lock", lambda handle: refreshes.append(handle))
    monkeypatch.setattr(module, "_release_pipeline_run_lock", lambda handle, *_args, **_kwargs: releases.append(handle))

    def fake_stream_run_command(env, index_page, cmd, cwd, **kwargs):
        stream_calls.append({"cmd": cmd, "cwd": cwd, "extra_env": kwargs.get("extra_env")})
        return "No such file or directory: missing.csv"

    stages = [
        {"D": "first", "Q": "q1", "M": "m1", "C": "print(1)"},
        {"D": "second", "Q": "q2", "M": "m2", "C": "print(2)", "E": str(runtime_root), "R": "runpy"},
        {"D": "skip", "Q": "q3", "M": "m3", "C": ""},
    ]
    env = SimpleNamespace(app="demo", active_app=str(runtime_root), copilot_file=tmp_path / "copilot.py")

    module.run_all_stages(
        tmp_path / "lab",
        "page",
        stages_file,
        tmp_path / "module.py",
        env,
        load_all_stages_fn=lambda *_args: stages,
        stream_run_command_fn=fake_stream_run_command,
    )

    assert any(kind == "success" and "Executed 2 stages." in message for kind, message in fake_st.messages)
    assert any("Run workflow completed: 2 stage(s) executed." in line for line in fake_st.session_state["page__run_logs"])
    assert any("No such file or directory" in line for line in fake_st.session_state["page__run_logs"])
    assert any("AGI_CLUSTER_SHARE" in line for line in fake_st.session_state["page__run_logs"])
    assert stream_calls[0]["cmd"][0] == "pythonX"
    assert stream_calls[0]["cwd"] == stages_dir.parent.resolve()
    assert stream_calls[0]["extra_env"]["MLFLOW_RUN_ID"] == "run-3"
    assert saved_exports == [str(export_file), str(export_file)]
    assert fake_st.session_state["df_file_in"] == str(export_file)
    assert fake_st.session_state["stage_checked"] is True
    assert fake_st.session_state["page"][0] == 99
    assert fake_st.session_state["lab_selected_venv"] == ""
    assert fake_st.session_state["lab_selected_engine"] == "old-engine"
    assert fake_st.session_state["page__force_blank_q"] is True
    assert fake_st.session_state["page__q_rev"] == 1
    assert fake_st.session_state["page__venv_map"][1] == str(runtime_root)
    assert refreshes and releases == [{"path": "lock", "token": "t"}]
    assert artifact_calls
    assert mlflow_calls[1]["nested"] is True


def test_pipeline_run_controls_run_all_stages_handles_early_exits(tmp_path, monkeypatch):
    module = _import_pipeline_run_controls()
    fake_st = _FakeStreamlit({"page": [0, "", "", "", "", "", 0]})
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module._pipeline_stages, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_stages, "is_runnable_stage", lambda entry: bool(entry.get("C")))
    env = SimpleNamespace(app="demo", active_app="", copilot_file=tmp_path / "copilot.py")

    module.run_all_stages(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_stages.toml",
        tmp_path / "module.py",
        env,
        load_all_stages_fn=lambda *_args: [],
        stream_run_command_fn=lambda *_args, **_kwargs: "",
    )
    assert any(kind == "info" and "No stages available" in message for kind, message in fake_st.messages)

    module.run_all_stages(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_stages.toml",
        tmp_path / "module.py",
        env,
        load_all_stages_fn=lambda *_args: [{"C": "print(1)"}],
        stream_run_command_fn=lambda *_args, **_kwargs: "",
    )
    assert any(kind == "error" and "Snippet file is not configured" in message for kind, message in fake_st.messages)

    fake_st.session_state["snippet_file"] = str(tmp_path / "snippet.py")
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: None)
    module.run_all_stages(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_stages.toml",
        tmp_path / "module.py",
        env,
        load_all_stages_fn=lambda *_args: [{"C": "print(1)"}],
        stream_run_command_fn=lambda *_args, **_kwargs: "",
    )
    assert fake_st.session_state["page__run_logs"].count("Run pipeline invoked.") == 3


def test_pipeline_run_controls_run_all_stages_reports_no_runnable_code(tmp_path, monkeypatch):
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
    monkeypatch.setattr(module._pipeline_stages, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_stages, "is_runnable_stage", lambda entry: bool(entry.get("C")))
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: {"path": "lock", "token": "t"})
    monkeypatch.setattr(module, "_refresh_pipeline_run_lock", lambda _handle: None)
    monkeypatch.setattr(module, "_release_pipeline_run_lock", lambda handle, *_args, **_kwargs: releases.append(handle))

    env = SimpleNamespace(app="demo", active_app="", copilot_file=tmp_path / "copilot.py")
    module.run_all_stages(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_stages.toml",
        tmp_path / "module.py",
        env,
        load_all_stages_fn=lambda *_args: [{"D": "skip", "Q": "no code", "M": "model", "C": ""}],
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
        raise AssertionError("stale snippets must abort before acquiring workflow lock")

    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", fail_if_lock_acquired)

    stale_code = (
        "from agi_cluster.agi_distributor import AGI\n"
        'APP = "flight_trajectory_project"\n'
        "async def main(app_env):\n"
        "    res = await AGI.run(app_env, mode=4, data_in='in', data_out='out')\n"
        "    return res\n"
    )
    env = SimpleNamespace(app="demo", active_app="", copilot_file=tmp_path / "copilot.py")

    module.run_all_stages(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_stages.toml",
        tmp_path / "module.py",
        env,
        load_all_stages_fn=lambda *_args: [{"Q": "Generate flight trajectories", "C": stale_code, "R": "agi.run"}],
        stream_run_command_fn=lambda *_args, **_kwargs: "should not execute",
    )

    assert any(kind == "error" and "aborted before execution" in message for kind, message in fake_st.messages)
    assert any("RunRequest" in line and "stage 1" in line for line in fake_st.session_state["page__run_logs"])
    assert not any("Running stage 1" in line for line in fake_st.session_state["page__run_logs"])


def test_pipeline_run_controls_normalizes_legacy_step_request_snippet() -> None:
    module = _import_pipeline_run_controls()
    stale_code = (
        "from agi_cluster.agi_distributor import AGI, RunRequest, StepRequest\n"
        "steps = [StepRequest(name='demo', args={})]\n"
        "request = RunRequest(mode=4, steps=steps)\n"
    )

    normalized, changed = module._normalize_legacy_agi_run_request_code(stale_code)

    assert changed is True
    assert "StepRequest" not in normalized
    assert "StageRequest" in normalized
    assert "stages = [StageRequest" in normalized
    assert "RunRequest(mode=4, stages=stages)" in normalized

    unchanged, changed = module._normalize_legacy_agi_run_request_code("steps = ['plain runpy loop']\n")
    assert changed is False
    assert unchanged == "steps = ['plain runpy loop']\n"


def test_pipeline_run_controls_run_all_stages_without_mlflow_tracks_runpy_no_output(tmp_path, monkeypatch):
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
        "label_for_stage_runtime",
        lambda runtime, *, engine, code: f"{engine}:{runtime or 'default'}",
    )
    monkeypatch.setattr(module._pipeline_runtime, "is_valid_runtime_root", lambda _value: False)
    monkeypatch.setattr(module._pipeline_stages, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_stages, "is_runnable_stage", lambda entry: bool(entry.get("C")))
    monkeypatch.setattr(module._pipeline_stages, "stage_summary", lambda entry, width=80: entry.get("Q", ""))
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
    module.run_all_stages(
        tmp_path / "lab",
        "page",
        tmp_path / "stages" / "lab_stages.toml",
        tmp_path / "module.py",
        env,
        load_all_stages_fn=lambda *_args: [{"D": "desc", "Q": "question", "M": "model", "C": "print(1)"}],
        stream_run_command_fn=lambda *_args, **_kwargs: "should not run",
    )

    assert len(run_lab_calls) == 1
    assert run_lab_calls[0]["payload"] == ["desc", "question", "print(1)"]
    assert run_lab_calls[0]["snippet"] == str(snippet_file)
    assert run_lab_calls[0]["copilot"] == env.copilot_file
    env_overrides = run_lab_calls[0]["kwargs"]["env_overrides"]
    assert env_overrides["AGILAB_PIPELINE_PROFILE"] == "balanced"
    assert env_overrides["AGILAB_PIPELINE_STAGE_INDEX"] == "1"
    assert env_overrides["AGILAB_PIPELINE_RUN_ID"]
    assert env_overrides["AGILAB_PIPELINE_MANIFEST"].endswith(".json")
    assert any(kind == "success" and "Executed 1 stage." in message for kind, message in fake_st.messages)
    assert any("runpy executed (no captured stdout)" in line for line in fake_st.session_state["page__run_logs"])
    assert fake_st.session_state["page"][0] == 7
    assert fake_st.session_state["lab_selected_engine"] == "old-engine"
    assert releases == [{"path": "lock", "token": "t"}]


def test_pipeline_run_controls_missing_mlflow_cli_still_runs_without_tracker(
    tmp_path, monkeypatch
):
    module = _import_pipeline_run_controls()
    snippet_file = tmp_path / "snippet.py"
    snippet_file.write_text("print('snippet')", encoding="utf-8")
    fake_st = _FakeStreamlit(
        {
            "page": [0, "", "", "", "", "", 0],
            "snippet_file": str(snippet_file),
            "lab_selected_venv": "",
            "lab_selected_engine": "",
        }
    )
    monkeypatch.setattr(module, "st", fake_st)
    releases: list[dict] = []
    run_lab_calls: list[dict] = []

    class MissingMlflowCliError(RuntimeError):
        pass

    @contextmanager
    def no_mlflow_tracker(*_args, **_kwargs):
        yield None

    def fail_build_mlflow_process_env(*_args, **_kwargs):
        raise AssertionError("MLflow env should not be built without a tracker")

    monkeypatch.setattr(
        module._pipeline_runtime,
        "mlflow_tracking_uri",
        lambda _env: (_ for _ in ()).throw(
            MissingMlflowCliError("Install `agilab[mlflow]`")
        ),
    )
    monkeypatch.setattr(module._pipeline_runtime, "start_tracker_run", no_mlflow_tracker)
    monkeypatch.setattr(
        module._pipeline_runtime,
        "build_mlflow_process_env",
        fail_build_mlflow_process_env,
    )
    monkeypatch.setattr(
        module._pipeline_runtime,
        "label_for_stage_runtime",
        lambda runtime, *, engine, code: f"{engine}:{runtime or 'default'}",
    )
    monkeypatch.setattr(module._pipeline_runtime, "is_valid_runtime_root", lambda _value: False)
    monkeypatch.setattr(module._pipeline_stages, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_stages, "is_runnable_stage", lambda entry: bool(entry.get("C")))
    monkeypatch.setattr(module._pipeline_stages, "stage_summary", lambda entry, width=80: entry.get("Q", ""))
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
    module.run_all_stages(
        tmp_path / "lab",
        "page",
        tmp_path / "lab_stages.toml",
        tmp_path / "module.py",
        env,
        load_all_stages_fn=lambda *_args: [{"D": "desc", "Q": "question", "M": "model", "C": "print(1)"}],
        stream_run_command_fn=lambda *_args, **_kwargs: "should not run",
    )

    env_overrides = run_lab_calls[0]["kwargs"]["env_overrides"]
    assert env_overrides["AGILAB_PIPELINE_PROFILE"] == "balanced"
    assert env_overrides["AGILAB_PIPELINE_STAGE_INDEX"] == "1"
    assert env_overrides["AGILAB_PIPELINE_RUN_ID"]
    assert env_overrides["AGILAB_PIPELINE_MANIFEST"].endswith(".json")
    assert any(kind == "success" and "Executed 1 stage." in message for kind, message in fake_st.messages)
    assert releases == [{"path": "lock", "token": "t"}]


def test_pipeline_run_controls_run_all_stages_uses_active_app_for_agi_engine(tmp_path, monkeypatch):
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
        "python_for_stage",
        lambda runtime, *, engine, code: f"python-for-{Path(runtime).name}",
    )
    monkeypatch.setattr(
        module._pipeline_runtime,
        "label_for_stage_runtime",
        lambda runtime, *, engine, code: f"{engine}:{Path(runtime).name if runtime else 'default'}",
    )
    monkeypatch.setattr(module._pipeline_runtime, "is_valid_runtime_root", lambda value: str(value) == str(runtime_root))
    monkeypatch.setattr(module._pipeline_stages, "normalize_runtime_path", lambda value: str(value or ""))
    monkeypatch.setattr(module._pipeline_stages, "is_runnable_stage", lambda entry: bool(entry.get("C")))
    monkeypatch.setattr(module._pipeline_stages, "stage_summary", lambda entry, width=80: entry.get("Q", ""))
    monkeypatch.setattr(module, "_acquire_pipeline_run_lock", lambda *_args, **_kwargs: {"path": "lock", "token": "t"})
    monkeypatch.setattr(module, "_refresh_pipeline_run_lock", lambda _handle: None)
    monkeypatch.setattr(module, "_release_pipeline_run_lock", lambda handle, *_args, **_kwargs: releases.append(handle))

    def fake_stream_run_command(env, index_page, cmd, cwd, **kwargs):
        stream_calls.append({"cmd": cmd, "cwd": cwd, "extra_env": kwargs.get("extra_env")})
        return "completed"

    env = SimpleNamespace(app="demo", active_app=str(runtime_root), copilot_file=tmp_path / "copilot.py")
    module.run_all_stages(
        tmp_path / "lab",
        "page",
        tmp_path / "stages" / "lab_stages.toml",
        tmp_path / "module.py",
        env,
        load_all_stages_fn=lambda *_args: [{"D": "desc", "Q": "question", "M": "model", "C": "print(1)", "R": "agi.run"}],
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


def test_utc_timestamp_is_timezone_aware_utc_with_legacy_z_format(monkeypatch):
    import re
    from datetime import datetime, timezone

    module = _import_pipeline_run_controls()

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            # Return a fixed aware UTC instant regardless of local tz.
            aware = datetime(2026, 7, 12, 8, 30, 15, 123456, tzinfo=timezone.utc)
            return aware if tz is None else aware.astimezone(tz)

    monkeypatch.setattr(module, "datetime", _FixedDateTime)

    stamp = module._utc_timestamp()

    # Historic naive "...Z" second-precision format must be preserved so existing
    # manifests/captions stay stable after dropping deprecated datetime.utcnow().
    assert stamp == "2026-07-12T08:30:15Z"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp)
    # No timezone offset leaked into the string.
    assert "+00:00" not in stamp
