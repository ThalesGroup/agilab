import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "env_file_utils.py"
SPEC = importlib.util.spec_from_file_location("agilab_env_file_utils", MODULE_PATH)
assert SPEC and SPEC.loader
env_file_utils = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(env_file_utils)
load_env_file_map = env_file_utils.load_env_file_map


def test_load_env_file_map_reads_comments_and_last_wins(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# OPENAI_MODEL=gpt-5.4",
                "AGI_LOG_DIR=/tmp/logs",
                "#ignored line",
                "SPACED = 'hello world'",
                "AGI_LOG_DIR=/tmp/final",
            ]
        ),
        encoding="utf-8",
    )

    assert load_env_file_map(env_file) == {
        "OPENAI_MODEL": "gpt-5.4",
        "AGI_LOG_DIR": "/tmp/final",
        "SPACED": "hello world",
    }


def test_load_env_file_map_can_ignore_commented_template_defaults(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                '# AGI_EXPORT_DIR="export"',
                "AGI_LOG_DIR=log",
            ]
        ),
        encoding="utf-8",
    )

    assert load_env_file_map(env_file, include_commented=False) == {"AGI_LOG_DIR": "log"}


def test_load_env_file_map_ignores_assignments_without_key(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "=missing",
                "# =commented-missing",
                "VALID=value",
            ]
        ),
        encoding="utf-8",
    )

    assert load_env_file_map(env_file) == {"VALID": "value"}


def test_load_env_file_map_returns_empty_mapping_for_missing_file(tmp_path: Path):
    assert load_env_file_map(tmp_path / "missing.env") == {}


def test_load_env_file_map_retries_windows_sharing_violation(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("READY=1\n", encoding="utf-8")
    real_read_text = Path.read_text
    attempts = 0

    def _transient_read_text(path: Path, *args, **kwargs):
        nonlocal attempts
        if path == env_file:
            attempts += 1
            if attempts == 1:
                raise PermissionError("sharing violation")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(env_file_utils, "_is_windows", lambda: True)
    monkeypatch.setattr(env_file_utils.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(Path, "read_text", _transient_read_text)

    assert load_env_file_map(env_file) == {"READY": "1"}
    assert attempts == 2
