"""Fail-closed import layout inspection under filesystem and metadata pollution."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_env.runtime import import_layout_support as layout


@pytest.mark.parametrize("text,expected", [
    ("version = 3.13.1\n", (3, 13)), ("version_info = 3.14.0.final.0\n", (3, 14)),
    ("other = 3.12\nversion = invalid\n", None), ("version without separator\n", None),
])
def test_manager_python_version_requires_supported_config_field(tmp_path, text, expected):
    (tmp_path / "pyvenv.cfg").write_text(text)
    assert layout._venv_python_version(tmp_path) == expected


@pytest.mark.parametrize("directories,version,expected", [
    ([], None, []), (["python3.13"], None, ["python3.13"]),
    (["python3.13", "python3.14"], None, []),
    (["python3.13", "python3.14"], (3, 13), ["python3.13"]),
    (["python3.13", "python3.13t"], (3, 13), []),
    (["python3.13t"], (3, 13), ["python3.13t"]),
    (["python3.14"], (3, 13), []),
])
def test_ambiguous_manager_site_packages_never_selects_arbitrary_python(monkeypatch, tmp_path, directories, version, expected):
    monkeypatch.setattr(layout, "os", SimpleNamespace(name="posix"))
    for name in directories:
        (tmp_path / "lib" / name / "site-packages").mkdir(parents=True)
    result = layout._active_venv_site_package_dirs(tmp_path, version)
    assert [path.parent.name for path in result] == expected


@pytest.mark.parametrize("exists", [False, True])
def test_windows_site_packages_location_is_explicit(monkeypatch, tmp_path, exists):
    monkeypatch.setattr(layout, "os", SimpleNamespace(name="nt"))
    target = tmp_path / "Lib" / "site-packages"
    if exists:
        target.mkdir(parents=True)
    assert layout._active_venv_site_package_dirs(tmp_path, (3, 13)) == ((target,) if exists else ())


@pytest.mark.parametrize("payload", [[], {"url": None}, {"url": "https://example.com/source"},
                                    {"url": "file://"}, {"url": "file:///tmp/project", "dir_info": []},
                                    {"url": "file:///tmp/project", "dir_info": {"editable": 1}}])
def test_direct_url_requires_literal_editable_local_project(tmp_path, payload):
    path = tmp_path / "direct_url.json"
    path.write_text(json.dumps(payload))
    assert layout._direct_url_project(path, editable_only=True) is None


def test_direct_url_non_editable_file_is_allowed_only_without_editable_requirement(tmp_path):
    path = tmp_path / "direct_url.json"
    project = tmp_path / "project with spaces"
    path.write_text(json.dumps({"url": project.as_uri(), "dir_info": {"editable": False}}))
    assert layout._direct_url_project(path) == project.resolve()
    assert layout._direct_url_project(path, editable_only=True) is None


@pytest.mark.parametrize("module,filename,expected", [
    ("module", "module", True), ("package.module", "package/module", True),
    ("aliased", "module", False), ("bad-name", "bad-name", False), ("", "module", False),
])
def test_structural_mapping_requires_module_path_identity(tmp_path, module, filename, expected):
    candidate = tmp_path / filename
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.with_suffix(".py").write_text("raise AssertionError('must not execute')")
    assert layout._structural_source_import_root(module, candidate) == (tmp_path if expected else None)


@pytest.mark.parametrize("name,unsafe", [
    ("agilab", True), ("streamlit.py", True), ("agi_env.so", True),
    ("third_party.py", False), ("notes.txt", False), ("bad-name.py", False),
])
def test_hosted_source_root_cannot_shadow_runtime(tmp_path, name, unsafe):
    candidate = tmp_path / name
    if "." in name:
        candidate.write_text("")
    else:
        candidate.mkdir()
    assert layout._root_exposes_hosted_runtime(tmp_path) is unsafe


@pytest.mark.parametrize("suffix", [".so", ".pyd", ".dylib", ".SO"])
def test_native_module_anywhere_in_source_root_blocks_hosted_import(tmp_path, suffix):
    module = tmp_path / "package" / ("native" + suffix)
    module.parent.mkdir()
    module.write_bytes(b"not-executable-test-fixture")
    assert layout._root_contains_native_code(tmp_path)


def test_native_scan_ignores_venv_and_handles_internal_symlink_cycle(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "native.so").write_bytes(b"fixture")
    package = tmp_path / "package"
    package.mkdir()
    (package / "cycle").symlink_to(package, target_is_directory=True)
    assert not layout._root_contains_native_code(tmp_path)


def test_native_scan_rejects_directory_symlink_escape(tmp_path):
    root = tmp_path / "source"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    assert layout._root_contains_native_code(root)


@pytest.mark.parametrize("operation", ["walk", "onerror", "stat"])
def test_native_scan_io_uncertainty_blocks_hosted_import(monkeypatch, tmp_path, operation):
    if operation == "stat":
        original = Path.stat
        def stat(path, *args, **kwargs):
            if path == tmp_path:
                raise OSError("denied")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "stat", stat)
    else:
        def walk(*args, **kwargs):
            if operation == "walk":
                raise OSError("directory unavailable")
            kwargs["onerror"](OSError("directory unavailable"))
            return iter(())
        monkeypatch.setattr(layout, "os", SimpleNamespace(walk=walk))
    assert layout._root_contains_native_code(tmp_path)


@pytest.mark.parametrize("method", ["iterdir", "is_dir", "is_file"])
def test_runtime_shadow_scan_io_uncertainty_is_unsafe(monkeypatch, tmp_path, method):
    child = tmp_path / "module.py"
    child.write_text("")
    original = getattr(Path, method)
    def failed(path, *args, **kwargs):
        if (method == "iterdir" and path == tmp_path) or (method != "iterdir" and path == child):
            raise OSError("cannot inspect")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, method, failed)
    assert layout._root_exposes_hosted_runtime(tmp_path)


def test_unresolvable_paths_remain_available_for_fail_closed_inspection(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "resolve", Mock(side_effect=OSError("broken mount")))
    assert layout._resolve_without_failure(tmp_path) == tmp_path


@pytest.mark.parametrize("operation", ["glob", "read_text"])
def test_unreadable_distribution_metadata_cannot_claim_installation(monkeypatch, tmp_path, operation):
    info = tmp_path / "demo-1.dist-info"
    info.mkdir()
    metadata = info / "METADATA"
    metadata.write_text("Name: demo\n")
    original = getattr(Path, operation)
    def failed(path, *args, **kwargs):
        if path == (tmp_path if operation == "glob" else metadata):
            raise OSError("denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, operation, failed)
    assert layout._distribution_metadata_dirs([tmp_path], "demo") == ()
