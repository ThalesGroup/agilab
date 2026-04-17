from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/sync_docs_source.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_docs_source_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_manifest_ignores_junk_files(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    (source / "guide.rst").parent.mkdir(parents=True)
    (source / "guide.rst").write_text("hello\n", encoding="utf-8")
    (source / ".DS_Store").write_text("junk\n", encoding="utf-8")
    (source / "__pycache__" / "ignored.pyc").parent.mkdir(parents=True)
    (source / "__pycache__" / "ignored.pyc").write_bytes(b"x")

    manifest = module.build_manifest(source)

    assert manifest == {"guide.rst": source / "guide.rst"}


def test_make_sync_plan_reports_create_update_and_delete(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "same.rst").parent.mkdir(parents=True)
    (target / "same.rst").parent.mkdir(parents=True)
    (source / "same.rst").write_text("same\n", encoding="utf-8")
    (target / "same.rst").write_text("same\n", encoding="utf-8")
    (source / "new.rst").write_text("new\n", encoding="utf-8")
    (source / "changed.rst").write_text("source\n", encoding="utf-8")
    (target / "changed.rst").write_text("target\n", encoding="utf-8")
    (target / "extra.rst").write_text("extra\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)

    assert plan.created == ["new.rst"]
    assert plan.updated == ["changed.rst"]
    assert plan.deleted == ["extra.rst"]


def test_apply_sync_plan_copies_and_deletes(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "nested" / "guide.rst").parent.mkdir(parents=True)
    (target / "stale.rst").parent.mkdir(parents=True)
    (source / "nested" / "guide.rst").write_text("guide\n", encoding="utf-8")
    (target / "nested" / "guide.rst").parent.mkdir(parents=True, exist_ok=True)
    (target / "nested" / "guide.rst").write_text("old\n", encoding="utf-8")
    (target / "stale.rst").write_text("stale\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)
    module.apply_sync_plan(source, target, plan)

    assert (target / "nested" / "guide.rst").read_text(encoding="utf-8") == "guide\n"
    assert not (target / "stale.rst").exists()


def test_make_sync_plan_normalizes_unicode_relative_paths(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    source_name = "TP Prompt Ingénierie.pptx"
    target_name = "TP Prompt Inge\u0301nierie.pptx"
    (source / source_name).write_text("same\n", encoding="utf-8")
    (target / target_name).write_text("same\n", encoding="utf-8")

    plan = module.make_sync_plan(source, target, delete_extra=True)

    assert not plan.has_changes()


def test_main_check_and_apply_modes(tmp_path: Path, capsys) -> None:
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "guide.rst").write_text("guide\n", encoding="utf-8")

    exit_code = module.main(["--source", str(source), "--target", str(target), "--check"])

    assert exit_code == 1
    assert "create: 1" in capsys.readouterr().out

    exit_code = module.main(["--source", str(source), "--target", str(target), "--apply"])

    assert exit_code == 0
    assert (target / "guide.rst").read_text(encoding="utf-8") == "guide\n"
