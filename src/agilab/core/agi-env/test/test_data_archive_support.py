from pathlib import Path
from unittest import mock

import pytest

import agi_env.data_archive_support as data_archive_support
from agi_env.data_archive_support import unzip_data


def test_unzip_data_warns_when_archive_missing(tmp_path: Path):
    logger = mock.Mock()

    unzip_data(
        tmp_path / "missing.7z",
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=tmp_path / "share",
        user=Path.home().name,
        home_abs=Path.home(),
        verbose=0,
        logger=logger,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        sevenzip_file_cls=object,  # not used on this path
        rmtree_fn=lambda *_a, **_k: None,
    )

    assert logger.warning.called


def test_unzip_data_raises_runtime_error_on_extract_failure(tmp_path: Path):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    logger = mock.Mock()

    class _BrokenSevenZip:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, path):
            raise data_archive_support.py7zr.exceptions.Bad7zFile("bad archive")

    with pytest.raises(RuntimeError, match="Extraction failed"):
        unzip_data(
            archive,
            extract_to="dataset/demo",
            app_data_rel="demo",
            agi_share_path_abs=tmp_path / "share",
            user=Path.home().name,
            home_abs=Path.home(),
            verbose=0,
            logger=logger,
            force_extract=True,
            ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
            sevenzip_file_cls=_BrokenSevenZip,
            rmtree_fn=lambda *_a, **_k: None,
        )


def test_unzip_data_propagates_unexpected_extract_bug(tmp_path: Path):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    logger = mock.Mock()

    class _BrokenSevenZip:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, path):
            raise ValueError("extract bug")

    with pytest.raises(ValueError, match="extract bug"):
        unzip_data(
            archive,
            extract_to="dataset/demo",
            app_data_rel="demo",
            agi_share_path_abs=tmp_path / "share",
            user=Path.home().name,
            home_abs=Path.home(),
            verbose=0,
            logger=logger,
            force_extract=True,
            ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
            sevenzip_file_cls=_BrokenSevenZip,
            rmtree_fn=lambda *_a, **_k: None,
        )


def test_write_dataset_stamp_handles_oserror_and_propagates_runtime_bug(tmp_path: Path, monkeypatch):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    stamp_path = tmp_path / "dataset" / ".agilab_dataset_stamp"
    stamp_path.parent.mkdir(parents=True)

    original_write_text = Path.write_text

    def _oserror_write_text(self, *args, **kwargs):
        if self == stamp_path:
            raise OSError("write failed")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _oserror_write_text, raising=False)
    data_archive_support._write_dataset_stamp(archive, stamp_path)

    def _runtime_write_text(self, *args, **kwargs):
        if self == stamp_path:
            raise RuntimeError("write bug")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _runtime_write_text, raising=False)
    with pytest.raises(RuntimeError, match="write bug"):
        data_archive_support._write_dataset_stamp(archive, stamp_path)


def test_archive_size_mb_handles_oserror_and_propagates_runtime_bug(tmp_path: Path, monkeypatch):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"1234567890")

    original_stat = Path.stat

    def _oserror_stat(self, *args, **kwargs):
        if self == archive:
            raise OSError("stat failed")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _oserror_stat, raising=False)
    assert data_archive_support._archive_size_mb(archive) is None

    def _runtime_stat(self, *args, **kwargs):
        if self == archive:
            raise RuntimeError("stat bug")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _runtime_stat, raising=False)
    with pytest.raises(RuntimeError, match="stat bug"):
        data_archive_support._archive_size_mb(archive)


def test_unzip_data_skips_owner_mismatch_and_parent_or_dest_failures(tmp_path: Path):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    logger = mock.Mock()
    share_root = tmp_path / "share"
    share_root.mkdir()
    home_abs = tmp_path / "home"
    home_abs.mkdir()

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user="other-user",
        home_abs=home_abs,
        verbose=1,
        logger=logger,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        sevenzip_file_cls=object,
        rmtree_fn=lambda *_a, **_k: None,
    )
    assert logger.info.called

    logger.reset_mock()
    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user=home_abs.name,
        home_abs=home_abs,
        verbose=0,
        logger=logger,
        ensure_dir_fn=lambda _path: (_ for _ in ()).throw(OSError("mkdir failed")),
        sevenzip_file_cls=object,
        rmtree_fn=lambda *_a, **_k: None,
    )
    assert logger.warning.called


def test_unzip_data_owner_mismatch_handles_target_dir_prepare_failure(tmp_path: Path):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    logger = mock.Mock()
    share_root = tmp_path / "share"
    share_root.mkdir()
    home_abs = tmp_path / "home"
    home_abs.mkdir()

    def _ensure_dir(path):
        path = Path(path)
        if path == share_root / "dataset" / "demo":
            raise OSError("mkdir failed")
        path.mkdir(parents=True, exist_ok=True)
        return path

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user="other-user",
        home_abs=home_abs,
        verbose=0,
        logger=logger,
        ensure_dir_fn=_ensure_dir,
        sevenzip_file_cls=object,
        rmtree_fn=lambda *_a, **_k: None,
    )

    logger.warning.assert_called()


