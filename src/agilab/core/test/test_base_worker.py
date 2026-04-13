from __future__ import annotations

import builtins
import json
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


def test_baseworker_helper_edge_cases(monkeypatch, tmp_path):
    class MissingHelpersWorker(BaseWorker):
        pass

    with pytest.raises(AttributeError, match="args_loader"):
        MissingHelpersWorker.from_toml(SimpleNamespace())

    monkeypatch.setattr(
        base_worker_mod,
        "normalize_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert BaseWorker._normalized_path("~/demo") == Path("~/demo").expanduser()

    env = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(RuntimeError("no share")),
        agi_share_path_abs=None,
        agi_share_path=Path("clustershare"),
        home_abs=tmp_path,
        _is_managed_pc=False,
    )
    assert BaseWorker._share_root_path(env) == tmp_path / "clustershare"

    with pytest.raises(ValueError, match="data_path must be provided"):
        BaseWorker._resolve_data_dir(env, None)


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


def test_baseworker_managed_pc_override_skips_missing_fields_and_bad_values(monkeypatch):
    class OverrideWorker(BaseWorker):
        managed_pc_path_fields = ("missing", "payload")

    env = SimpleNamespace(
        _is_managed_pc=True,
        agi_share_path=Path.home() / "clustershare",
        agi_share_path_abs=Path.home() / "clustershare",
    )
    args = SimpleNamespace(payload=Path.home() / "payload")

    monkeypatch.setattr(
        OverrideWorker,
        "_remap_managed_pc_path",
        classmethod(lambda cls, value, env=None: (_ for _ in ()).throw(ValueError("bad path"))),
    )

    result = OverrideWorker._apply_managed_pc_path_overrides(args, env=env)

    assert result is args
    assert result.payload == Path.home() / "payload"
    assert not hasattr(result, "missing")


def test_baseworker_apply_managed_pc_paths_instance_wrapper():
    class OverrideWorker(BaseWorker):
        managed_pc_path_fields = ("payload",)

    env = SimpleNamespace(
        _is_managed_pc=True,
        agi_share_path=Path.home() / "clustershare",
        agi_share_path_abs=Path.home() / "clustershare",
    )
    worker = OverrideWorker()
    worker.env = env
    args = SimpleNamespace(payload=Path.home() / "payload")

    result = worker._apply_managed_pc_paths(args)

    assert result is args
    assert str(result.payload).startswith(str(Path.home() / OverrideWorker.managed_pc_home_suffix))


def test_baseworker_ensure_managed_pc_share_dir_branches(tmp_path):
    BaseWorker._ensure_managed_pc_share_dir(None)

    env_not_managed = SimpleNamespace(_is_managed_pc=False, agi_share_path=Path("clustershare"))
    BaseWorker._ensure_managed_pc_share_dir(env_not_managed)
    assert env_not_managed.agi_share_path == Path("clustershare")

    env_without_share = SimpleNamespace(_is_managed_pc=True, agi_share_path=None)
    BaseWorker._ensure_managed_pc_share_dir(env_without_share)
    assert env_without_share.agi_share_path is None

    home = Path.home()
    env_managed = SimpleNamespace(_is_managed_pc=True, agi_share_path=home / "clustershare")
    BaseWorker._ensure_managed_pc_share_dir(env_managed)
    assert str(env_managed.agi_share_path).startswith(str(home / BaseWorker.managed_pc_home_suffix))


def test_baseworker_share_root_path_none_absolute_and_home_fallback(tmp_path):
    assert BaseWorker._share_root_path(None) is None

    env_absolute = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(RuntimeError("no share")),
        agi_share_path_abs=tmp_path / "absolute-share",
        agi_share_path=Path("clustershare"),
        home_abs=tmp_path / "home",
    )
    assert BaseWorker._share_root_path(env_absolute) == tmp_path / "absolute-share"

    env_home = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(RuntimeError("no share")),
        agi_share_path_abs=None,
        agi_share_path=None,
        home_abs=tmp_path / "home",
    )
    assert BaseWorker._share_root_path(env_home) == (tmp_path / "home")


