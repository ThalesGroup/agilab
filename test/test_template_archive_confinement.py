from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_ROOT = REPO_ROOT / "src" / "agilab" / "apps" / "templates"
TEMPLATE_CASES = [
    ("pandas_app_template", "pandas_app.pandas_app", "PandasApp"),
    ("polars_app_template", "polars_app.polars_app", "PolarsApp"),
    ("fireducks_app_template", "fireducks_app.fireducks_app", "FireducksApp"),
]


def _load_template_app(monkeypatch, template: str, module_name: str, class_name: str):
    monkeypatch.syspath_prepend(str(TEMPLATES_ROOT / template / "src"))
    module = importlib.import_module(module_name)
    return module, getattr(module, class_name)


@pytest.mark.parametrize(("template", "module_name", "class_name"), TEMPLATE_CASES)
def test_template_dataset_extraction_rejects_archive_escape(
    tmp_path,
    monkeypatch,
    template,
    module_name,
    class_name,
):
    module, app_class = _load_template_app(
        monkeypatch,
        template,
        module_name,
        class_name,
    )
    app_root = tmp_path / template
    app_root.mkdir()
    (app_root / "data.7z").write_bytes(b"test archive placeholder")
    data_in = tmp_path / "share" / "dataset"
    extracted = False

    class _UnsafeArchive:
        def __init__(self, _path, *, mode):
            assert mode == "r"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def getnames():
            return ["../outside.txt"]

        def extractall(self, *, path):
            nonlocal extracted
            extracted = True
            (path.parent / "outside.txt").write_text("escaped", encoding="utf-8")

    monkeypatch.setattr(module.py7zr, "SevenZipFile", _UnsafeArchive)

    with pytest.raises(RuntimeError, match="Unsafe archive member path"):
        app_class._ensure_dataset(object(), data_in, app_root=app_root)

    assert extracted is False
    assert not (data_in.parent / "outside.txt").exists()


@pytest.mark.parametrize(("template", "module_name", "class_name"), TEMPLATE_CASES)
def test_template_dataset_extraction_keeps_safe_archive_behavior(
    tmp_path,
    monkeypatch,
    template,
    module_name,
    class_name,
):
    module, app_class = _load_template_app(
        monkeypatch,
        template,
        module_name,
        class_name,
    )
    app_root = tmp_path / template
    app_root.mkdir()
    (app_root / "data.7z").write_bytes(b"test archive placeholder")
    data_in = tmp_path / "share" / "dataset"

    class _SafeArchive:
        def __init__(self, _path, *, mode):
            assert mode == "r"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def getnames():
            return ["dataset/sample.csv"]

        @staticmethod
        def extractall(*, path):
            output = path / "dataset" / "sample.csv"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("value\n1\n", encoding="utf-8")

    monkeypatch.setattr(module.py7zr, "SevenZipFile", _SafeArchive)

    app_class._ensure_dataset(object(), data_in, app_root=app_root)

    assert (data_in / "dataset" / "sample.csv").read_text(
        encoding="utf-8"
    ) == "value\n1\n"
