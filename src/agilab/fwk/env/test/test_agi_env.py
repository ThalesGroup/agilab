import os
import pytest
import asyncio
from pathlib import Path
from agi_env import AgiEnv
from unittest import mock
import tempfile

@pytest.fixture
def env():
    agipath = AgiEnv.locate_agi_installation(verbose=0)
    return AgiEnv(active_app="flight", apps_dir=agipath / "apps", install_type=1, verbose=1)

def test_replace_content_replaces_whole_words(env):
    txt = "foo foo_bar barfoo bar"
    rename_map = {"foo": "baz", "bar": "qux"}
    replaced = env.replace_content(txt, rename_map)
    assert replaced == "baz foo_bar barfoo qux"

def test_create_symlink_existing_and_errors(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    # create symlink first time
    AgiEnv.create_symlink(src, dest)
    assert dest.is_symlink()

    # calling again should not error and detect existing symlink
    AgiEnv.create_symlink(src, dest)

    # Create a file at dest (not symlink), should warn and not overwrite
    dest.unlink()
    dest.write_text("hello")
    AgiEnv.create_symlink(src, dest)

def test_clone_directory_and_cleanup(tmp_path, env):
    # Setup dummy source project with files for clone_directory
    source = tmp_path / "source_project"
    source.mkdir()
    (source / "file.py").write_text("class SourceWorker:\n    pass")
    (source / "README.md").write_text("source_project readme")
    (source / ".gitignore").write_text("*.pyc\n")
    dest = tmp_path / "dest_project"

    rename_map = env.create_rename_map(source, dest)
    spec = env.read_gitignore(source / ".gitignore")
    env.clone_directory(source, dest, rename_map, spec, source)
    env._cleanup_rename(dest, rename_map)

    # Check that renamed files exist and content replaced
    renamed_py = dest / "file.py"
    assert renamed_py.exists()
    content = renamed_py.read_text()
    # Should have replaced 'FlightWorker' with renamed class in content
    assert any(s in content for s in rename_map.values())

def test_change_active_app_reinitializes(monkeypatch, env):
    # Patch __init__ to track call
    called = {}
    orig_init = AgiEnv.__init__
    def fake_init(self, **kwargs):
        called['called'] = True
        orig_init(self, **kwargs)
    monkeypatch.setattr(AgiEnv, "__init__", fake_init)

    env.app = "flight_project"
    env.change_active_app("my_code_project", install_type=1)
    assert called.get('called', False)

@pytest.mark.asyncio
async def test_run_timeout_and_exception(monkeypatch):
    async def raise_timeout(*args, **kwargs):
        raise asyncio.TimeoutError()
    monkeypatch.setattr("subprocess.Popen", mock.Mock())
    env = AgiEnv(active_app="flight", apps_dir=Path("."), install_type=1)

    # Patch subprocess.Popen to raise TimeoutExpired when communicate called
    class DummyProcess:
        def __init__(self):
            self.returncode = None
            self.stdout = mock.Mock()
            self.stderr = mock.Mock()
        def poll(self):
            return 1
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="sleep", timeout=timeout)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: DummyProcess())
    with pytest.raises(RuntimeError):
        await env.run("sleep 1", venv=".", wait=True)

@pytest.mark.asyncio
async def test_exec_ssh_async_reads(monkeypatch, env):
    class DummyStream:
        def __init__(self, lines):
            self.lines = lines
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self.lines:
                raise StopAsyncIteration
            return self.lines.pop(0)

    class DummyConn:
        async def create_process(self, cmd):
            process = mock.Mock()
            process.stdout = DummyStream([b"INFO: line1\n", b"ERROR: line2\n"])
            process.stderr = DummyStream([b"DEBUG: line3\n"])
            return process

        def is_closed(self):
            return False

    monkeypatch.setattr(env, "get_ssh_connection", mock.AsyncMock(return_value=DummyConn()))

    await env.exec_ssh_async("1.2.3.4", "ls")

def test_humanize_validation_errors(env):
    from pydantic import BaseModel, ValidationError, constr

    class TestModel(BaseModel):
        name: constr(min_length=3)

    with pytest.raises(ValidationError) as exc_info:
        TestModel(name="a")

    errors = env.humanize_validation_errors(exc_info.value)
    assert any("❌ **name**" in e for e in errors)
