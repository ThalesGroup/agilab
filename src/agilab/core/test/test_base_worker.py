from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agi_node.agi_dispatcher import BaseWorker


class DummyWorker(BaseWorker):
    def __init__(self):
        super().__init__()
        worker_id = 0
        BaseWorker._worker_id = worker_id
        BaseWorker._insts = {worker_id: self}

    def works(self, *_args, **_kwargs):
        pass


def teardown_function(_fn):
    BaseWorker._worker_id = None
    BaseWorker._insts = {}
    BaseWorker._env = None
    BaseWorker.env = None


def test_baseworker_do_works_executes_tasks():
    dummy = DummyWorker()
    with patch.object(dummy, "works", return_value=None) as mocked:
        BaseWorker._do_works({}, {})
    mocked.assert_called_once()


def test_prepare_output_dir_creates_directory(tmp_path):
    worker = DummyWorker()
    target = worker.prepare_output_dir(tmp_path, subdir="payload", attribute="custom_attr", clean=True)

    assert target.exists()
    assert target.name == "payload"
    assert worker.custom_attr == target


def test_setup_args_requires_args():
    worker = DummyWorker()
    with pytest.raises(ValueError):
        worker.setup_args(None)


def test_setup_args_applies_defaults_and_creates_output(tmp_path):
    class ConfigWorker(BaseWorker):
        args_ensure_defaults = staticmethod(lambda args, env=None: SimpleNamespace(**{**vars(args), "extra": "value"}))
        managed_pc_path_fields = ("data_path",)

    worker = ConfigWorker()
    args = SimpleNamespace(data_path=tmp_path / "data")

    processed = worker.setup_args(
        args,
        output_field="data_path",
        output_subdir="frames",
        output_attr="output_dir",
    )

    assert processed.extra == "value"
    assert worker.output_dir.exists()
    assert worker.output_dir.name == "frames"


def test_remap_managed_pc_path_when_managed():
    home = Path.home()
    sample = home / "dataset" / "file.csv"
    env = SimpleNamespace(_is_managed_pc=True)

    remapped = BaseWorker._remap_managed_pc_path(sample, env=env)

    expected_root = home / BaseWorker.managed_pc_home_suffix
    assert str(remapped).startswith(str(expected_root))


def test_apply_managed_pc_path_overrides():
    class OverrideWorker(BaseWorker):
        managed_pc_path_fields = ("payload",)

    env = SimpleNamespace(_is_managed_pc=True)
    path = Path.home() / "payload"
    args = SimpleNamespace(payload=path)

    result = OverrideWorker._apply_managed_pc_path_overrides(args, env=env)

    assert isinstance(result.payload, Path)
    assert str(result.payload).startswith(str(Path.home() / OverrideWorker.managed_pc_home_suffix))
