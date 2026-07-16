import builtins
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import agi_env.app_args as app_args_module
import agi_env.runtime.atomic_write_support as atomic_write_module
import tomllib
import pytest
from pydantic import BaseModel

from agi_env.app_args import (
    dump_model_to_toml,
    load_model_from_toml,
    merge_model_data,
    model_to_payload,
    prefer_persisted_value,
)
from agi_env.runtime.atomic_write_support import (
    atomic_write_bytes,
    run_with_windows_file_sharing_retry,
)


class ExampleModel(BaseModel):
    foo: int = 1
    bar: str = "baz"


_MODEL_WRITER = """
import sys
import time
from pathlib import Path

from pydantic import BaseModel

from agi_env.app_args import dump_model_to_toml


class Model(BaseModel):
    foo: int
    bar: str


settings = Path(sys.argv[1])
section = sys.argv[2]
offset = int(sys.argv[3])
start = Path(sys.argv[4])
deadline = time.monotonic() + 10
while not start.exists():
    if time.monotonic() >= deadline:
        raise TimeoutError("writer start signal was not created")
    time.sleep(0.001)
for index in range(20):
    dump_model_to_toml(
        Model(foo=offset + index, bar=section),
        settings,
        section=section,
    )
    time.sleep(0.002)
"""


def test_model_to_payload_round_trip():
    model = ExampleModel(foo=3, bar="qux")
    payload = model_to_payload(model)
    assert payload == {"foo": 3, "bar": "qux"}


def test_prefer_persisted_value_preserves_explicit_values():
    assert prefer_persisted_value("saved", "fallback") == "saved"
    assert prefer_persisted_value(Path("saved"), Path("fallback")) == Path("saved")
    assert prefer_persisted_value(0, 1) == 0
    assert prefer_persisted_value(None, "fallback") == "fallback"
    assert prefer_persisted_value("", "fallback") == "fallback"
    assert prefer_persisted_value(False, "fallback") == "fallback"


def test_merge_model_data_applies_overrides_without_mutating_original():
    original = ExampleModel(foo=1, bar="orig")
    updated = merge_model_data(original, {"bar": "changed"})

    assert updated.bar == "changed"
    assert updated.foo == 1
    assert original.bar == "orig"


def test_merge_model_data_without_overrides_returns_copy():
    original = ExampleModel(foo=4, bar="same")

    updated = merge_model_data(original, {})

    assert updated == original
    assert updated is not original


def test_load_model_from_toml_reads_existing_section(tmp_path: Path):
    settings = tmp_path / "config.toml"
    settings.write_text(
        """
[args]
foo = 10
bar = "from_toml"
""".strip()
    )

    model = load_model_from_toml(ExampleModel, settings)
    assert model.foo == 10
    assert model.bar == "from_toml"


def test_load_model_from_toml_returns_defaults_when_missing(tmp_path: Path):
    settings = tmp_path / "missing.toml"
    model = load_model_from_toml(ExampleModel, settings)
    assert model == ExampleModel()


def test_load_model_from_toml_returns_defaults_when_section_is_absent(tmp_path: Path):
    settings = tmp_path / "config.toml"
    settings.write_text(
        """
[other]
foo = 10
""".strip()
    )

    model = load_model_from_toml(ExampleModel, settings)

    assert model == ExampleModel()


def test_load_model_from_toml_raises_on_invalid_payload(tmp_path: Path):
    settings = tmp_path / "invalid.toml"
    settings.write_text(
        """
[args]
foo = "bad"
""".strip()
    )

    with pytest.raises(ValueError):
        load_model_from_toml(ExampleModel, settings)


def test_dump_model_to_toml_creates_file_and_section(tmp_path: Path):
    settings = tmp_path / "config.toml"
    model = ExampleModel(foo=7, bar="written")

    dump_model_to_toml(model, settings)

    data = tomllib.loads(settings.read_text())
    assert data["__meta__"] == {"schema": "agilab.app_settings.v1", "version": 1}
    assert data["args"] == {"foo": 7, "bar": "written"}


def test_dump_model_to_toml_preserves_disjoint_multiprocess_updates_and_parseability(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "config.toml"
    start = tmp_path / "start"
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _MODEL_WRITER,
                str(settings),
                section,
                str(offset),
                str(start),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for section, offset in (("alpha", 100), ("beta", 200))
    ]
    start.touch()
    while any(process.poll() is None for process in processes):
        if settings.exists():
            load_model_from_toml(ExampleModel, settings, section="alpha")
            load_model_from_toml(ExampleModel, settings, section="beta")
        time.sleep(0.001)
    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"

    payload = tomllib.loads(settings.read_text(encoding="utf-8"))
    assert payload["alpha"] == {"foo": 119, "bar": "alpha"}
    assert payload["beta"] == {"foo": 219, "bar": "beta"}


def test_dump_model_to_toml_rolls_back_serialization_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "config.toml"
    settings.write_text("[preserved]\nvalue = 1\n", encoding="utf-8")

    def failing_atomic(path, writer):
        def write_then_fail(handle):
            writer(handle)
            raise OSError("simulated write failure")

        return atomic_write_bytes(path, write_then_fail)

    monkeypatch.setattr(app_args_module, "atomic_write_bytes", failing_atomic)
    with pytest.raises(OSError, match="simulated write failure"):
        dump_model_to_toml(ExampleModel(), settings)

    assert settings.read_text(encoding="utf-8") == "[preserved]\nvalue = 1\n"


