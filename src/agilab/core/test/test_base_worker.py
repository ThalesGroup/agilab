from __future__ import annotations

import builtins
import logging
import os
import pickle
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace
import types
from unittest.mock import patch

import pytest

from agi_node.agi_dispatcher import BaseWorker
from agi_node.agi_dispatcher import base_worker as base_worker_mod

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)

class DummyWorker(BaseWorker):
    def __init__(self):
        super().__init__()
        worker_id = 0
        BaseWorker._worker_id = worker_id
        BaseWorker._insts = {worker_id: self}

    def works(self, *_args, **_kwargs):
        pass


def teardown_function(_fn):
    BaseWorker._worker_id = None
    BaseWorker._insts = {}
    BaseWorker._env = None
    BaseWorker.env = None


def test_baseworker_do_works_executes_tasks():
    dummy = DummyWorker()
    with patch.object(dummy, "works", return_value=None) as mocked:
        BaseWorker._do_works({}, {})
    mocked.assert_called_once()


def test_new_sets_worker_ids_on_instance(monkeypatch):
    class SpawnedWorker(BaseWorker):
        pass

    captured = {}

    monkeypatch.setattr(BaseWorker, "_ensure_managed_pc_share_dir", staticmethod(lambda env: None))
    monkeypatch.setattr(BaseWorker, "_load_worker", staticmethod(lambda _mode: SpawnedWorker))

    def _fake_start(worker_inst):
        captured["worker_id"] = worker_inst.worker_id
        captured["_worker_id"] = worker_inst._worker_id

    monkeypatch.setattr(BaseWorker, "start", staticmethod(_fake_start))

    env = SimpleNamespace()
    BaseWorker._new(env=env, mode=4, worker_id=3, worker="tcp://192.168.20.130:1234")

    assert captured == {"worker_id": 3, "_worker_id": 3}
    assert BaseWorker._insts[3].worker_id == 3
    assert BaseWorker._insts[3]._worker_id == 3


def test_prepare_output_dir_creates_directory(tmp_path):
    worker = DummyWorker()
    target = worker.prepare_output_dir(tmp_path, subdir="payload", attribute="custom_attr", clean=True)

    assert target.exists()
    assert target.name == "payload"
    assert worker.custom_attr == target


def test_setup_args_requires_args():
    worker = DummyWorker()
    with pytest.raises(ValueError):
        worker.setup_args(None)


def test_setup_args_applies_defaults_and_creates_output(tmp_path):
    class ConfigWorker(BaseWorker):
        args_ensure_defaults = staticmethod(lambda args, env=None: SimpleNamespace(**{**vars(args), "extra": "value"}))
        managed_pc_path_fields = ("data_path",)

    worker = ConfigWorker()
    args = SimpleNamespace(data_path=tmp_path / "data")

    processed = worker.setup_args(
        args,
        output_field="data_path",
        output_subdir="frames",
        output_attr="output_dir",
    )

    assert processed.extra == "value"
    assert worker.output_dir.exists()
    assert worker.output_dir.name == "frames"


def test_remap_managed_pc_path_when_managed():
    home = Path.home()
    sample = home / "dataset" / "file.csv"
    env = SimpleNamespace(
        _is_managed_pc=True,
        agi_share_path=Path("clustershare"),
        agi_share_path_abs=Path.home() / "clustershare",
    )

    remapped = BaseWorker._remap_managed_pc_path(sample, env=env)

    expected_root = home / BaseWorker.managed_pc_home_suffix
    assert str(remapped).startswith(str(expected_root))


def test_apply_managed_pc_path_overrides():
    class OverrideWorker(BaseWorker):
        managed_pc_path_fields = ("payload",)

    env = SimpleNamespace(
        _is_managed_pc=True,
        agi_share_path=Path("clustershare"),
        agi_share_path_abs=Path.home() / "clustershare",
    )
    path = Path.home() / "payload"
    args = SimpleNamespace(payload=path)

    result = OverrideWorker._apply_managed_pc_path_overrides(args, env=env)

    assert isinstance(result.payload, Path)
    assert str(result.payload).startswith(str(Path.home() / OverrideWorker.managed_pc_home_suffix))


