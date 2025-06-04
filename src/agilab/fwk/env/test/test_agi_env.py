import pytest
import io
from agi_env import AgiEnv
from unittest import mock
import asyncio
import subprocess
import logging

@pytest.fixture
def env():
    agipath = AgiEnv.locate_agi_installation(verbose=0)
    # Initialise AgiEnv avec install_type=1 (normal)
    return AgiEnv(active_app="flight", apps_dir=agipath / "apps", install_type=1, verbose=1)

def test_replace_content_replaces_whole_words(env):
    txt = "foo foo_bar barfoo bar"
    rename_map = {"foo": "baz", "bar": "qux"}
    replaced = env.replace_content(txt, rename_map)
    assert replaced == "baz foo_bar barfoo qux"

def test_replace_content_unary(env):
    txt = "foo bar baz foo"
    rename_map = {"foo": "FOO"}
    replaced = env.replace_content(txt, rename_map)
    assert replaced == "FOO bar baz FOO"

def test_create_symlink_existing_and_errors(tmp_path, caplog):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"

    with caplog.at_level(logging.INFO):
        AgiEnv.create_symlink(src, dest)
        assert dest.is_symlink()

        # Re-creation should not error
        AgiEnv.create_symlink(src, dest)

        dest.unlink()
        dest.write_text("hello")

        AgiEnv.create_symlink(src, dest)

        # DEBUG: print all captured logs for inspection
        for rec in caplog.records:
            print(f"Captured log: {rec.levelname} {rec.name} {rec.getMessage()}")

        assert any("symlink" in rec.getMessage().lower() or "warning" in rec.getMessage().lower()
                   for rec in caplog.records), "Expected symlink or warning messages in logs"

def test_clone_directory_and_cleanup(tmp_path, env):
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

    renamed_py = dest / "file.py"
    assert renamed_py.exists()
    content = renamed_py.read_text()
    # Check rename_map values appear somewhere in content
    assert any(v in content for v in rename_map.values())

def test_change_active_app_reinitializes(monkeypatch, env):
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
async def test_run_timeout_and_exception(env):
    class DummyProcess:
        def __init__(self):
            self.returncode = None
            self.stdout = io.StringIO("partial output\n")
            self.stderr = io.StringIO("error output\n")
        def poll(self):
            return 1
        def kill(self):
            return 2
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="sleep", timeout=timeout)

    with mock.patch("subprocess.Popen", return_value=DummyProcess()):
        with pytest.raises(RuntimeError):
            await env.run("sleep 1", venv=".", wait=True)

@pytest.mark.asyncio
async def test_exec_ssh_async_reads(monkeypatch, env):
    class DummyStream:
        def __init__(self, lines):
            self.lines = lines

        async def read(self):
            return b"".join(self.lines)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.lines:
                raise StopAsyncIteration
            return self.lines.pop(0)

    class DummyProcess:
        def __init__(self):
            self.stdout = DummyStream([b"INFO: line1\n", b"ERROR: line2\n"])
            self.stderr = DummyStream([b"DEBUG: line3\n"])

        async def wait(self):
            return 0

    class DummyConn:
        async def create_process(self, cmd):
            return DummyProcess()

        def is_closed(self):
            return False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    # Now monkeypatch after DummyConn is defined:
    monkeypatch.setattr(env, "get_ssh_connection", lambda ip: DummyConn())

    result = await env.exec_ssh_async("1.2.3.4", "ls")

    if isinstance(result, bytes):
        result = result.decode("utf-8").strip()

    assert result == "ERROR: line2"


def test_humanize_validation_errors(env):
    from pydantic import BaseModel, ValidationError, constr

    class TestModel(BaseModel):
        name: constr(min_length=3)

    with pytest.raises(ValidationError) as exc_info:
        TestModel(name="a")

    errors = env.humanize_validation_errors(exc_info.value)
    assert any("❌ **name**" in e for e in errors)
