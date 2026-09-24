"""Aligned source refresh and dotenv updates preserve state on boundary failures."""
from collections import OrderedDict
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_env.runtime import hot_source_support as hot
from agi_env.runtime import env_config_support as config


@pytest.fixture
def aligned_root(tmp_path, monkeypatch):
    monkeypatch.setattr(hot, "_AGI_ENV_PACKAGE_ROOT", tmp_path.resolve())
    monkeypatch.setattr(hot, "_MODULE_CACHE", OrderedDict())
    yield tmp_path
    hot._clear_aligned_module_cache()


def _stale(path):
    module = ModuleType("stale_test_module")
    module.__file__ = str(path)
    return module


@pytest.mark.parametrize("origin", [None, "", 42])
def test_source_refresh_requires_verifiable_file_identity(origin):
    module = ModuleType("missing_origin")
    module.__file__ = origin
    with pytest.raises(hot.StaleRuntimeModuleError, match="no verifiable source"):
        hot.aligned_module_callable(module, "new_callable")


def test_source_refresh_rejects_directory_as_module(aligned_root):
    with pytest.raises(hot.StaleRuntimeModuleError, match="not a file"):
        hot.aligned_module_callable(_stale(aligned_root), "missing")


def test_source_read_failure_does_not_publish_partial_module(aligned_root, monkeypatch):
    source = aligned_root / "source.py"
    source.write_text("def new_callable(): return 1")
    read = Path.read_bytes
    def fail(path):
        if path == source:
            raise OSError("source disappeared")
        return read(path)
    monkeypatch.setattr(Path, "read_bytes", fail)
    with pytest.raises(hot.StaleRuntimeModuleError, match="Cannot read"):
        hot.aligned_module_callable(_stale(source), "new_callable")
    assert not hot._MODULE_CACHE


@pytest.mark.parametrize("source", ["value = 3", "def other(): return 1"])
def test_refresh_refuses_missing_or_noncallable_symbol(aligned_root, source):
    path = aligned_root / "source.py"
    path.write_text(source)
    with pytest.raises(hot.StaleRuntimeModuleError, match="does not expose callable"):
        hot.aligned_module_callable(_stale(path), "value")


@pytest.mark.parametrize("source", ["raise RuntimeError('init failed')", "def broken(: pass"])
def test_failed_source_execution_removes_partial_sys_modules_entry(aligned_root, source):
    path = aligned_root / "broken.py"
    path.write_text(source)
    before = set(sys.modules)
    with pytest.raises(hot.StaleRuntimeModuleError, match="Unable to execute") as caught:
        hot.aligned_module_callable(_stale(path), "missing")
    assert isinstance(caught.value.__cause__, (RuntimeError, SyntaxError))
    assert not hot._MODULE_CACHE
    assert not [key for key in set(sys.modules) - before if key.startswith("agi_env.runtime._hot_source_")]


def test_source_with_unsupported_loader_is_rejected(aligned_root):
    path = aligned_root / "source.unsupported"
    path.write_text("def candidate(): return 1")
    with pytest.raises(hot.StaleRuntimeModuleError, match="Unable to load"):
        hot.aligned_module_callable(_stale(path), "candidate")


def test_aligned_cache_eviction_removes_only_evicted_module(aligned_root, monkeypatch):
    monkeypatch.setattr(hot, "_MODULE_CACHE_LIMIT", 1)
    first = aligned_root / "first.py"
    second = aligned_root / "second.py"
    first.write_text("def candidate(): return 'first'")
    second.write_text("def candidate(): return 'second'")
    first_call = hot.aligned_module_callable(_stale(first), "candidate")
    first_module = first_call.__module__
    assert first_module in sys.modules
    second_call = hot.aligned_module_callable(_stale(second), "candidate")
    assert first_module not in sys.modules
    assert second_call.__module__ in sys.modules
    assert first_call() == "first"
    assert second_call() == "second"
    assert len(hot._MODULE_CACHE) == 1


@pytest.mark.parametrize("phase", ["open", "fsync"])
def test_environment_directory_sync_is_best_effort_and_closes_descriptor(tmp_path, monkeypatch, phase):
    os_api = SimpleNamespace(O_RDONLY=0, open=Mock(return_value=51), fsync=Mock(), close=Mock())
    getattr(os_api, phase).side_effect = OSError("unsupported directory sync")
    monkeypatch.setattr(config, "_stdlib_os", os_api)
    config._fsync_directory(tmp_path)
    if phase == "open":
        os_api.close.assert_not_called()
    else:
        os_api.close.assert_called_once_with(51)


@pytest.mark.parametrize("remove_temp", [False, True])
def test_dotenv_publication_failure_preserves_original_and_cleans_temporary_file(tmp_path, monkeypatch, remove_temp):
    target = tmp_path / ".env"
    target.write_text("KEEP=original\n")
    def fail(temp, _target):
        if remove_temp:
            temp.unlink()
        raise OSError("publication denied")
    monkeypatch.setattr(config, "_publish_env_temp", fail)
    with pytest.raises(OSError, match="publication denied"):
        config.update_env_file_text(target, lambda _: "KEEP=changed\n")
    assert target.read_text() == "KEEP=original\n"
    assert not list(tmp_path.glob(".*.tmp"))


def test_dotenv_none_update_preserves_existing_contents(tmp_path):
    target = tmp_path / ".env"
    target.write_text("KEEP=original\n")
    assert config.update_env_file_text(target, lambda _: None) is False
    assert target.read_text() == "KEEP=original\n"


def test_empty_environment_update_creates_no_files(tmp_path):
    target = tmp_path / "missing" / ".env"
    config.write_env_updates(target, {})
    assert not target.parent.exists()
