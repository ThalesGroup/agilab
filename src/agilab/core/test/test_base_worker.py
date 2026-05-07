from __future__ import annotations

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("boom")),
    )
    assert BaseWorker._normalized_path("~/demo") == Path("~/demo").expanduser()

    env = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(OSError("no share")),
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
        share_root_path=lambda: (_ for _ in ()).throw(OSError("no share")),
        agi_share_path_abs=tmp_path / "absolute-share",
        agi_share_path=Path("clustershare"),
        home_abs=tmp_path / "home",
    )
    assert BaseWorker._share_root_path(env_absolute) == tmp_path / "absolute-share"

    env_home = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(OSError("no share")),
        agi_share_path_abs=None,
        agi_share_path=None,
        home_abs=tmp_path / "home",
    )
    assert BaseWorker._share_root_path(env_home) == (tmp_path / "home")


def test_baseworker_collect_share_aliases_and_data_dir_fallbacks(monkeypatch, tmp_path):
    class _BrokenPath:
        def __fspath__(self):
            raise OSError("boom")

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
        classmethod(lambda cls, value: (_ for _ in ()).throw(OSError("normalize failed"))),
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

    def _fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        raise OSError("mount failed")

    monkeypatch.setattr(base_worker_mod.subprocess, "run", _fake_run)

    result = BaseWorker.expand_and_join("/Users/demo/data", "child.txt")

    assert calls
    assert calls[0][0][:3] == ["net", "use", "Z:"]
    assert calls[0][1]["check"] is True
    assert "shell" not in calls[0][1]
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

    def _fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        raise OSError("net use failed")

    monkeypatch.setattr(base_worker_mod.subprocess, "run", _fake_run)

    result = BaseWorker.normalize_dataset_path("relative/data")

    assert calls
    assert calls[0][0][:3] == ["net", "use", "Z:"]
    assert calls[0][1]["check"] is True
    assert "shell" not in calls[0][1]
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
        lambda cmd, **kwargs: calls.append((cmd, kwargs)),
    )

    result = BaseWorker.normalize_dataset_path("/tmp/demo/data")

    assert calls
    assert calls[0][0][:3] == ["net", "use", "Z:"]
    assert calls[0][1]["check"] is True
    assert "shell" not in calls[0][1]
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


def test_baseworker_path_support_runtime_bugs_propagate(tmp_path, monkeypatch):
    monkeypatch.setattr(
        base_worker_mod,
        "normalize_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("normalize bug")),
    )
    with pytest.raises(RuntimeError, match="normalize bug"):
        BaseWorker._normalized_path("~/demo")

    env = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(RuntimeError("share bug")),
        agi_share_path_abs=None,
        agi_share_path=Path("clustershare"),
        home_abs=tmp_path,
        _is_managed_pc=False,
    )
    with pytest.raises(RuntimeError, match="share bug"):
        BaseWorker._share_root_path(env)

    class _BrokenRuntimePath:
        def __fspath__(self):
            raise RuntimeError("alias bug")

    env_alias = SimpleNamespace(
        AGILAB_SHARE_HINT=Path("clustershare/link_sim"),
        AGILAB_SHARE_REL=_BrokenRuntimePath(),
        agi_share_path=Path("clustershare"),
    )
    with pytest.raises(RuntimeError, match="alias bug"):
        BaseWorker._collect_share_aliases(env_alias, tmp_path / "share")

    monkeypatch.setattr(
        Path,
        "unlink",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cleanup bug")),
    )
    with pytest.raises(RuntimeError, match="cleanup bug"):
        BaseWorker._can_create_path(tmp_path / "output" / "data.csv")


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


def test_baseworker_default_extend_payload_returns_original_mapping():
    worker = DummyWorker()
    payload = {"alpha": 1}

    assert worker._extend_payload(payload) is payload


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


def test_baseworker_loop_requires_initialization():
    BaseWorker._worker_id = None
    BaseWorker._insts = {}

    with pytest.raises(RuntimeError, match="before worker initialisation"):
        BaseWorker.loop()


