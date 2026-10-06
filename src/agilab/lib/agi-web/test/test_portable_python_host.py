"""Validate standalone Python host exports and their file custody."""

from __future__ import annotations

import hashlib
import sys

import pytest

from agi_web import portable_python_host as portable


def test_standalone_export_matches_allowlist_and_exact_package_bytes(tmp_path):
    target = tmp_path / "standalone" / "agi_web"
    manifest = portable.export_python_host(target)
    names = portable.python_host_files()
    assert set(manifest) == set(names)
    assert set(portable.PYTHON_HOST_MODULES).issubset(names)
    assert list(names[len(portable.PYTHON_HOST_MODULES):]) == sorted(
        names[len(portable.PYTHON_HOST_MODULES):]
    )
    actual = {str(path.relative_to(target)): path for path in target.rglob("*") if path.is_file()}
    assert set(actual) == set(names)
    package = portable.files("agi_web")
    for name, path in actual.items():
        expected = package.joinpath(name).read_bytes()
        assert path.read_bytes() == expected
        assert manifest[name] == hashlib.sha256(expected).hexdigest()
    assert "react_python_host_assets/agilab_react_python_host.js" in manifest
    assert "react_main_interface_assets/agilab_react_main_interface.css" in manifest


def test_standalone_export_accepts_empty_directory(tmp_path):
    target = tmp_path / "empty"
    target.mkdir()
    assert portable.export_python_host(str(target))


@pytest.mark.parametrize("kind", ["file", "nonempty", "symlink", "dangling-symlink"])
def test_standalone_export_preserves_existing_or_linked_destination(tmp_path, kind):
    target = tmp_path / "destination"
    if kind == "file":
        target.write_bytes(b"keep")
    elif kind == "nonempty":
        target.mkdir()
        (target / "keep.txt").write_bytes(b"keep")
    else:
        original = tmp_path / "original"
        if kind == "symlink":
            original.mkdir()
            (original / "keep.txt").write_bytes(b"keep")
        try:
            target.symlink_to(original, target_is_directory=True)
        except NotImplementedError:
            pytest.skip("This filesystem does not support symbolic links.")
        except OSError as exc:
            if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
                pytest.skip("Creating symbolic links requires Windows developer mode or privilege.")
            raise
    with pytest.raises(ValueError, match="new or empty directory"):
        portable.export_python_host(target)
    if kind == "file":
        assert target.read_bytes() == b"keep"
    elif kind == "nonempty":
        assert (target / "keep.txt").read_bytes() == b"keep"
    elif kind == "symlink":
        assert (target.resolve() / "keep.txt").read_bytes() == b"keep"
    else:
        assert target.is_symlink() and not target.exists()


def test_standalone_export_reads_every_asset_before_creating_destination(tmp_path, monkeypatch):
    destination = tmp_path / "export"
    package = portable.files("agi_web")

    class UnreadablePackage:
        def joinpath(self, name):
            if name == "component.py":
                raise OSError("unreadable package asset")
            return package.joinpath(name)

    monkeypatch.setattr(portable, "files", lambda name: UnreadablePackage())
    with pytest.raises(OSError, match="unreadable package asset"):
        portable.export_python_host(destination)
    assert not destination.exists()


def test_host_asset_inventory_ignores_directories(tmp_path, monkeypatch):
    package = tmp_path / "package"
    for directory in portable._ASSET_DIRECTORIES:
        assets = package / directory
        assets.mkdir(parents=True)
        (assets / "bundle.js").write_text("bundle", encoding="utf-8")
        (assets / "subdirectory").mkdir()
    monkeypatch.setattr(portable, "files", lambda name: package)
    names = portable.python_host_files()
    assert names == (
        *portable.PYTHON_HOST_MODULES,
        *(directory + "/bundle.js" for directory in sorted(portable._ASSET_DIRECTORIES)),
    )
