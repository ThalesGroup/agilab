"""Manager behavior of the five packaged application templates."""

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src/agilab/apps/templates"
KINDS = ("pandas", "polars", "fireducks", "dag", "simple")


@pytest.fixture(params=KINDS)
def template(request, monkeypatch):
    kind = request.param
    package = kind + "_app"
    monkeypatch.syspath_prepend(str(ROOT / (package + "_template") / "src"))
    # Restore any previously loaded installed copy after this test.
    for name in tuple(sys.modules):
        if name == package or name.startswith(package + "."):
            monkeypatch.delitem(sys.modules, name)
    module = importlib.import_module(package + "." + package)
    cls = getattr(module, kind.capitalize() + "App")
    if kind != "simple":
        monkeypatch.setattr(module.WorkDispatcher, "args", {}, raising=False)
        monkeypatch.setattr(cls, "worker_vars", {})
    yield kind, module, cls
    for name in tuple(sys.modules):
        if name == package or name.startswith(package + "."):
            monkeypatch.delitem(sys.modules, name)


def test_template_initialization_resolves_data_and_ignores_unrelated_launch_options(
    template, tmp_path
):
    kind, module, cls = template
    data = tmp_path / "explicit-data"
    env = SimpleNamespace(
        _is_managed_pc=False,
        workflow_data_root=tmp_path,
        app_abs=tmp_path / "app",
        verbose=1,
    )
    key = "data_out" if kind == "simple" else "data_in"
    instance = cls(env, **{key: str(data), "verbose": "2", "launcher_only": "ignored"})
    assert instance.verbose == 2
    payload = instance.as_dict()
    assert payload[key] == str(data)
    assert "launcher_only" not in payload
    if kind != "simple":
        assert data.is_dir()
        assert payload["dir_path"] == str(data)
        assert module.WorkDispatcher.args == payload
        instance.pool_init({"factor": 3})
        assert cls.worker_vars == {"factor": 3}
    else:
        manifest = instance.run()
        assert manifest.parent == data
        assert (
            json.loads(manifest.read_text())["schema"]
            == "agilab.simple_app_template.manifest.v1"
        )


@pytest.mark.parametrize("override", [False, True])
def test_template_toml_roundtrip_preserves_other_sections_and_explicit_overrides(
    template, tmp_path, override
):
    kind, _, cls = template
    key = "data_out" if kind == "simple" else "data_in"
    source = tmp_path / "settings.toml"
    original_data = tmp_path / "original"
    target_data = tmp_path / "override"
    source.write_text(
        '[unrelated]\nname = "preserve"\n[args]\n'
        + key
        + ' = "'
        + str(original_data)
        + '"\n'
    )
    env = SimpleNamespace(
        _is_managed_pc=False,
        workflow_data_root=tmp_path,
        app_abs=tmp_path / "app",
        verbose=0,
    )
    instance = cls.from_toml(
        env, source, **({key: str(target_data)} if override else {})
    )
    expected = target_data if override else original_data
    assert instance.as_dict()[key] == str(expected)
    instance.to_toml(source)
    restored = cls.from_toml(env, source)
    assert restored.as_dict() == instance.as_dict()
    import tomllib

    assert tomllib.loads(source.read_text())["unrelated"] == {"name": "preserve"}


def test_template_to_toml_missing_parent_policy(template, tmp_path):
    kind, _, cls = template
    key = "data_out" if kind == "simple" else "data_in"
    instance = cls(
        SimpleNamespace(
            _is_managed_pc=False,
            workflow_data_root=tmp_path,
            app_abs=tmp_path / "app",
            verbose=0,
        ),
        **{key: str(tmp_path / "data")},
    )
    destination = tmp_path / "missing" / "settings.toml"
    with pytest.raises(FileNotFoundError):
        instance.to_toml(destination, create_missing=False)
    assert not destination.exists()


@pytest.mark.parametrize("kind", ["pandas", "polars", "fireducks"])
def test_frame_template_existing_dataset_is_not_reseeded(kind, monkeypatch, tmp_path):
    package = kind + "_app"
    monkeypatch.syspath_prepend(str(ROOT / (package + "_template") / "src"))
    module = importlib.import_module(package + "." + package)
    cls = getattr(module, kind.capitalize() + "App")
    root = tmp_path / "app"
    root.mkdir()
    (root / "data.7z").write_bytes(b"invalid archive must not be opened")
    data = tmp_path / "data"
    data.mkdir()
    (data / "owned.csv").write_text("x\n9\n")
    cls._ensure_dataset(object(), data, app_root=root)
    assert (data / "owned.csv").read_text() == "x\n9\n"
    assert (
        cls._app_root(
            SimpleNamespace(
                _is_managed_pc=False, workflow_data_root=tmp_path, app_abs=root
            )
        )
        == root
    )
    assert cls._app_root(SimpleNamespace()) == ROOT / (package + "_template")


@pytest.mark.parametrize("resolver", [False, True])
def test_simple_template_relative_output_uses_available_share_resolver(
    monkeypatch, tmp_path, resolver
):
    monkeypatch.syspath_prepend(str(ROOT / "simple_app_template/src"))
    module = importlib.import_module("simple_app.simple_app")
    env = SimpleNamespace()
    if resolver:
        env.resolve_share_path = lambda path: tmp_path / path
    expected = tmp_path / "output" if resolver else Path("output")
    assert module.SimpleApp._resolve_output_path(env, Path("output")) == expected
    absolute = tmp_path / "absolute"
    assert module.SimpleApp._resolve_output_path(env, absolute) == absolute


@pytest.mark.parametrize("kind", ["pandas", "polars", "fireducks"])
@pytest.mark.parametrize("verbose", [0, 1])
def test_frame_template_stop_delegates_once_and_logs_when_requested(
    kind, verbose, monkeypatch, caplog
):
    import logging

    package = kind + "_app"
    monkeypatch.syspath_prepend(str(ROOT / (package + "_template") / "src"))
    module = importlib.import_module(package + "." + package)
    cls = getattr(module, kind.capitalize() + "App")
    instance = object.__new__(cls)
    instance.verbose = verbose
    stopped = []
    monkeypatch.setattr(
        module.BaseWorker, "stop", lambda worker: stopped.append(worker)
    )
    with caplog.at_level(logging.INFO, logger=module.__name__):
        instance.stop()
    assert stopped == [instance]
    assert ("finished" in caplog.text) is bool(verbose)