def test_baseworker_loop_handles_signature_fallback_polling_and_stop_event(monkeypatch):
    waits: list[float] = []

    class FakeEvent:
        def __init__(self):
            self._set = False

        def is_set(self):
            return self._set

        def set(self):
            self._set = True

        def wait(self, timeout=None):
            waits.append(timeout)
            return self._set

    class PollingWorker(BaseWorker):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def loop(self):
            self.calls += 1
            return False if self.calls > 1 else None

    worker = PollingWorker()
    BaseWorker._worker_id = 4
    BaseWorker._worker = "local-worker"
    BaseWorker._insts = {4: worker}
    monkeypatch.setattr(base_worker_mod.threading, "Event", FakeEvent)
    monkeypatch.setattr(
        base_worker_mod.inspect,
        "signature",
        lambda _fn: (_ for _ in ()).throw(TypeError("no signature")),
    )

    result = BaseWorker.loop(poll_interval=0.25)

    assert result["status"] == "stopped"
    assert waits == [0.25]


def test_baseworker_loop_accepts_stop_event_without_base_polling(monkeypatch):
    waits: list[float | None] = []

    class FakeEvent:
        def __init__(self):
            self._set = False

        def is_set(self):
            return self._set

        def set(self):
            self._set = True

        def wait(self, timeout=None):
            waits.append(timeout)
            return self._set

    class ManagedLoopWorker(BaseWorker):
        def __init__(self):
            super().__init__()
            self.stop_events: list[object] = []

        def loop(self, stop_event):
            self.stop_events.append(stop_event)
            stop_event.set()
            return None

    worker = ManagedLoopWorker()
    BaseWorker._worker_id = 5
    BaseWorker._worker = "local-worker"
    BaseWorker._insts = {5: worker}
    monkeypatch.setattr(base_worker_mod.threading, "Event", FakeEvent)

    result = BaseWorker.loop(poll_interval=0.25)

    assert result["status"] == "stopped"
    assert len(worker.stop_events) == 1
    assert waits == []


def test_baseworker_path_and_subprocess_helpers(monkeypatch, tmp_path):
    expanded = BaseWorker.expand("folder/demo.csv", base_directory=tmp_path)
    assert expanded == str((tmp_path / "folder" / "demo.csv").resolve())
    assert BaseWorker._join(str(tmp_path), "child.txt").endswith("/child.txt")

    monkeypatch.setattr(BaseWorker, "expand", staticmethod(lambda value: str(tmp_path / value)))
    assert BaseWorker.expand_and_join("base", "child.txt").endswith("/base/child.txt")

def test_baseworker_expand_chunk():
    reconstructed, chunk_len, total_workers = BaseWorker._expand_chunk(
        {"__agi_worker_chunk__": True, "chunk": ["a"], "total_workers": 3, "worker_idx": 1},
        1,
    )
    assert reconstructed == [[], ["a"], []]
    assert chunk_len == 1
    assert total_workers == 3


def test_baseworker_args_namespace_mapping_helpers():
    args = base_worker_mod.ArgsNamespace(alpha=1)

    assert args["alpha"] == 1
    assert args.get("alpha") == 1
    assert args.get("missing", "fallback") == "fallback"
    assert "alpha" in args
    assert "missing" not in args
    assert args.to_dict() == {"alpha": 1}

    with pytest.raises(KeyError, match="missing"):
        _ = args["missing"]


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


def test_baseworker_setup_data_directories_logs_rmtree_failures(monkeypatch, tmp_path):
    worker = DummyWorker()
    share_root = tmp_path / "share"
    input_dir = share_root / "flight_trajectory" / "pipeline"
    output_dir = input_dir.parent / "output"
    output_dir.mkdir(parents=True)

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

    infos: list[str] = []
    monkeypatch.setattr(
        base_worker_mod.shutil,
        "rmtree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cleanup failed")),
    )
    monkeypatch.setattr(
        base_worker_mod.logger,
        "info",
        lambda message, *args: infos.append(str(message % args if args else message)),
    )

    result = worker.setup_data_directories(
        source_path=Path("flight_trajectory/pipeline"),
        target_subdir="output",
        reset_target=True,
    )

    assert result.output_path == output_dir
    assert any("Error removing directory" in message for message in infos)


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


