from pathlib import Path
import subprocess
import sys
import time

import agi_env.env_config_support as env_config_module
import agi_env.runtime.atomic_write_support as atomic_write_module
import pytest


_ENV_WRITER = """
import sys
import time
from pathlib import Path

from agi_env.env_config_support import write_env_updates


env_file = Path(sys.argv[1])
key = sys.argv[2]
offset = int(sys.argv[3])
start = Path(sys.argv[4])
deadline = time.monotonic() + 10
while not start.exists():
    if time.monotonic() >= deadline:
        raise TimeoutError("writer start signal was not created")
    time.sleep(0.001)
for index in range(20):
    write_env_updates(env_file, {key: offset + index})
    time.sleep(0.002)
"""


def test_env_file_lock_times_out_instead_of_freezing_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    monkeypatch.setattr(env_config_module, "_ENV_FILE_LOCK_TIMEOUT_SECONDS", 0.01)

    with env_config_module._env_file_lock(env_file):
        with pytest.raises(TimeoutError, match="Another session"):
            with env_config_module._env_file_lock(env_file):
                raise AssertionError("nested lock unexpectedly acquired")


def test_clean_envar_value_handles_blank_values_and_process_fallback(monkeypatch):
    monkeypatch.setenv("AGI_DEMO", " from-process ")

    assert (
        env_config_module.clean_envar_value({"AGI_DEMO": " value "}, "AGI_DEMO")
        == "value"
    )
    assert env_config_module.clean_envar_value({"AGI_DEMO": "   "}, "AGI_DEMO") is None
    assert (
        env_config_module.clean_envar_value(
            {"AGI_DEMO": ""},
            "AGI_DEMO",
            fallback_to_process=True,
        )
        == "from-process"
    )


def test_load_dotenv_values_discards_blank_assignments(tmp_path: Path):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "OPENAI_MODEL=\nAPP_DEFAULT=   \nAGI_LOG_DIR=/tmp/logs\nTABLE_MAX_ROWS=1000\n",
        encoding="utf-8",
    )

    values = env_config_module.load_dotenv_values(dotenv_path)

    assert values == {
        "AGI_LOG_DIR": "/tmp/logs",
        "TABLE_MAX_ROWS": "1000",
    }


