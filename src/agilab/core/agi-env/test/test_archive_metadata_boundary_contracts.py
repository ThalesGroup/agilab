"""Archive preflight rejects incomplete metadata before any extraction."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_env.project import data_archive_support as archive


@pytest.mark.parametrize("value", [object(), "not-a-size", -1])
def test_invalid_uncompressed_metadata_is_rejected(tmp_path, value):
    member = SimpleNamespace(filename="dataset/data", uncompressed=value, compressed=1)
    with pytest.raises(ValueError, match="invalid|negative"):
        archive.validate_archive_extraction_quota(
            SimpleNamespace(list=lambda: [member]), tmp_path, min_free_bytes=0
        )


def test_missing_metadata_api_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="member size metadata is unavailable"):
        archive.validate_archive_extraction_quota(SimpleNamespace(), tmp_path)


def test_missing_member_size_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="size metadata"):
        archive.validate_archive_extraction_quota(
            SimpleNamespace(list=lambda: [SimpleNamespace(filename="data")]), tmp_path
        )


@pytest.mark.parametrize("compressed", [None, 0])
def test_unavailable_or_zero_compressed_size_rejects_nonempty_archive(tmp_path, compressed):
    member = SimpleNamespace(filename="data", uncompressed=10, compressed=compressed)
    with pytest.raises(ValueError, match="compressed-size metadata|compression ratio"):
        archive.validate_archive_extraction_quota(
            SimpleNamespace(list=lambda: [member]), tmp_path, min_free_bytes=0
        )


def test_non_zip_member_metadata_supplies_overall_compression_basis(tmp_path, monkeypatch):
    disk = Mock(return_value=SimpleNamespace(free=15))
    monkeypatch.setattr(archive.shutil, "disk_usage", disk)
    member = SimpleNamespace(filename="data", uncompressed="10", compressed="5")
    archive.validate_archive_extraction_quota(
        SimpleNamespace(list=lambda: [member]), tmp_path / "not-created",
        max_compression_ratio=2, min_free_bytes=5,
    )
    disk.assert_called_once_with(tmp_path)


def test_directory_metadata_does_not_need_sizes(tmp_path, monkeypatch):
    monkeypatch.setattr(archive.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    archive.validate_archive_extraction_quota(
        SimpleNamespace(infolist=lambda: [SimpleNamespace(is_dir=lambda: True)]),
        tmp_path, min_free_bytes=0,
    )


@pytest.mark.parametrize("name", ["/absolute/data", "C:/data", "C:data", "../data", "..\\data"])
def test_member_path_preflight_rejects_absolute_drive_and_parent_names(tmp_path, name):
    with pytest.raises(RuntimeError, match="Unsafe archive member path"):
        archive.validate_archive_members_stay_within_dest(
            SimpleNamespace(getnames=lambda: [name]), tmp_path
        )


@pytest.mark.parametrize("error", [ImportError("optional module absent"), AttributeError("partial module")])
def test_exception_module_import_falls_back_to_package_exports(monkeypatch, error):
    exports = SimpleNamespace()
    monkeypatch.setattr(archive.py7zr, "exceptions", exports, raising=False)
    def fail(_name):
        raise error
    monkeypatch.setattr(archive.importlib, "import_module", fail)
    assert archive._load_py7zr_exceptions_module() is exports


@pytest.mark.parametrize("error", [ImportError("implementation absent"), AttributeError("partial module")])
def test_missing_py7zr_implementation_remains_unavailable(monkeypatch, error):
    def fail(_name):
        raise error
    monkeypatch.setattr(archive.importlib, "import_module", fail)
    assert archive._load_py7zr_implementation_module(SimpleNamespace()) is None


def test_missing_archive_class_reports_dependency_failure():
    with pytest.raises(AttributeError, match="SevenZipFile class is unavailable"):
        archive._py7zr_sevenzip_file_class(SimpleNamespace(SevenZipFile="bad"), SimpleNamespace())


def test_archive_class_can_be_restored_from_implementation():
    class SevenZipFile:
        pass
    package = SimpleNamespace()
    archive.ensure_py7zr_package_compatibility(
        package, implementation_module=SimpleNamespace(SevenZipFile=SevenZipFile),
        exceptions_module=SimpleNamespace(),
    )
    assert package.SevenZipFile is SevenZipFile


def _refresh_fixture(tmp_path):
    from pathlib import Path
    import shutil
    source = tmp_path / "dataset.7z"
    source.write_bytes(b"archive")
    home = tmp_path / "home"
    dest = home / "app"
    live = dest / "dataset"
    live.mkdir(parents=True)
    (live / "old.txt").write_text("prior")
    class Archive:
        def __init__(self, *_args, **_kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def getnames(self):
            return ["dataset/new.txt"]
        def list(self):
            return [SimpleNamespace(filename="dataset/new.txt", uncompressed=3, compressed=3)]
        def extractall(self, path):
            dataset = Path(path) / "dataset"
            dataset.mkdir()
            (dataset / "new.txt").write_text("new")
    kwargs = dict(
        extract_to="app", app_data_rel="app", agi_share_path_abs=home,
        user="owner", home_abs=tmp_path / "owner", verbose=2, logger=Mock(),
        force_extract=True, ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True),
        sevenzip_file_cls=Archive, rmtree_fn=shutil.rmtree, environ={},
    )
    return source, live, Archive, kwargs


def test_extracted_archive_without_dataset_preserves_live_tree(tmp_path):
    source, live, Archive, kwargs = _refresh_fixture(tmp_path)
    Archive.extractall = lambda self, path: None
    with pytest.raises(RuntimeError) as caught:
        archive.unzip_data(source, **kwargs)
    assert "did not produce a dataset directory" in str(caught.value)
    assert (live / "old.txt").read_text() == "prior"
    assert not list(live.parent.glob(".agilab-dataset-refresh-*"))


def test_extracted_symlink_escape_is_rejected_before_live_swap(tmp_path):
    from pathlib import Path
    source, live, Archive, kwargs = _refresh_fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_text("untouched")
    def extract(self, path):
        (Path(path) / "dataset").symlink_to(outside, target_is_directory=True)
    Archive.extractall = extract
    with pytest.raises(RuntimeError) as caught:
        archive.unzip_data(source, **kwargs)
    assert "escaped its staging directory" in str(caught.value)
    assert (live / "old.txt").read_text() == "prior"
    assert (outside / "sentinel").read_text() == "untouched"
    assert not (outside / ".agilab_dataset_stamp").exists()


def test_failed_refresh_and_failed_rollback_retains_recoverable_backup(tmp_path, monkeypatch):
    from pathlib import Path
    source, live, Archive, kwargs = _refresh_fixture(tmp_path)
    replace = Path.replace
    def fail_publication_or_rollback(path, target):
        if path.name.endswith(".rollback") or path.parent.name.startswith(".agilab-dataset-refresh-"):
            raise OSError("destination locked")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", fail_publication_or_rollback)
    with pytest.raises(RuntimeError) as caught:
        archive.unzip_data(source, **kwargs)
    assert "rollback could not restore" in str(caught.value)
    backups = list(live.parent.glob("*.rollback"))
    # The backup is hidden on POSIX; glob still includes dot-prefixed entries.
    assert len(backups) == 1
    assert (backups[0] / "old.txt").read_text() == "prior"
    assert not live.exists()
    assert not list(live.parent.glob(".agilab-dataset-refresh-*/new.txt"))