def test_resolve_input_folder_uses_dataset_fallback(tmp_path):
    dataset_root = tmp_path / "link_sim" / "dataset"
    flights_dir = dataset_root / "flights"
    flights_dir.mkdir(parents=True)
    (flights_dir / "plane0.csv").write_text("plane_id,time_s\n0,0\n")
    (flights_dir / "plane1.csv").write_text("plane_id,time_s\n1,1\n")

    env = SimpleNamespace(
        share_root_path=lambda: tmp_path,
        agi_share_path_abs=tmp_path,
        agi_share_path=tmp_path,
        home_abs=Path.home(),
        AGILAB_SHARE_HINT=None,
        AGILAB_SHARE_REL=None,
    )

    resolved = BaseWorker.resolve_input_folder(
        env,
        dataset_root,
        "flight_trajectory/pipeline",
        descriptor="flight_trajectory",
        fallback_subdirs=("flights",),
        dataset_namespace="link_sim",
        min_files=2,
        required_label="plane trajectory files",
    )

    assert resolved == flights_dir


def test_resolve_input_folder_uses_share_root_namespace_fallback(tmp_path):
    share_root = tmp_path / "share"
    dataset_root = tmp_path / "runtime" / "dataset"
    flights_dir = share_root / "link_sim" / "dataset" / "flights"
    flights_dir.mkdir(parents=True)
    (flights_dir / "plane0.csv").write_text("plane_id,time_s\n0,0\n")
    (flights_dir / "plane1.csv").write_text("plane_id,time_s\n1,1\n")

    env = SimpleNamespace(
        share_root_path=lambda: share_root,
        agi_share_path_abs=share_root,
        agi_share_path=share_root,
        home_abs=Path.home(),
        AGILAB_SHARE_HINT=None,
        AGILAB_SHARE_REL=None,
    )

    resolved = BaseWorker.resolve_input_folder(
        env,
        dataset_root,
        "flight_trajectory/pipeline",
        descriptor="flight_trajectory",
        fallback_subdirs=("flights",),
        dataset_namespace="link_sim",
        min_files=2,
        required_label="plane trajectory files",
    )

    assert resolved == flights_dir


def test_baseworker_path_helper_utilities_cover_share_and_home_cases(tmp_path):
    env = SimpleNamespace(
        share_root_path=lambda: tmp_path / "share",
        agi_share_path_abs=tmp_path / "share",
        agi_share_path=Path("clustershare"),
        home_abs=Path.home(),
        AGILAB_SHARE_HINT=Path("clustershare/link_sim"),
        AGILAB_SHARE_REL="clustershare/link_sim",
        _is_managed_pc=False,
    )
    (tmp_path / "share").mkdir()

    resolved = BaseWorker._resolve_data_dir(env, Path("flight_trajectory/pipeline"))
    assert resolved == (tmp_path / "share" / "flight_trajectory" / "pipeline").resolve()

    home_path = Path("/Users/demo/data/file.csv")
    assert BaseWorker._relative_to_user_home(home_path) == Path("data/file.csv")
    assert BaseWorker._relative_to_user_home(Path("/tmp/data/file.csv")) is None
    assert BaseWorker._remap_user_home(home_path, username="other") == Path("/Users/other/data/file.csv")
    assert BaseWorker._remap_user_home(Path("/tmp/data/file.csv"), username="other") is None

    assert BaseWorker._strip_share_prefix(Path("clustershare/demo/file.csv"), {"clustershare"}) == Path("demo/file.csv")
    assert BaseWorker._strip_share_prefix(Path("demo/file.csv"), {"clustershare"}) == Path("demo/file.csv")

    aliases = BaseWorker._collect_share_aliases(env, tmp_path / "share")
    assert {"share", "clustershare", "link_sim"} <= aliases


