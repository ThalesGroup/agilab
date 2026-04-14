from __future__ import annotations

from pathlib import Path

from agi_env.ui_state_support import (
    load_global_state,
    normalize_existing_path,
    normalize_path_string,
    persist_global_state,
)


def test_ui_state_support_loads_legacy_when_toml_is_invalid(tmp_path):
    state_file = tmp_path / "state.toml"
    state_file.write_text("not = [valid\n", encoding="utf-8")
    legacy = tmp_path / ".last-active-app"
    legacy.write_text("/tmp/demo\n", encoding="utf-8")

    assert load_global_state(state_file, legacy) == {"last_active_app": "/tmp/demo"}


def test_ui_state_support_loads_empty_when_all_state_files_are_missing(tmp_path):
    state_file = tmp_path / "state.toml"
    legacy = tmp_path / ".last-active-app"

    assert load_global_state(state_file, legacy) == {}


def test_ui_state_support_ignores_blank_legacy_contents(tmp_path):
    state_file = tmp_path / "state.toml"
    legacy = tmp_path / ".last-active-app"
    legacy.write_text("  \n", encoding="utf-8")

    assert load_global_state(state_file, legacy) == {}


def test_ui_state_support_ignores_unreadable_legacy_contents(tmp_path):
    state_file = tmp_path / "state.toml"
    legacy = tmp_path / ".last-active-app"
    legacy.write_bytes(b"\xff")

    assert load_global_state(state_file, legacy) == {}


def test_ui_state_support_loads_valid_toml_and_persists_state(tmp_path):
    state_file = tmp_path / "state.toml"
    legacy = tmp_path / ".last-active-app"
    state_file.write_text('last_active_app = "/tmp/demo"\n', encoding="utf-8")

    assert load_global_state(state_file, legacy) == {"last_active_app": "/tmp/demo"}

    dumped: list[dict[str, str]] = []

    def _dump_payload(data, handle):
        dumped.append(dict(data))
        handle.write(b'last_active_app = "/tmp/demo"\n')

    persist_global_state(state_file, {"last_active_app": "/tmp/demo"}, dump_payload_fn=_dump_payload)

    assert dumped == [{"last_active_app": "/tmp/demo"}]
    assert state_file.read_text(encoding="utf-8").strip() == 'last_active_app = "/tmp/demo"'


def test_ui_state_support_persist_global_state_ignores_dump_errors(tmp_path):
    state_file = tmp_path / "state.toml"

    persist_global_state(
        state_file,
        {"last_active_app": "/tmp/demo"},
        dump_payload_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom")),
    )

    assert state_file.exists()
    assert state_file.read_bytes() == b""


def test_ui_state_support_normalizes_existing_paths(tmp_path):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir()

    assert normalize_existing_path(app_dir) == app_dir
    assert normalize_existing_path(object()) is None
    assert normalize_existing_path(None) is None
    assert normalize_path_string(app_dir) == str(app_dir)


def test_ui_state_support_normalize_existing_path_handles_exists_errors():
    class BrokenPath:
        def __init__(self, _value):
            pass

        def expanduser(self):
            return self

        def exists(self):
            raise OSError("boom")

    assert normalize_existing_path("missing", path_cls=BrokenPath) is None


def test_ui_state_support_rejects_broken_path_objects():
    class BrokenPath:
        def __init__(self, _value):
            raise OSError("boom")

    class BrokenStringPath:
        def __init__(self, _value):
            raise TypeError("boom")

    assert normalize_existing_path("missing", path_cls=BrokenPath) is None
    assert normalize_path_string(Path("missing"), path_cls=BrokenStringPath) is None
