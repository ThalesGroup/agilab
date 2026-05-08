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


def test_load_env_file_map_returns_empty_mapping_for_missing_file(tmp_path: Path):
    assert load_env_file_map(tmp_path / "missing.env") == {}