def test_baseworker_onerror_propagates_non_oserror_from_retry(tmp_path, monkeypatch):
    target = tmp_path / "locked.txt"
    target.write_text("x", encoding="utf-8")

    monkeypatch.setattr(base_worker_mod.os, "access", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(base_worker_mod.os, "chmod", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="bad callback"):
        BaseWorker._onerror(
            lambda _path: (_ for _ in ()).throw(ValueError("bad callback")),
            str(target),
            (PermissionError, PermissionError("denied"), None),
        )


def test_baseworker_onerror_logs_oserror_from_retry(tmp_path, monkeypatch):
    target = tmp_path / "locked.txt"
    target.write_text("x", encoding="utf-8")
    errors: list[str] = []

    monkeypatch.setattr(base_worker_mod.os, "access", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(base_worker_mod.os, "chmod", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        base_worker_mod.logger,
        "error",
        lambda message, *args: errors.append(str(message % args if args else message)),
    )

    BaseWorker._onerror(
        lambda _path: (_ for _ in ()).throw(OSError("retry failed")),
        str(target),
        (PermissionError, PermissionError("denied"), None),
    )

    assert any("warning failed to grant write access" in message for message in errors)


def test_baseworker_setup_data_directories_fallback_to_home_and_failure(monkeypatch, tmp_path):
    worker = DummyWorker()
    share_root = tmp_path / "share"
    input_dir = share_root / "flight_trajectory" / "pipeline"
    input_dir.mkdir(parents=True)

    env = SimpleNamespace(
        AGI_LOCAL_SHARE="",
        home_abs=tmp_path / "home-base",
        target="demo",
        _is_managed_pc=False,
        share_root_path=lambda: share_root,
        agi_share_path_abs=share_root,
        agi_share_path=Path("clustershare"),
        AGILAB_SHARE_HINT=None,
        AGILAB_SHARE_REL=None,
    )
    worker.env = env

    requested_output = input_dir.parent / "reports"
    fallback_output = env.home_abs / "demo" / "output"
    original_mkdir = Path.mkdir

    def _patched_mkdir(self, *args, **kwargs):
        if self in {requested_output, fallback_output}:
            raise OSError(f"mkdir failed for {self}")
        return original_mkdir(self, *args, **kwargs)

    errors: list[str] = []
    monkeypatch.setattr(Path, "mkdir", _patched_mkdir, raising=False)
    monkeypatch.setattr(base_worker_mod.logger, "error", lambda message, *args: errors.append(str(message % args if args else message)))

    with pytest.raises(OSError):
        worker.setup_data_directories(
            source_path=Path("flight_trajectory/pipeline"),
            target_path=Path("reports"),
            target_subdir="output",
        )

    assert any("Fallback output directory failed" in message for message in errors)


def test_baseworker_setup_data_directories_without_env_falls_back_to_home(monkeypatch, tmp_path):
    worker = DummyWorker()
    fake_home = tmp_path / "home"
    input_dir = fake_home / "flight_trajectory" / "pipeline"
    input_dir.mkdir(parents=True)
    requested_output = fake_home / "reports" / "out"
    fallback_output = fake_home / "out" / "output"

    original_home = Path.home
    original_mkdir = Path.mkdir

    def _patched_home():
        return fake_home

    def _patched_mkdir(self, *args, **kwargs):
        if self == requested_output:
            raise OSError("mkdir failed")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(base_worker_mod.Path, "home", staticmethod(_patched_home))
    monkeypatch.setattr(Path, "home", staticmethod(_patched_home))
    monkeypatch.setattr(Path, "mkdir", _patched_mkdir, raising=False)

    result = worker.setup_data_directories(
        source_path=Path("flight_trajectory/pipeline"),
        target_path=Path("reports/out"),
        target_subdir="output",
    )

    assert result.input_path == input_dir.resolve(strict=False)
    assert result.normalized_output == fallback_output.as_posix()
    assert worker.data_out == fallback_output.as_posix()
