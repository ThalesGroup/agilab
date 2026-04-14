from pathlib import Path
from unittest import mock

import pytest

import agi_env.worker_source_support as worker_source_module


def test_get_base_classes_reads_worker_bases_and_reports_missing_file(tmp_path: Path):
    worker_file = tmp_path / "demo_worker.py"
    worker_file.write_text(
        "import pkg.module as mod\n"
        "from demo.worker import DemoWorker\n"
        "class Child(mod.OtherBase, DemoWorker):\n"
        "    pass\n",
        encoding="utf-8",
    )

    bases = worker_source_module.get_base_classes(worker_file, "Child")
    assert bases == [("OtherBase", "pkg.module"), ("DemoWorker", "demo.worker")]

    fake_logger = mock.Mock()
    assert worker_source_module.get_base_classes(tmp_path / "missing.py", "Child", logger=fake_logger) == []
    assert fake_logger.error.called


def test_get_base_classes_raises_runtime_error_on_syntax_error(tmp_path: Path):
    worker_file = tmp_path / "broken_worker.py"
    worker_file.write_text("class Broken(:\n", encoding="utf-8")
    fake_logger = mock.Mock()

    with pytest.raises(RuntimeError, match="Syntax error parsing"):
        worker_source_module.get_base_classes(worker_file, "Broken", logger=fake_logger)

    assert fake_logger.error.called


def test_get_base_worker_cls_picks_worker_base_and_returns_none_when_absent():
    bases = [("BaseThing", "demo.base"), ("DemoWorker", "demo.worker")]
    assert worker_source_module.get_base_worker_cls(
        "unused.py",
        "Child",
        get_base_classes_fn=lambda *_a, **_k: bases,
    ) == ("DemoWorker", "demo.worker")

    assert worker_source_module.get_base_worker_cls(
        "unused.py",
        "Child",
        get_base_classes_fn=lambda *_a, **_k: [("BaseThing", "demo.base")],
    ) == (None, None)
