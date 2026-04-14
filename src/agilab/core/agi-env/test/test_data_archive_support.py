from pathlib import Path
from unittest import mock

import pytest

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
            raise ValueError("bad archive")

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
