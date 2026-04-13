from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "About_agilab.py"
SPEC = importlib.util.spec_from_file_location("agilab_about_helpers", MODULE_PATH)
assert SPEC and SPEC.loader
about_agilab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(about_agilab)


class _BrokenTemplatePath:
    def read_text(self, encoding: str = "utf-8") -> str:  # pragma: no cover - called by test
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


def test_ensure_env_file_falls_back_to_touch_when_template_read_fails(tmp_path, monkeypatch):
    env_file = tmp_path / ".agilab" / ".env"
    monkeypatch.setattr(about_agilab, "TEMPLATE_ENV_PATH", _BrokenTemplatePath())

    result = about_agilab._ensure_env_file(env_file)

    assert result == env_file
    assert env_file.exists()
    assert env_file.read_text(encoding="utf-8") == ""


def test_refresh_env_from_file_updates_env_map_and_apps_path(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_MODEL=gpt-5.4",
                f"APPS_PATH={apps_dir}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)

    env = SimpleNamespace(
        envars={},
        apps_path="old/path",
    )

    about_agilab._refresh_env_from_file(env)

    assert env.envars["OPENAI_MODEL"] == "gpt-5.4"
    assert env.envars["APPS_PATH"] == str(apps_dir)
    assert env.apps_path == apps_dir.resolve()
    assert about_agilab.st.session_state["env_file_mtime_ns"] == env_file.stat().st_mtime_ns


def test_refresh_env_from_file_ignores_bad_envars_mapping(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_MODEL=gpt-5.4\n", encoding="utf-8")
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)

    env = SimpleNamespace(
        envars=object(),
        apps_path="old/path",
    )

    about_agilab._refresh_env_from_file(env)

    assert about_agilab.st.session_state["env_file_mtime_ns"] == env_file.stat().st_mtime_ns