def test_baseworker_collect_share_aliases_and_data_dir_fallbacks(monkeypatch, tmp_path):
    class _BrokenPath:
        def __fspath__(self):
            raise RuntimeError("boom")

    env = SimpleNamespace(
        AGILAB_SHARE_HINT=Path("clustershare/link_sim"),
        AGILAB_SHARE_REL=_BrokenPath(),
        agi_share_path=_BrokenPath(),
        _is_managed_pc=False,
        share_root_path=lambda: tmp_path / "share",
        agi_share_path_abs=tmp_path / "share",
        home_abs=tmp_path / "home",
    )
    (tmp_path / "share").mkdir()

    aliases = BaseWorker._collect_share_aliases(env, tmp_path / "share")
    assert {"share", "clustershare", "data", "datashare", "link_sim"} <= aliases

    assert BaseWorker._has_min_input_files(tmp_path / "missing", min_files=1) is False
    folder = tmp_path / "dataset"
    folder.mkdir()
    (folder / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (folder / "b.csv").write_text("x\n2\n", encoding="utf-8")
    assert BaseWorker._has_min_input_files(folder, min_files=2, patterns=("*.csv",)) is True

    original_normalized = BaseWorker._normalized_path
    monkeypatch.setattr(
        BaseWorker,
        "_normalized_path",
        classmethod(lambda cls, value: (_ for _ in ()).throw(RuntimeError("normalize failed"))),
    )
    fallback = BaseWorker._resolve_data_dir(env, Path("dataset") / "inputs")
    assert fallback == (tmp_path / "share" / "dataset" / "inputs").expanduser().resolve(strict=False)

    monkeypatch.setattr(BaseWorker, "_normalized_path", original_normalized)
    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == (tmp_path / "share" / "dataset" / "normpath-target"):
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)
    resolved = BaseWorker._resolve_data_dir(env, Path("dataset") / "normpath-target")
    assert resolved == Path(os.path.normpath(str(tmp_path / "share" / "dataset" / "normpath-target")))


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


def test_resolve_input_folder_uses_nested_fallback_and_warns(tmp_path, monkeypatch):
    dataset_root = tmp_path / "dataset"
    nested = dataset_root / "pipeline" / "csv"
    nested.mkdir(parents=True)
    (nested / "a.csv").write_text("plane_id,time_s\n0,0\n", encoding="utf-8")
    (nested / "b.csv").write_text("plane_id,time_s\n1,1\n", encoding="utf-8")

    warnings = []
    monkeypatch.setattr(base_worker_mod.logger, "warning", lambda msg, *args: warnings.append(msg % args))

    resolved = BaseWorker.resolve_input_folder(
        None,
        dataset_root,
        "pipeline",
        descriptor="demo generator",
        fallback_subdirs=("csv",),
        min_files=2,
        patterns=("*.csv",),
    )

    assert resolved == nested.resolve()
    assert warnings
    assert "using nested fallback" in warnings[0]


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


def test_baseworker_candidate_roots_resolve_fallback(monkeypatch, tmp_path):
    share_root = tmp_path / "share"
    dataset_root = tmp_path / "runtime" / "dataset"
    env = SimpleNamespace(
        share_root_path=lambda: share_root,
        agi_share_path_abs=share_root,
        agi_share_path=Path("clustershare"),
        home_abs=Path.home(),
        AGILAB_SHARE_HINT=None,
        AGILAB_SHARE_REL=None,
        _is_managed_pc=False,
    )

    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == share_root / "link_sim":
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)

    candidates = BaseWorker._candidate_named_dataset_roots(env, dataset_root, namespace="link_sim")

    assert share_root / "link_sim" in candidates


