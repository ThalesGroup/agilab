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
