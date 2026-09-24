"""Dependency metadata used to diagnose orchestration runtime imports."""

from pathlib import Path

import pytest

from agilab.orchestrate import orchestrate_page_support as support


@pytest.mark.parametrize(
    "record,expected",
    [
        ("", None),
        ("demo.dist-info/METADATA,,", None),
        ("demo.egg-info/PKG-INFO,,", None),
        ("demo.data/scripts/run,,", None),
        ("module.py,sha256=x,20", "module"),
        ("native.cpython-313-darwin.so,,", "native"),
        ("native.cp313-win_amd64.pyd,,", "native"),
        ("native.dylib,,", "native"),
        ("docs.html,,", None),
        ("package/submodule.py,,", "package"),
        ("package\\submodule.py,,", "package"),
        ("../outside.py,,", None),
        ("bad-name/file.py,,", None),
    ],
)
def test_record_import_names_filter_metadata_and_non_python_assets(record, expected):
    assert support._module_name_from_record_path(record) == expected


def test_top_level_metadata_prefers_valid_declared_modules(tmp_path):
    metadata = tmp_path / "demo.dist-info"
    metadata.mkdir()
    (metadata / "top_level.txt").write_text(
        "# generated\n\ndemo\nbad-name\ndemo\nother\n"
    )
    (metadata / "RECORD").write_text("unrelated/__init__.py,,\n")
    assert support._top_level_modules_from_metadata_dir(metadata) == ("demo", "other")


@pytest.mark.parametrize("top_level", [None, "# comment\nbad-name\n"])
def test_top_level_metadata_falls_back_to_record_and_deduplicates(tmp_path, top_level):
    metadata = tmp_path / "demo.dist-info"
    metadata.mkdir()
    if top_level is not None:
        (metadata / "top_level.txt").write_text(top_level)
    (metadata / "RECORD").write_text(
        "demo/__init__.py,,\ndemo/core.py,,\nnative.abi3.so,,\n"
        "standalone.py,,\ndemo.dist-info/METADATA,,\n"
    )
    assert support._top_level_modules_from_metadata_dir(metadata) == (
        "demo",
        "native",
        "standalone",
    )


def test_missing_metadata_is_reported_without_inventing_import_name(tmp_path):
    assert (
        support._top_level_modules_from_metadata_dir(tmp_path / "missing.dist-info")
        == ()
    )


@pytest.mark.parametrize(
    "content",
    [
        "[project",
        'project = "invalid"',
        '[project]\nname = "demo"\n',
        '[project]\ndependencies = "numpy"\n',
    ],
)
def test_invalid_project_metadata_does_not_invent_dependency_imports(tmp_path, content):
    (tmp_path / "pyproject.toml").write_text(content)
    assert support._dependency_modules_from_pyproject(tmp_path) == ()


def test_project_dependency_markers_and_extras_produce_runtime_import_set(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\ndependencies = [\n"
        '  "dask[distributed]>=2024",\n'
        '  "scikit-learn",\n'
        "  \"numpy; sys_platform == 'win32'\",\n"
        '  "agi-env",\n'
        '  "types-requests",\n'
        "  123,\n]\n"
    )
    actual = support._dependency_modules_from_pyproject(
        tmp_path, marker_environment={"sys_platform": "linux"}
    )
    assert actual == ("dask", "distributed", "sklearn")


def test_disappearing_metadata_after_name_read_is_ignored(tmp_path, monkeypatch):
    metadata = tmp_path / "demo.dist-info/METADATA"
    metadata.parent.mkdir()
    metadata.write_text("Name: demo\nRequires-Dist: numpy\n")
    original = Path.read_text
    reads = 0

    def read(path, *args, **kwargs):
        nonlocal reads
        if path == metadata:
            reads += 1
            if reads > 1:
                raise FileNotFoundError("package removed during inspection")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert support._dependency_modules_from_metadata([tmp_path], ["demo"]) == ()