def test_load_dotenv_values_retries_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("READY=1\n", encoding="utf-8")
    real_dotenv_values = env_config_module.dotenv_values
    attempts = 0

    def _transient_dotenv_values(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("sharing violation")
        return real_dotenv_values(**kwargs)

    monkeypatch.setattr(atomic_write_module, "_is_windows", lambda: True)
    monkeypatch.setattr(atomic_write_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(
        env_config_module,
        "dotenv_values",
        _transient_dotenv_values,
    )

    assert env_config_module.load_dotenv_values(dotenv_path) == {"READY": "1"}
    assert attempts == 2


def test_clean_envar_value_handles_mapping_errors_and_dotenv_none(
    monkeypatch, tmp_path: Path
):
    class BadMapping(dict):
        def get(self, key, default=None):
            raise TypeError("boom")

    monkeypatch.setenv("AGI_DEMO", " process-value ")
    assert (
        env_config_module.clean_envar_value(
            BadMapping(),
            "AGI_DEMO",
            fallback_to_process=True,
        )
        == "process-value"
    )

    monkeypatch.setattr(
        env_config_module,
        "dotenv_values",
        lambda **_kwargs: {"A": " ", "B": None, "C": " 1 "},
    )
    assert env_config_module.load_dotenv_values(tmp_path / ".env") == {"C": " 1 "}


def test_clean_envar_value_propagates_unexpected_mapping_runtime_bug():
    class BadRuntimeMapping(dict):
        def get(self, key, default=None):
            raise RuntimeError("mapping bug")

    with pytest.raises(RuntimeError, match="mapping bug"):
        env_config_module.clean_envar_value(BadRuntimeMapping(), "AGI_DEMO")


def test_write_env_updates_creates_parent_and_preserves_unquoted_values(tmp_path: Path):
    env_file = tmp_path / ".agilab" / ".env"

    env_config_module.write_env_updates(
        env_file,
        {
            "AGI_DEMO_FLAG": "1",
            "AGI_PATH": "/tmp/demo path",
        },
    )

    env_text = env_file.read_text(encoding="utf-8")
    assert "AGI_DEMO_FLAG=1" in env_text
    assert "AGI_PATH=/tmp/demo path" in env_text
    assert env_file.parent.is_dir()


def test_env_updates_preserve_disjoint_multiprocess_writes_and_reader_parseability(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".agilab" / ".env"
    start = tmp_path / "start"
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _ENV_WRITER,
                str(env_file),
                key,
                str(offset),
                str(start),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for key, offset in (("ALPHA", 100), ("BETA", 200))
    ]
    start.touch()
    while any(process.poll() is None for process in processes):
        if env_file.exists():
            env_config_module.load_dotenv_values(env_file)
        time.sleep(0.001)
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"

    assert env_config_module.load_dotenv_values(env_file) == {
        "ALPHA": "119",
        "BETA": "219",
    }


def test_env_multi_key_update_rolls_back_if_one_mutation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PRESERVED=1\n", encoding="utf-8")
    real_set_key = env_config_module.set_key
    calls = 0

    def failing_set_key(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = real_set_key(*args, **kwargs)
        if calls == 2:
            raise OSError("simulated dotenv failure")
        return result

    monkeypatch.setattr(env_config_module, "set_key", failing_set_key)
    with pytest.raises(OSError, match="simulated dotenv failure"):
        env_config_module.write_env_updates(env_file, {"FIRST": "1", "SECOND": "2"})

    assert env_file.read_text(encoding="utf-8") == "PRESERVED=1\n"
    assert list(tmp_path.glob("..env.*.tmp")) == []


def test_env_update_routes_replace_through_windows_sharing_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    real_retry = env_config_module.run_with_windows_file_sharing_retry
    retry_calls = 0

    def _tracking_retry(operation, **kwargs):
        nonlocal retry_calls
        retry_calls += 1
        return real_retry(operation, **kwargs)

    monkeypatch.setattr(
        env_config_module,
        "run_with_windows_file_sharing_retry",
        _tracking_retry,
    )

    env_config_module.write_env_updates(env_file, {"READY": "1"})

    assert env_file.read_text(encoding="utf-8") == "READY=1\n"
    assert retry_calls == 1


def test_remote_env_update_scripts_serialize_disjoint_process_updates(tmp_path: Path) -> None:
    env_dir = tmp_path / ".agilab"
    env_dir.mkdir()
    env_file = env_dir / ".env"
    env_file.write_text("PRESERVED=1\n", encoding="utf-8")
    scripts = [
        env_config_module.build_remote_env_update_script({"FIRST": "one"}),
        env_config_module.build_remote_env_update_script({"SECOND": "two"}),
    ]
    subprocess_env = {
        **dict(env_config_module._stdlib_os.environ),
        # ``Path.home()`` uses HOME on POSIX and USERPROFILE on Windows.
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
    }
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script],
            env=subprocess_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for script in scripts
    ]

    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        assert Path(stdout.strip()).resolve(strict=False) == env_file.resolve(strict=False)

    values = env_config_module.load_dotenv_values(env_file)
    assert values == {"PRESERVED": "1", "FIRST": "one", "SECOND": "two"}
    assert list(env_dir.glob("..env.*.tmp")) == []
    assert (env_dir / ".env.lock").exists()


def test_remote_env_update_script_rejects_invalid_dotenv_key() -> None:
    with pytest.raises(ValueError, match="Invalid dotenv key"):
        env_config_module.build_remote_env_update_script({"BAD\nKEY": "value"})


def test_remote_env_update_script_bounds_lock_wait() -> None:
    script = env_config_module.build_remote_env_update_script({"READY": "1"})

    assert "deadline = time.monotonic() + 5.0" in script
    assert "Timed out waiting for AGILAB dotenv lock" in script
    assert "if locked:" in script