def test_unzip_data_existing_dataset_refresh_and_success_paths(tmp_path: Path):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    share_root = tmp_path / "share"
    share_root.mkdir()
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    logger = mock.Mock()
    extracted: list[Path] = []
    removed: list[tuple[Path, object]] = []

    class _Archive:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, path):
            extracted.append(Path(path))
            dataset_dir = Path(path) / "dataset"
            dataset_dir.mkdir(parents=True, exist_ok=True)
            (dataset_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")

    dataset = share_root / "dataset" / "demo" / "dataset"
    dataset.mkdir(parents=True)
    stamp_path = dataset / ".agilab_dataset_stamp"

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user=home_abs.name,
        home_abs=home_abs,
        verbose=1,
        logger=logger,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        sevenzip_file_cls=_Archive,
        rmtree_fn=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("refresh should not run")),
    )
    assert stamp_path.exists()

    logger.reset_mock()
    extracted.clear()

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user=home_abs.name,
        home_abs=home_abs,
        verbose=2,
        logger=logger,
        force_extract=True,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        sevenzip_file_cls=_Archive,
        rmtree_fn=lambda path, onerror=None: removed.append((Path(path), onerror)),
    )
    assert removed and removed[0][0] == dataset
    assert extracted == [share_root / "dataset" / "demo"]
    assert logger.info.called


def test_unzip_data_refresh_handles_missing_permission_and_dataset_dir_failures(tmp_path: Path):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    share_root = tmp_path / "share"
    share_root.mkdir()
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    logger = mock.Mock()
    dataset = share_root / "dataset" / "demo" / "dataset"
    dataset.mkdir(parents=True)

    def _missing_rmtree(_path, onerror=None):
        if onerror is not None:
            onerror(lambda *_args: None, "missing", (FileNotFoundError, FileNotFoundError("gone"), None))

    class _Archive:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, path):
            dataset_dir = Path(path) / "dataset"
            dataset_dir.mkdir(parents=True, exist_ok=True)

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user=home_abs.name,
        home_abs=home_abs,
        verbose=0,
        logger=logger,
        force_extract=True,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        sevenzip_file_cls=_Archive,
        rmtree_fn=_missing_rmtree,
    )

    logger.reset_mock()

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user=home_abs.name,
        home_abs=home_abs,
        verbose=1,
        logger=logger,
        force_extract=True,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        sevenzip_file_cls=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("archive should not open")),
        rmtree_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )
    assert logger.info.called

    logger.reset_mock()

    def _dataset_dir_failure(path):
        if Path(path).name == "dataset":
            raise OSError("dataset mkdir failed")
        return Path(path).mkdir(parents=True, exist_ok=True) or Path(path)

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user=home_abs.name,
        home_abs=home_abs,
        verbose=0,
        logger=logger,
        force_extract=True,
        ensure_dir_fn=_dataset_dir_failure,
        sevenzip_file_cls=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("archive should not open")),
        rmtree_fn=lambda *_args, **_kwargs: None,
    )
    assert logger.warning.called


def test_unzip_data_refresh_handles_direct_filenotfound_and_dataset_dir_failure(tmp_path: Path):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    share_root = tmp_path / "share"
    share_root.mkdir()
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    logger = mock.Mock()
    dataset = share_root / "dataset" / "demo" / "dataset"
    dataset.mkdir(parents=True)
    extracted = []

    class _Archive:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extractall(self, path):
            extracted.append(Path(path))
            dataset_dir = Path(path) / "dataset"
            dataset_dir.mkdir(parents=True, exist_ok=True)

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user=home_abs.name,
        home_abs=home_abs,
        verbose=0,
        logger=logger,
        force_extract=True,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        sevenzip_file_cls=_Archive,
        rmtree_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("gone")),
    )
    assert extracted == [share_root / "dataset" / "demo"]

    logger.reset_mock()

    def _dataset_dir_failure(path):
        path = Path(path)
        if path == dataset:
            raise OSError("dataset mkdir failed")
        path.mkdir(parents=True, exist_ok=True)
        return path

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user=home_abs.name,
        home_abs=home_abs,
        verbose=0,
        logger=logger,
        force_extract=True,
        ensure_dir_fn=_dataset_dir_failure,
        sevenzip_file_cls=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("archive should not open")),
        rmtree_fn=lambda *_args, **_kwargs: None,
    )

    logger.warning.assert_called()


def test_unzip_data_refresh_onerror_raises_non_missing_exception(tmp_path: Path):
    archive = tmp_path / "demo.7z"
    archive.write_bytes(b"7z")
    share_root = tmp_path / "share"
    share_root.mkdir()
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    logger = mock.Mock()
    dataset = share_root / "dataset" / "demo" / "dataset"
    dataset.mkdir(parents=True)

    def _permission_rmtree(_path, onerror=None):
        if onerror is not None:
            onerror(lambda *_args: None, "locked", (PermissionError, PermissionError("denied"), None))

    unzip_data(
        archive,
        extract_to="dataset/demo",
        app_data_rel="demo",
        agi_share_path_abs=share_root,
        user=home_abs.name,
        home_abs=home_abs,
        verbose=1,
        logger=logger,
        force_extract=True,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        sevenzip_file_cls=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("archive should not open")),
        rmtree_fn=_permission_rmtree,
    )

    logger.info.assert_called()