def test_baseworker_expand_and_join_windows_mount_failure_is_swallowed(monkeypatch):
    calls = []
    posix_path_cls = type(Path("/tmp"))
    monkeypatch.setattr(base_worker_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(base_worker_mod, "Path", posix_path_cls)
    monkeypatch.setattr(BaseWorker, "_is_managed_pc", False, raising=False)

    def _fake_run(cmd, shell=True, check=True):
        calls.append((cmd, shell, check))
        raise OSError("mount failed")

    monkeypatch.setattr(base_worker_mod.subprocess, "run", _fake_run)

    result = BaseWorker.expand_and_join("/Users/demo/data", "child.txt")

    assert calls
    assert calls[0][0].startswith('net use Z: ')
    assert result.replace("\\", "/").endswith("/Users/demo/data/child.txt")


def test_baseworker_normalize_dataset_path_windows_unc(monkeypatch):
    posix_path_cls = type(Path("/tmp"))
    monkeypatch.setattr(base_worker_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(base_worker_mod, "Path", posix_path_cls)
    monkeypatch.setattr(BaseWorker, "_is_managed_pc", True, raising=False)

    result = BaseWorker.normalize_dataset_path(r"\\server\share\dataset")

    assert "server" in result
    assert result.endswith("dataset")


def test_baseworker_normalize_dataset_path_windows_relative_resolve_and_mount_fallback(monkeypatch):
    posix_path_cls = type(Path("/tmp"))
    monkeypatch.setattr(base_worker_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(base_worker_mod, "Path", posix_path_cls)
    monkeypatch.setattr(BaseWorker, "_is_managed_pc", False, raising=False)

    candidate = (posix_path_cls.home() / "relative" / "data").expanduser()
    original_resolve = posix_path_cls.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == candidate:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(posix_path_cls, "resolve", _patched_resolve, raising=False)

    calls = []

    def _fake_run(cmd, shell=True, check=True):
        calls.append((cmd, shell, check))
        raise OSError("net use failed")

    monkeypatch.setattr(base_worker_mod.subprocess, "run", _fake_run)

    result = BaseWorker.normalize_dataset_path("relative/data")

    assert calls
    assert calls[0][0].startswith('net use Z: ')
    assert result.endswith("relative/data")


def test_baseworker_normalize_dataset_path_windows_without_users_prefix(monkeypatch):
    calls = []
    posix_path_cls = type(Path("/tmp"))
    monkeypatch.setattr(base_worker_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(base_worker_mod, "Path", posix_path_cls)
    monkeypatch.setattr(BaseWorker, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(
        base_worker_mod.subprocess,
        "run",
        lambda cmd, shell=True, check=True: calls.append((cmd, shell, check)),
    )

    result = BaseWorker.normalize_dataset_path("/tmp/demo/data")

    assert calls
    assert calls[0][0].startswith('net use Z: ')
    assert result.endswith("/tmp/demo/data")


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


def test_baseworker_can_create_path_returns_false_on_permission_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        Path,
        "touch",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )
    assert BaseWorker._can_create_path(tmp_path / "output" / "data.csv") is False


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


def test_baseworker_prepare_output_dir_and_setup_args_parent_branch(monkeypatch, tmp_path):
    worker = DummyWorker()
    target = tmp_path / "root" / "payload"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(
        base_worker_mod.shutil,
        "rmtree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )
    original_mkdir = Path.mkdir

    def _patched_mkdir(self, *args, **kwargs):
        if self == target:
            raise OSError("mkdir failed")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _patched_mkdir)
    prepared = worker.prepare_output_dir(tmp_path / "root", subdir="payload", attribute="payload_dir", clean=True)
    assert prepared == target
    assert worker.payload_dir == target

    class ParentWorker(BaseWorker):
        args_ensure_defaults = staticmethod(lambda args, env=None: args)

    parent_worker = ParentWorker()
    args = SimpleNamespace(data_path=tmp_path / "dataset" / "inputs" / "file.csv")
    processed = parent_worker.setup_args(
        args,
        output_field="data_path",
        output_subdir="frames",
        output_attr="output_dir",
        output_parents_up=1,
    )

    assert processed is args
    assert parent_worker.output_dir == tmp_path / "dataset" / "inputs" / "frames"


def test_baseworker_as_dict_without_args_uses_extend_payload():
    class ExtendWorker(BaseWorker):
        def _extend_payload(self, payload):
            payload["extended"] = True
            return payload

    worker = ExtendWorker()
    assert worker.as_dict() == {"extended": True}


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


def test_baseworker_start_error_and_inactive_stop(monkeypatch):
    class PassiveWorker(BaseWorker):
        pass

    BaseWorker.start(PassiveWorker())

    class BrokenWorker(BaseWorker):
        def start(self):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        BaseWorker.start(BrokenWorker())

    worker = DummyWorker()
    worker._worker_id = 3
    worker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._service_active = {3: False}
    calls: list[str] = []
    monkeypatch.setattr(BaseWorker, "break_loop", staticmethod(lambda: calls.append("break") or True))
    worker.stop()
    assert calls == []


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
    debug_logs, debug_result = BaseWorker._get_logs_and_result(_logged, verbosity=2)
    warning_logs, warning_result = BaseWorker._get_logs_and_result(_logged, verbosity=0)
    assert result == 9
    assert debug_result == 9
    assert warning_result == 9
    assert "hello" in logs
    assert debug_logs
    assert warning_logs == ""

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


def test_baseworker_setup_data_directories_requires_source_path():
    worker = DummyWorker()
    worker.env = None

    with pytest.raises(ValueError, match="requires a source_path value"):
        worker.setup_data_directories(source_path=None)


def test_baseworker_setup_data_directories_falls_back_when_output_unavailable(monkeypatch, tmp_path):
    worker = DummyWorker()
    share_root = tmp_path / "share"
    input_dir = share_root / "flight_trajectory" / "pipeline"
    input_dir.mkdir(parents=True)

    fallback_base = tmp_path / "localshare"
    env = SimpleNamespace(
        AGI_LOCAL_SHARE=fallback_base,
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

    requested_output = share_root / "reports" / "out"
    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == requested_output:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)

    original_mkdir = Path.mkdir

    def _patched_mkdir(self, *args, **kwargs):
        if self == requested_output:
            raise OSError("mkdir failed")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _patched_mkdir, raising=False)

    warnings = []
    monkeypatch.setattr(base_worker_mod.logger, "warning", lambda msg, *args: warnings.append(msg % args))

    result = worker.setup_data_directories(
        source_path=Path("flight_trajectory/pipeline"),
        target_path=Path("reports/out"),
        target_subdir="output",
    )

    expected_fallback = fallback_base / "demo" / "output"

    assert result.input_path == input_dir.resolve()
    assert result.normalized_output == expected_fallback.as_posix()
    assert worker.data_out == expected_fallback.as_posix()
    assert expected_fallback.is_dir()
    assert warnings
    assert "using fallback" in warnings[0]


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


def test_service_loop_moves_unreadable_task_to_failed(tmp_path):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    task_file = pending / "000002-bad.task.pkl"
    task_file.write_bytes(b"not-a-pickle")

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    deadline = time.time() + 2.0
    failed_file = queue_root / "failed" / task_file.name
    while time.time() < deadline and not failed_file.exists():
        time.sleep(0.05)

    assert failed_file.exists(), "Unreadable task was not moved to failed"

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("failed") == 0


def test_service_loop_records_worker_failures(tmp_path):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    worker.works = _raise

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    payload = {
        "task_id": "batch-fail",
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
    task_file = pending / "000003-batch-fail-000-worker.task.pkl"
    with open(task_file, "wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()

    deadline = time.time() + 2.0
    failed_file = queue_root / "failed" / task_file.name
    while time.time() < deadline and not failed_file.exists():
        time.sleep(0.05)

    assert failed_file.exists(), "Failed task was not moved to failed"

    with open(failed_file, "rb") as stream:
        failed_payload = pickle.load(stream)
    assert failed_payload["status"] == "failed"
    assert failed_payload["error"] == "boom"
    assert "RuntimeError: boom" in failed_payload["traceback"]

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("failed") == 1


def test_service_loop_skips_tasks_for_other_workers(tmp_path):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    mismatched_idx = pending / "000004-idx.task.pkl"
    with open(mismatched_idx, "wb") as stream:
        pickle.dump({"worker_idx": 99, "plan": [], "metadata": []}, stream, protocol=pickle.HIGHEST_PROTOCOL)

    mismatched_worker = pending / "000005-worker.task.pkl"
    with open(mismatched_worker, "wb") as stream:
        pickle.dump({"worker": "tcp://other:8787", "plan": [], "metadata": []}, stream, protocol=pickle.HIGHEST_PROTOCOL)

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    time.sleep(0.2)

    assert mismatched_idx.exists()
    assert mismatched_worker.exists()

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("processed") == 0


def test_service_loop_swallow_heartbeat_write_failure(monkeypatch, tmp_path):
    class LoopWorker(BaseWorker):
        def __init__(self):
            self.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "queue"))

        def loop(self, stop_event):
            stop_event.set()
            return False

    worker = LoopWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._insts = {0: worker}

    monkeypatch.setattr(base_worker_mod.os, "replace", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("replace denied")))

    payload = BaseWorker.loop(poll_interval=0.0)

    assert payload["status"] == "stopped"
    assert list((tmp_path / "queue" / "heartbeats").glob("*.tmp")) == []


def test_service_loop_skips_claim_races(tmp_path, monkeypatch):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    task_file = pending / "000006-claim-race.task.pkl"
    with open(task_file, "wb") as stream:
        pickle.dump({"worker_idx": 0, "plan": [], "metadata": []}, stream, protocol=pickle.HIGHEST_PROTOCOL)

    original_replace = Path.replace

    def _patched_replace(self, target):
        if self == task_file:
            raise FileNotFoundError("claimed elsewhere")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _patched_replace, raising=False)

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    time.sleep(0.2)

    assert task_file.exists()

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("processed") == 0


def test_service_loop_handles_disappearing_task_files(tmp_path, monkeypatch):
    worker = DummyWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "127.0.0.1:8787"
    worker.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "service_queue"))

    queue_root = Path(worker.args._agi_service_queue_dir)
    pending = queue_root / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    task_file = pending / "000007-disappearing.task.pkl"
    with open(task_file, "wb") as stream:
        pickle.dump({"worker_idx": 0, "plan": [], "metadata": []}, stream, protocol=pickle.HIGHEST_PROTOCOL)

    original_open = open

    def _patched_open(path, *args, **kwargs):
        if Path(path) == task_file and "rb" in kwargs.get("mode", args[0] if args else ""):
            raise FileNotFoundError("gone")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(base_worker_mod, "open", _patched_open, raising=False)

    result: dict[str, object] = {}

    def _run_loop():
        result["payload"] = BaseWorker.loop(poll_interval=0.05)

    thread = threading.Thread(target=_run_loop, daemon=True)
    thread.start()
    time.sleep(0.2)

    assert task_file.exists()

    assert BaseWorker.break_loop() is True
    thread.join(timeout=2)
    assert not thread.is_alive(), "Service loop did not stop after break_loop"

    payload_out = result.get("payload")
    assert isinstance(payload_out, dict)
    assert payload_out.get("processed") == 0


