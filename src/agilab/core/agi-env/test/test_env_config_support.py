from pathlib import Path

import agi_env.env_config_support as env_config_module


def test_clean_envar_value_handles_blank_values_and_process_fallback(monkeypatch):
    monkeypatch.setenv("AGI_DEMO", " from-process ")

    assert env_config_module.clean_envar_value({"AGI_DEMO": " value "}, "AGI_DEMO") == "value"
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
        "OPENAI_MODEL=\n"
        "APP_DEFAULT=   \n"
        "AGI_LOG_DIR=/tmp/logs\n"
        "TABLE_MAX_ROWS=1000\n",
        encoding="utf-8",
    )

    values = env_config_module.load_dotenv_values(dotenv_path)

    assert values == {
        "AGI_LOG_DIR": "/tmp/logs",
        "TABLE_MAX_ROWS": "1000",
    }


def test_clean_envar_value_handles_mapping_errors_and_dotenv_none(monkeypatch, tmp_path: Path):
    class BadMapping(dict):
        def get(self, key, default=None):
            raise RuntimeError("boom")

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