def test_baseworker_candidate_roots_and_expand_helpers(tmp_path, monkeypatch):
    share_root = tmp_path / "share"
    dataset_root = tmp_path / "runtime" / "dataset"
    env = SimpleNamespace(
        share_root_path=lambda: share_root,
        agi_share_path_abs=share_root,
        agi_share_path=Path("clustershare"),
        home_abs=Path.home(),
        AGILAB_SHARE_HINT=Path("clustershare/link_sim"),
        AGILAB_SHARE_REL="clustershare/link_sim",
        _is_managed_pc=False,
    )

    candidates = BaseWorker._candidate_named_dataset_roots(env, dataset_root, namespace="link_sim")
    assert share_root / "link_sim" in candidates
    assert share_root / "link_sim" / "dataset" in candidates

    monkeypatch.setattr(base_worker_mod.Path, "home", staticmethod(lambda: tmp_path))
    assert BaseWorker.expand("demo/file.csv", base_directory=tmp_path / "base").endswith("base/demo/file.csv")
    assert BaseWorker.expand_and_join("~/data", "nested/file.csv").endswith("data/nested/file.csv")
    assert BaseWorker.normalize_dataset_path("relative/data").endswith("relative/data")


def test_baseworker_iter_input_files_and_can_create_path(tmp_path):
    folder = tmp_path / "dataset"
    folder.mkdir()
    (folder / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (folder / "b.parquet").write_text("pq", encoding="utf-8")
    (folder / "._hidden.csv").write_text("hidden", encoding="utf-8")

    files = BaseWorker._iter_input_files(folder)
    assert [path.name for path in files] == ["a.csv", "b.parquet"]

    writable_target = tmp_path / "output" / "data.csv"
    assert BaseWorker._can_create_path(writable_target) is True


def test_baseworker_expand_chunk_and_missing_input_folder(tmp_path):
    reconstructed, chunk_len, total = BaseWorker._expand_chunk(
        {
            "__agi_worker_chunk__": True,
            "chunk": {"step": 1},
            "total_workers": 3,
            "worker_idx": 1,
        },
        worker_id=1,
    )
    assert reconstructed == [{}, {"step": 1}, {}]
    assert chunk_len == 1
    assert total == 3

    env = SimpleNamespace(
        share_root_path=lambda: tmp_path / "share",
        agi_share_path_abs=tmp_path / "share",
        agi_share_path=tmp_path / "share",
        home_abs=Path.home(),
        AGILAB_SHARE_HINT=None,
        AGILAB_SHARE_REL=None,
    )
    with pytest.raises(FileNotFoundError, match="Need at least 2 csv files"):
        BaseWorker.resolve_input_folder(
            env,
            tmp_path / "dataset",
            "missing",
            descriptor="demo",
            fallback_subdirs=("flights",),
            min_files=2,
            patterns=("*.csv",),
            required_label="csv files",
        )


def test_baseworker_args_helpers_and_payload_round_trip(tmp_path):
    events: dict[str, object] = {}

    class Payload:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def model_dump(self, mode=None):
            events["dump_mode"] = mode
            return dict(self.__dict__)

    class ConfigWorker(BaseWorker):
        default_settings_path = "worker_settings.toml"
        default_settings_section = "worker"
        args_loader = staticmethod(
            lambda path, section=None: Payload(settings_path=str(path), section=section, value=1)
        )
        args_merger = staticmethod(
            lambda base, overrides=None: Payload(**{**base.model_dump(), **(overrides or {})})
        )
        args_ensure_defaults = staticmethod(
            lambda args, env=None: Payload(**{**args.model_dump(), "env_name": getattr(env, "name", None)})
        )
        args_dumper = staticmethod(
            lambda args, path, section=None, create_missing=True: events.setdefault("dump_calls", []).append(
                (args.model_dump(), Path(path), section, create_missing)
            )
        )

        def __init__(self, env=None, args=None):
            self.env = env
            self.args = args

        def _extend_payload(self, payload):
            payload["extended"] = True
            return payload

    env = SimpleNamespace(name="demo-env", _is_managed_pc=False, agi_share_path=None)

    worker = ConfigWorker.from_toml(env, value=3, extra="yes")
    assert worker.args.value == 3
    assert worker.args.extra == "yes"
    assert worker.args.env_name == "demo-env"

    settings_path = tmp_path / "settings.toml"
    worker.to_toml(settings_path, section="override", create_missing=False)
    dump_calls = events["dump_calls"]
    assert dump_calls == [
        (
            {
                "settings_path": "worker_settings.toml",
                "section": "worker",
                "value": 3,
                "extra": "yes",
                "env_name": "demo-env",
            },
            settings_path,
            "override",
            False,
        )
    ]

    assert worker.as_dict() == {
        "settings_path": "worker_settings.toml",
        "section": "worker",
        "value": 3,
        "extra": "yes",
        "env_name": "demo-env",
        "extended": True,
    }
    assert events["dump_mode"] == "json"


def test_baseworker_stop_and_break_loop_idle_paths(monkeypatch):
    worker = DummyWorker()
    BaseWorker._worker_id = 7
    worker._worker_id = 7
    worker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._service_active = {7: True}

    calls: list[str] = []
    monkeypatch.setattr(BaseWorker, "break_loop", staticmethod(lambda: calls.append("break") or True))
    worker.stop()
    assert calls == ["break"]

    monkeypatch.undo()
    BaseWorker._worker_id = None
    assert BaseWorker.break_loop() is False
    BaseWorker._worker_id = 7
    BaseWorker._service_stop_events = {}
    assert BaseWorker.break_loop() is False


def test_baseworker_path_and_subprocess_helpers(monkeypatch, tmp_path):
    expanded = BaseWorker.expand("folder/demo.csv", base_directory=tmp_path)
    assert expanded == str((tmp_path / "folder" / "demo.csv").resolve())
    assert BaseWorker._join(str(tmp_path), "child.txt").endswith("/child.txt")

    monkeypatch.setattr(BaseWorker, "expand", staticmethod(lambda value: str(tmp_path / value)))
    assert BaseWorker.expand_and_join("base", "child.txt").endswith("/base/child.txt")

    def _logged():
        logging.getLogger().info("hello")
        return 9

    logs, result = BaseWorker._get_logs_and_result(_logged, verbosity=1)
    assert result == 9
    assert "hello" in logs

    ok = SimpleNamespace(returncode=0, stderr="", stdout="done")
    warning = SimpleNamespace(returncode=1, stderr="WARNING: notice", stdout="")
    error = SimpleNamespace(returncode=1, stderr="fatal boom", stdout="")
    responses = iter([ok, warning, error])
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: next(responses))

    assert BaseWorker._exec("echo ok", tmp_path, "worker") is ok
    assert BaseWorker._exec("echo warn", tmp_path, "worker") is warning
    with pytest.raises(RuntimeError, match="fatal boom"):
        BaseWorker._exec("echo fail", tmp_path, "worker")


