from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Literal

import pytest
from annotated_types import Ge, Le, MultipleOf
from pydantic import BaseModel

from agi_env import streamlit_args


class SessionState(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


class DummyStreamlit:
    def __init__(self):
        self.session_state = SessionState()
        self.warning_messages: list[str] = []
        self.number_inputs: list[tuple[str, dict]] = []
        self.selectbox_calls: list[tuple[str, list, int]] = []
        self.text_inputs: list[str] = []
        self.text_areas: list[str] = []
        self.write_calls: list[str] = []

    def checkbox(self, label, value=False):
        return not value

    def number_input(self, label, **kwargs):
        self.number_inputs.append((label, kwargs))
        value = kwargs["value"]
        return value + 1 if isinstance(value, int) else value + 0.5

    def text_input(self, label, value=""):
        self.text_inputs.append(label)
        return f"text:{label}"

    def text_area(self, label, value=""):
        self.text_areas.append(label)
        return f"area:{label}"

    def selectbox(self, label, options, index=0):
        self.selectbox_calls.append((label, list(options), index))
        return options[index]

    def date_input(self, label, value):
        return value

    def warning(self, message):
        self.warning_messages.append(message)

    def write(self, message):
        self.write_calls.append(str(message))


@pytest.fixture()
def dummy_streamlit(monkeypatch):
    dummy = DummyStreamlit()
    monkeypatch.setattr(streamlit_args, "st", dummy)
    return dummy


class DemoArgs(BaseModel):
    flag: bool = True
    count: Annotated[int, Ge(0), Le(10)] = 3
    ratio: Annotated[float, MultipleOf(0.25), Ge(0.25), Le(2.0)] = 1.25
    name: str = "Alice"
    location: Path = Path("/tmp/data")
    start_date: dt.date = dt.date(2024, 1, 1)
    timestamp: dt.datetime = dt.datetime(2024, 1, 1, 12, 0)
    choice: Literal["alpha", "beta"] = "beta"
    optional_text: str | None = None
    tuple_field: tuple[int, int] = (1, 2)
    list_field: list[int] = [1, 2]


def test_render_form_handles_various_field_types(dummy_streamlit):
    model = DemoArgs()
    values = streamlit_args.render_form(model)

    assert values["flag"] is False
    assert values["count"] == model.count + 1
    assert values["ratio"] == pytest.approx(model.ratio + 0.5)
    assert values["name"] == "text:Name"
    assert values["location"] == "text:Location"
    assert values["optional_text"] == "text:Optional Text"
    assert values["tuple_field"] == "area:Tuple Field"
    assert values["list_field"] == "area:List Field"
    assert values["choice"] == "beta"
    assert dummy_streamlit.selectbox_calls[0][2] == 1
    assert dummy_streamlit.number_inputs[0][1]["min_value"] == 0
    assert dummy_streamlit.number_inputs[0][1]["max_value"] == 10
    assert dummy_streamlit.number_inputs[1][1]["step"] == pytest.approx(0.25)


def test_constraint_value_returns_none_when_constraint_absent():
    field = DemoArgs.model_fields["name"]
    assert streamlit_args._constraint_value(field, Ge, "ge") is None


def test_load_args_state_reads_settings(tmp_path, dummy_streamlit):
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        '[args]\nflag = true\ncount = 5\nratio = 1.5\nname = "Bob"\nchoice = "beta"\n',
        encoding="utf-8",
    )
    args_module = SimpleNamespace(
        ArgsModel=DemoArgs,
        ensure_defaults=lambda args, env: args,
    )
    env = SimpleNamespace(app_settings_file=settings_path, humanize_validation_errors=lambda exc: ["msg"])

    defaults_model, payload, returned_path = streamlit_args.load_args_state(
        env,
        args_module=args_module,
    )

    assert returned_path == settings_path
    assert defaults_model.name == "Bob"
    assert payload["count"] == 5
    assert dummy_streamlit.session_state["app_settings"]["args"]["ratio"] == pytest.approx(1.5)


def test_load_args_state_prefers_session_state_when_args_from_ui(tmp_path, dummy_streamlit):
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text('[args]\nname = "DiskValue"\n', encoding="utf-8")
    dummy_streamlit.session_state["app_settings"] = {
        "args": {
            "name": "SessionValue",
            "choice": "beta",
            "count": 6,
            "ratio": 1.5,
        }
    }
    dummy_streamlit.session_state["is_args_from_ui"] = True

    args_module = SimpleNamespace(
        ArgsModel=DemoArgs,
        ensure_defaults=lambda args, env: args,
    )
    env = SimpleNamespace(app_settings_file=settings_path, humanize_validation_errors=lambda exc: ["msg"])

    defaults_model, payload, _ = streamlit_args.load_args_state(
        env,
        args_module=args_module,
    )

    assert defaults_model.name == "SessionValue"
    assert payload["name"] == "SessionValue"


def test_load_args_state_handles_missing_settings_file(tmp_path, dummy_streamlit):
    settings_path = tmp_path / "missing.toml"
    args_module = SimpleNamespace(
        ArgsModel=DemoArgs,
        ensure_defaults=lambda args, env: args,
    )
    env = SimpleNamespace(app_settings_file=settings_path, humanize_validation_errors=lambda exc: ["msg"])

    defaults_model, payload, returned_path = streamlit_args.load_args_state(
        env,
        args_module=args_module,
    )

    assert returned_path == settings_path
    assert defaults_model.name == "Alice"
    assert payload["name"] == "Alice"