def test_service_loop_custom_worker_writes_heartbeat_and_calls_stop(tmp_path):
    class LoopWorker(BaseWorker):
        def __init__(self):
            self.args = SimpleNamespace(_agi_service_queue_dir=str(tmp_path / "queue"))
            self.stop_called = False

        def loop(self, stop_event):
            stop_event.set()
            return False

        def stop(self):
            self.stop_called = True

    worker = LoopWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._insts = {0: worker}

    payload = BaseWorker.loop(poll_interval=0.0)

    heartbeat_files = list((tmp_path / "queue" / "heartbeats").glob("*.json"))
    assert payload["status"] == "stopped"
    assert worker.stop_called is True
    assert heartbeat_files
    heartbeat_payload = json.loads(heartbeat_files[0].read_text(encoding="utf-8"))
    assert heartbeat_payload["state"] == "stopped"


def test_service_loop_supports_async_worker_override():
    class AsyncLoopWorker(BaseWorker):
        async def loop(self):
            return False

    worker = AsyncLoopWorker()
    BaseWorker._worker_id = 0
    BaseWorker._worker = "tcp://127.0.0.1:8787"
    BaseWorker._insts = {0: worker}

    payload = BaseWorker.loop(poll_interval=0.0)

    assert payload["status"] == "stopped"
