"""Import discovery fails closed on interrupted filesystem observations."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_env.runtime import import_layout_support as layout


def _fail_path_method(monkeypatch, name, target):
    original = getattr(Path, name)
    def fail(path, *args, **kwargs):
        if path == target:
            raise OSError("filesystem observation denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, name, fail)


def test_pth_root_with_failed_directory_probe_is_not_exposed(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (tmp_path / "source.pth").write_text(str(source))
    _fail_path_method(monkeypatch, "is_dir", source)
    assert layout.inspect_pth_import_layout(tmp_path).roots == ()


def test_top_level_distribution_scan_cannot_claim_unreadable_metadata(tmp_path, monkeypatch):
    _fail_path_method(monkeypatch, "glob", tmp_path)
    assert layout.top_level_modules_from_distribution([tmp_path], "demo") == ()


@pytest.mark.parametrize("kind", ["directory", "outside", "missing"])
def test_editable_finder_must_be_existing_confined_file(tmp_path, kind):
    site = tmp_path / "site"
    site.mkdir()
    finder = site / "finder.py"
    if kind == "directory":
        finder.mkdir()
    elif kind == "outside":
        outside = tmp_path / "outside.py"
        outside.write_text("raise AssertionError('never execute')")
        finder.symlink_to(outside)
    assert layout._finder_path(site, "finder") is None


@pytest.mark.parametrize("suffix", [".cpython-313-special.so", ".cp313-special.pyd"])
def test_import_location_accepts_existing_abi_suffixed_extension_without_import(tmp_path, suffix):
    (tmp_path / ("native" + suffix)).write_bytes(b"non-executable fixture")
    assert layout._import_location("native", tmp_path) == tmp_path / "native"


def test_import_location_probe_error_cannot_claim_package(tmp_path, monkeypatch):
    _fail_path_method(monkeypatch, "is_file", tmp_path / "module" / "__init__.py")
    assert layout._import_location("module", tmp_path) is None


def test_site_package_enumeration_failure_selects_no_python_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(layout, "os", SimpleNamespace(name="posix"))
    _fail_path_method(monkeypatch, "glob", tmp_path / "lib")
    assert layout._active_venv_site_package_dirs(tmp_path, (3, 13)) == ()


@pytest.mark.parametrize("phase", ["glob", "is_dir"])
def test_editable_project_owner_requires_readable_directory(tmp_path, monkeypatch, phase):
    project = tmp_path / "project"
    project.mkdir()
    metadata = tmp_path / "demo.dist-info"
    metadata.mkdir()
    (metadata / "direct_url.json").write_text(json.dumps({
        "url": project.as_uri(), "dir_info": {"editable": True}
    }))
    _fail_path_method(monkeypatch, phase, tmp_path if phase == "glob" else project)
    assert layout._editable_project_roots(tmp_path) == ()


@pytest.mark.parametrize("phase", ["source", "root"])
def test_structural_source_root_requires_observable_directory_identity(tmp_path, monkeypatch, phase):
    package = tmp_path / "package"
    package.mkdir()
    _fail_path_method(monkeypatch, "is_dir", package if phase == "source" else tmp_path)
    assert layout._structural_source_import_root("package", package) is None


def test_native_scan_rechecks_directory_identity_after_resolving_root(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    resolve = Path.resolve
    def resolved(path, *args, **kwargs):
        if path == tmp_path:
            return root
        return resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolved)
    _fail_path_method(monkeypatch, "stat", root)
    assert layout._root_contains_native_code(tmp_path) is True


def test_record_metadata_read_failure_cannot_invent_top_level_modules(tmp_path, monkeypatch):
    _fail_path_method(monkeypatch, "read_text", tmp_path / "RECORD")
    assert layout._top_level_modules_from_metadata_dir(tmp_path) == ()


def test_hosted_mapping_with_unowned_location_is_not_exposed(tmp_path, monkeypatch):
    owner = tmp_path / "owner"
    owner.mkdir()
    foreign = tmp_path / "foreign" / "package"
    foreign.mkdir(parents=True)
    monkeypatch.setattr(layout, "_active_venv_site_package_dirs", lambda *_: (tmp_path,))
    monkeypatch.setattr(layout, "_editable_project_roots", lambda _: (owner,))
    monkeypatch.setattr(layout, "inspect_pth_import_layout", lambda _: layout.PthImportLayout(
        roots=(), module_locations=(("package", foreign),)
    ))
    assert layout.hosted_editable_source_import_roots(tmp_path) == ()