def test_load_args_state_warns_on_validation_error(tmp_path, dummy_streamlit):
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        '[args]\nchoice = "invalid"\n',
        encoding="utf-8",
    )

    args_module = SimpleNamespace(
        ArgsModel=DemoArgs,
        ensure_defaults=lambda args, env: args,
    )
    env = SimpleNamespace(
        app_settings_file=settings_path,
        humanize_validation_errors=lambda exc: ["bad config"],
    )

    defaults_model, payload, _ = streamlit_args.load_args_state(
        env,
        args_module=args_module,
    )

    assert defaults_model.choice == "beta"
    assert "bad config" in dummy_streamlit.warning_messages[0]
    assert "please check" in dummy_streamlit.warning_messages[0]
    assert "is_args_from_ui" not in dummy_streamlit.session_state


def test_resolve_shared_path_handles_absolute_and_relative(tmp_path):
    share_root = tmp_path / "share"
    env = SimpleNamespace(share_root_path=lambda: share_root)
    absolute = (tmp_path / "absolute").resolve()

    resolved_abs = streamlit_args.resolve_shared_path(env, absolute)
    resolved_rel = streamlit_args.resolve_shared_path(env, "nested/path")

    assert resolved_abs == absolute
    assert resolved_rel == share_root / "nested/path"


def test_ensure_shared_directory_create_and_no_create_paths(tmp_path, monkeypatch):
    share_root = tmp_path / "share"
    env = SimpleNamespace(share_root_path=lambda: share_root)
    existing = share_root / "existing"
    existing.mkdir(parents=True)

    target, created, error = streamlit_args.ensure_shared_directory(env, existing)
    assert target == existing
    assert created is False
    assert error is None

    target, created, error = streamlit_args.ensure_shared_directory(env, "created/folder")
    assert target.is_dir()
    assert created is True
    assert error is None

    monkeypatch.setattr(streamlit_args, "diagnose_data_directory", lambda _path: None)
    target, created, error = streamlit_args.ensure_shared_directory(
        env,
        "missing/folder",
        description="payload path",
        create_missing=False,
    )
    assert target == share_root / "missing/folder"
    assert created is False
    assert "payload path" in error
    assert "not a directory" in error


def test_ensure_shared_directory_reports_mkdir_failure(tmp_path, monkeypatch):
    share_root = tmp_path / "share"
    env = SimpleNamespace(share_root_path=lambda: share_root)
    target = share_root / "blocked"

    monkeypatch.setattr(streamlit_args, "resolve_shared_path", lambda *_args, **_kwargs: target)
    monkeypatch.setattr(streamlit_args, "diagnose_data_directory", lambda _path: "diagnosis")

    original_mkdir = Path.mkdir

    def raising_mkdir(self, *args, **kwargs):
        if self == target:
            raise OSError("permission denied")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", raising_mkdir)
    resolved, created, error = streamlit_args.ensure_shared_directory(env, "blocked")
    assert resolved == target
    assert created is False
    assert error == "diagnosis"


def test_persist_args_writes_when_changed(tmp_path, dummy_streamlit):
    settings_path = tmp_path / "app_settings.toml"
    dummy_streamlit.session_state.app_settings = {"args": DemoArgs().model_dump(mode="json")}

    calls: list[tuple] = []

    def dump_args(model, output_path, section="args"):
        calls.append((model, output_path, section))

    args_module = SimpleNamespace(
        dump_args=dump_args,
    )

    updated = DemoArgs(name="Charlie")
    defaults_payload = DemoArgs().model_dump(mode="json")

    streamlit_args.persist_args(
        args_module,
        updated,
        settings_path=settings_path,
        defaults_payload=defaults_payload,
    )

    assert calls and calls[0][1] == settings_path
    assert dummy_streamlit.session_state["app_settings"]["args"]["name"] == "Charlie"
    assert dummy_streamlit.session_state.is_args_from_ui is True


def test_persist_args_unchanged_payload_noop_and_sets_args_project(tmp_path, dummy_streamlit):
    settings_path = tmp_path / "app_settings.toml"
    defaults_payload = DemoArgs().model_dump(mode="json")
    dummy_streamlit.session_state.app_settings = {"args": defaults_payload.copy()}

    calls: list[tuple] = []

    def dump_args(model, output_path, section="args"):
        calls.append((model, output_path, section))

    args_module = SimpleNamespace(dump_args=dump_args)

    streamlit_args.persist_args(
        args_module,
        DemoArgs(),
        settings_path=settings_path,
        defaults_payload=defaults_payload,
    )
    assert calls == []
    assert "is_args_from_ui" not in dummy_streamlit.session_state

    dummy_streamlit.session_state["env"] = SimpleNamespace(app="demo-project")
    updated = DemoArgs(name="Delta")
    streamlit_args.persist_args(
        args_module,
        updated,
        settings_path=settings_path,
        defaults_payload=defaults_payload,
    )
    assert dummy_streamlit.session_state["args_project"] == "demo-project"