def test_atomic_write_bytes_preserves_existing_file_on_writer_failure(tmp_path: Path):
    settings = tmp_path / "config.toml"
    settings.write_text("original", encoding="utf-8")

    def _broken_writer(handle):
        handle.write(b"partial")
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        atomic_write_bytes(settings, _broken_writer)

    assert settings.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob(".config.toml.*.tmp")) == []


def test_windows_file_sharing_retry_eventually_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def _transient_operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("sharing violation")
        return "published"

    monkeypatch.setattr(atomic_write_module, "_is_windows", lambda: True)
    monkeypatch.setattr(atomic_write_module.time, "sleep", sleeps.append)

    assert run_with_windows_file_sharing_retry(_transient_operation) == "published"
    assert attempts == 2
    assert len(sleeps) == 1


def test_windows_file_sharing_retry_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def _locked_operation() -> None:
        nonlocal attempts
        attempts += 1
        raise PermissionError("sharing violation")

    monkeypatch.setattr(atomic_write_module, "_is_windows", lambda: True)

    with pytest.raises(PermissionError, match="sharing violation"):
        run_with_windows_file_sharing_retry(
            _locked_operation,
            timeout_seconds=0,
        )

    assert attempts == 1


def test_file_sharing_retry_reraises_immediately_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def _locked_operation() -> None:
        nonlocal attempts
        attempts += 1
        raise PermissionError("permission denied")

    monkeypatch.setattr(atomic_write_module, "_is_windows", lambda: False)

    with pytest.raises(PermissionError, match="permission denied"):
        run_with_windows_file_sharing_retry(_locked_operation)

    assert attempts == 1


def test_load_model_from_toml_retries_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "config.toml"
    settings.write_text('[args]\nfoo = 8\nbar = "ready"\n', encoding="utf-8")
    original_read_text = Path.read_text
    attempts = 0

    def _transient_read_text(path: Path, *args, **kwargs):
        nonlocal attempts
        if path == settings:
            attempts += 1
            if attempts == 1:
                raise PermissionError("sharing violation")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(atomic_write_module, "_is_windows", lambda: True)
    monkeypatch.setattr(atomic_write_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(Path, "read_text", _transient_read_text)

    assert load_model_from_toml(ExampleModel, settings) == ExampleModel(
        foo=8,
        bar="ready",
    )
    assert attempts == 2


def test_atomic_write_bytes_retries_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "config.toml"
    original_replace = atomic_write_module.os.replace
    attempts = 0

    def _transient_replace(source, destination) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("sharing violation")
        original_replace(source, destination)

    monkeypatch.setattr(atomic_write_module, "_is_windows", lambda: True)
    monkeypatch.setattr(atomic_write_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(atomic_write_module.os, "replace", _transient_replace)

    atomic_write_bytes(settings, lambda handle: handle.write(b"complete"))

    assert settings.read_bytes() == b"complete"
    assert attempts == 2


def test_dump_model_to_toml_respects_create_missing_flag(tmp_path: Path):
    settings = tmp_path / "config.toml"
    model = ExampleModel()

    with pytest.raises(FileNotFoundError):
        dump_model_to_toml(model, settings, create_missing=False)

    dump_model_to_toml(model, settings)
    dump_model_to_toml(model, settings, create_missing=False)


def test_dump_model_to_toml_rejects_future_app_settings_contract(tmp_path: Path):
    settings = tmp_path / "config.toml"
    settings.write_text("[__meta__]\nversion = 999\n", encoding="utf-8")

    with pytest.raises(
        ValueError, match="Unsupported app_settings.toml schema version 999"
    ):
        dump_model_to_toml(ExampleModel(), settings)


def test_dump_model_to_toml_falls_back_to_tomlkit_when_tomli_w_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = tmp_path / "config.toml"
    model = ExampleModel(foo=9, bar="tomlkit")
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tomli_w":
            err = ModuleNotFoundError("missing tomli_w")
            err.name = "tomli_w"
            raise err
        if name == "tomlkit":
            return SimpleNamespace(
                dumps=lambda data: '[args]\nfoo = 9\nbar = "tomlkit"\n'
            )
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    dump_model_to_toml(model, settings)

    data = tomllib.loads(settings.read_text())
    assert data["args"] == {"foo": 9, "bar": "tomlkit"}


def test_dump_model_to_toml_raises_when_no_supported_writer_is_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = tmp_path / "config.toml"
    model = ExampleModel()
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tomli_w":
            err = ModuleNotFoundError("missing tomli_w")
            err.name = "tomli_w"
            raise err
        if name == "tomlkit":
            err = ModuleNotFoundError("missing tomlkit")
            err.name = "tomlkit"
            raise err
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="either 'tomli-w' or 'tomlkit'"):
        dump_model_to_toml(model, settings)


def test_dump_model_to_toml_propagates_broken_writer_dependency_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = tmp_path / "config.toml"
    model = ExampleModel()
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tomli_w":
            err = ModuleNotFoundError("missing nested dependency")
            err.name = "broken_dep"
            raise err
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ModuleNotFoundError, match="missing nested dependency"):
        dump_model_to_toml(model, settings)


def test_dump_model_to_toml_propagates_broken_tomlkit_dependency_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    settings = tmp_path / "config.toml"
    model = ExampleModel()
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tomli_w":
            err = ModuleNotFoundError("missing tomli_w")
            err.name = "tomli_w"
            raise err
        if name == "tomlkit":
            err = ModuleNotFoundError("missing nested dependency")
            err.name = "broken_dep"
            raise err
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ModuleNotFoundError, match="missing nested dependency"):
        dump_model_to_toml(model, settings)