def test_baseworker_module_loading_and_chunks(monkeypatch):
    fake_module = types.ModuleType("demo.module")
    fake_module.Target = "loaded"

    original_import = builtins.__import__

    def fake_import(name, fromlist=(), *args, **kwargs):
        if name in {"demo.module", "demo.demo", "demo_worker.demo_worker", "demo_worker_cy"}:
            return fake_module
        return original_import(name, fromlist, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert BaseWorker._load_module("demo.module", "Target") == "loaded"

    BaseWorker.env = SimpleNamespace(
        module="demo",
        target_class="Target",
        target_worker="demo_worker",
        target_worker_class="Target",
    )
    assert BaseWorker._load_manager() == "loaded"
    assert BaseWorker._load_worker(0) == "loaded"
    assert BaseWorker._load_worker(2) == "loaded"
    assert BaseWorker._is_cython_installed(BaseWorker.env) is True

    monkeypatch.setattr(
        builtins,
        "__import__",
        lambda name, fromlist=(), *args, **kwargs: (_ for _ in ()).throw(ModuleNotFoundError(name)),
    )
    assert BaseWorker._is_cython_installed(BaseWorker.env) is False
    with pytest.raises(ModuleNotFoundError, match="module missing.module is not installed"):
        BaseWorker._load_module("missing.module", "Target")

    reconstructed, chunk_len, total_workers = BaseWorker._expand_chunk(
        {"__agi_worker_chunk__": True, "chunk": ["a"], "total_workers": 3, "worker_idx": 1},
        1,
    )
    assert reconstructed == [[], ["a"], []]
    assert chunk_len == 1
    assert total_workers == 3


def test_baseworker_setup_data_directories_and_info(monkeypatch, tmp_path):
    worker = DummyWorker()
    share_root = tmp_path / "share"
    input_dir = share_root / "flight_trajectory" / "pipeline"
    input_dir.mkdir(parents=True)

    env = SimpleNamespace(
        AGI_LOCAL_SHARE=tmp_path / "localshare",
        home_abs=tmp_path / "home",
        target="demo",
        _is_managed_pc=False,
        share_root_path=lambda: share_root,
        agi_share_path_abs=share_root,
        agi_share_path=Path("clustershare"),
        AGILAB_SHARE_HINT=None,
        AGILAB_SHARE_REL=None,
    )
    worker.env = env

    result = worker.setup_data_directories(
        source_path=Path("flight_trajectory/pipeline"),
        target_subdir="output",
        reset_target=True,
    )
    assert result.input_path == input_dir.resolve()
    assert result.output_path == input_dir.parent / "output"
    assert worker.data_out.endswith("/output")

    BaseWorker._share_path = tmp_path
    BaseWorker._worker = "127.0.0.1:8787"
    monkeypatch.setattr(base_worker_mod.psutil, "virtual_memory", lambda: SimpleNamespace(total=8_000_000_000, available=4_000_000_000))
    monkeypatch.setattr(base_worker_mod.psutil, "cpu_count", lambda: 4)
    monkeypatch.setattr(base_worker_mod.psutil, "cpu_freq", lambda: SimpleNamespace(current=3200))
    time_values = iter([1.0, 2.0])
    monkeypatch.setattr(base_worker_mod.time, "time", lambda: next(time_values))
    monkeypatch.setattr(base_worker_mod.time, "sleep", lambda *_args, **_kwargs: None)

    info = BaseWorker._get_worker_info(0)
    assert info["cpu_count"] == [4]
    assert info["cpu_frequency"] == [3.2]
    assert info["ram_total"] == [8.0]
    assert info["ram_available"] == [4.0]


def test_baseworker_onerror_handles_permission_and_non_permission(tmp_path, monkeypatch):
    target = tmp_path / "locked.txt"
    target.write_text("x", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(base_worker_mod.os, "access", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(base_worker_mod.os, "chmod", lambda *_args, **_kwargs: calls.append("chmod"))
    BaseWorker._onerror(lambda _path: calls.append("func"), str(target), (PermissionError, PermissionError("denied"), None))
    assert calls == ["chmod", "func"]

    monkeypatch.setattr(base_worker_mod.os, "access", lambda *_args, **_kwargs: True)
    with pytest.raises(RuntimeError, match="boom"):
        BaseWorker._onerror(lambda _path: None, str(target), (RuntimeError, RuntimeError("boom"), None))


def test_service_loop_without_worker_override_stops_cleanly():
    worker = DummyWorker()
    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    time.sleep(0.1)

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "BaseWorker.loop did not stop after break_loop"

    payload = result.get("payload")
    assert isinstance(payload, dict)
    assert payload.get("status") == "stopped"


def test_service_loop_consumes_queued_tasks(tmp_path):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))
    calls: list[tuple[object, object]] = []

    def _works(plan, metadata):
        calls.append((plan, metadata))

    worker.works = _works

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    payload = {
        "task_id": "batch-1",
        "worker_idx": 0,
        "worker": "127.0.0.1:8787",
        "plan": {
            "__agi_worker_chunk__": True,
            "chunk": ["step-1"],
            "total_workers": 1,
            "worker_idx": 0,
        },
        "metadata": {
            "__agi_worker_chunk__": True,
            "chunk": [{"meta": 1}],
            "total_workers": 1,
            "worker_idx": 0,
        },
    }
    task_file = pending / "000001-batch-1-000-worker.task.pkl"
    with open(task_file, "wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    deadline = time.time() + 2.0
    done_file = queue_root / "done" / task_file.name
    while time.time() < deadline and not done_file.exists():
        time.sleep(0.05)

    assert done_file.exists(), "Service queue task was not moved to done"
    assert len(calls) == 1

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("processed") == 1
