"""Settings transaction failures preserve files, locks and unrelated ownership."""
import builtins
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_env.project import app_settings_support as settings


@pytest.mark.parametrize("owned,defaults", [([], []), ([("x",)], [("x",)])])
def test_invalid_ownership_contract_is_rejected_without_creating_file(tmp_path, owned, defaults):
    target = tmp_path / "settings.toml"
    with pytest.raises(ValueError, match="required|disjoint"):
        settings.update_app_settings_owned(target, {}, owned_paths=owned, default_paths=defaults)
    assert not target.exists()


@pytest.mark.parametrize("path", [(), ("",), (None,), ("x", "")])
def test_invalid_owned_leaf_never_publishes(tmp_path, path):
    target = tmp_path / "settings.toml"
    target.write_text("keep = 1\n")
    with pytest.raises(ValueError, match="non-empty strings"):
        settings.update_app_settings_owned(target, {}, owned_paths=[path])
    assert target.read_text() == "keep = 1\n"


def test_absent_owned_nested_leaf_and_absent_default_do_not_rewrite(tmp_path):
    target = tmp_path / "settings.toml"
    target.write_text("keep = 1\n")
    payload, changed = settings.update_app_settings_owned(
        target, {}, owned_paths=[("absent", "child")], default_paths=[("missing",)]
    )
    assert payload == {"keep": 1} and changed is False
    assert target.read_text() == "keep = 1\n"


def test_owned_nested_value_replaces_scalar_parent_and_preserves_siblings(tmp_path):
    target = tmp_path / "settings.toml"
    target.write_text("keep = 1\nbranch = 2\n")
    payload, changed = settings.update_app_settings_owned(
        target, {"branch": {"child": 3}}, owned_paths=[("branch", "child")]
    )
    assert changed is True
    assert payload["branch"] == {"child": 3}
    assert payload["keep"] == 1
    assert settings.read_app_settings(target)["branch"] == {"child": 3}


def test_missing_settings_without_creation_never_invokes_mutator(tmp_path):
    mutate = Mock()
    with pytest.raises(FileNotFoundError, match="Settings file not found"):
        settings.update_app_settings(tmp_path / "missing.toml", mutate, create_missing=False)
    mutate.assert_not_called()


def test_failed_file_lock_acquisition_closes_handle_and_releases_thread_lock(tmp_path, monkeypatch):
    lock = Mock()
    lock.acquire.return_value = True
    monkeypatch.setattr(settings, "_app_settings_thread_lock", lambda _: lock)
    monkeypatch.setattr(settings, "acquire_bounded_file_lock", Mock(side_effect=TimeoutError("busy")))
    release = Mock()
    monkeypatch.setattr(settings, "release_file_lock", release)
    handles = []
    original = Path.open
    def record(path, *args, **kwargs):
        handle = original(path, *args, **kwargs)
        handles.append(handle)
        return handle
    monkeypatch.setattr(Path, "open", record)
    with pytest.raises(TimeoutError, match="busy"):
        with settings.app_settings_file_lock(tmp_path / "settings.toml"):
            pytest.fail("transaction entered without lock")
    assert len(handles) == 1 and handles[0].closed
    lock.release.assert_called_once_with()
    release.assert_not_called()


@pytest.mark.parametrize("platform,phase", [("posix", "open"), ("posix", "fsync"), ("nt", "fsync")])
def test_directory_sync_failure_closes_open_descriptor(tmp_path, monkeypatch, platform, phase):
    fake = SimpleNamespace(name=platform, O_RDONLY=0, open=Mock(return_value=17),
                           fsync=Mock(), close=Mock())
    getattr(fake, phase).side_effect = OSError("sync unavailable")
    monkeypatch.setattr(settings, "os", fake)
    if platform == "nt":
        settings._fsync_directory(tmp_path)
    else:
        with pytest.raises(OSError, match="sync unavailable"):
            settings._fsync_directory(tmp_path)
    if phase == "open":
        fake.close.assert_not_called()
    else:
        fake.close.assert_called_once_with(17)


@pytest.mark.parametrize("missing", ["tomli_w", "tomlkit", "nested_dependency"])
def test_settings_serializer_fallback_distinguishes_missing_dependency(monkeypatch, missing):
    original = builtins.__import__
    fallback = SimpleNamespace(dumps=lambda payload: "answer = 42\n")
    def importing(name, *args, **kwargs):
        if name == "tomli_w":
            raise ModuleNotFoundError("missing writer", name="nested_dependency" if missing == "nested_dependency" else name)
        if name == "tomlkit":
            if missing == "tomlkit":
                raise ModuleNotFoundError("missing fallback", name=name)
            return fallback
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importing)
    stream = BytesIO()
    if missing == "tomli_w":
        settings._default_app_settings_dumper({"answer": 42}, stream)
        assert stream.getvalue() == b"answer = 42\n"
    elif missing == "tomlkit":
        with pytest.raises(RuntimeError, match="requires either"):
            settings._default_app_settings_dumper({}, stream)
        assert stream.getvalue() == b""
    else:
        with pytest.raises(ModuleNotFoundError) as raised:
            settings._default_app_settings_dumper({}, stream)
        assert raised.value.name == "nested_dependency"
        assert stream.getvalue() == b""
