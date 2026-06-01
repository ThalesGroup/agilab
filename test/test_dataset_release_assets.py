from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tarfile


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import dataset_release_assets  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_dataset_release_assets_collects_all_tracked_datasets_and_pypi_datasets(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")

    packaged_dataset = repo / "src/agilab/apps/builtin/demo_project/src/demo_worker/dataset.7z"
    sample_dataset = repo / "src/agilab/apps/builtin/demo_project/src/demo/sample_data/example.csv"
    docs_dataset = repo / "docs/source/data/benchmark.csv"
    non_dataset = repo / "README.csv"
    packaged_dataset.parent.mkdir(parents=True)
    sample_dataset.parent.mkdir(parents=True)
    docs_dataset.parent.mkdir(parents=True)
    packaged_dataset.write_bytes(b"binary dataset")
    sample_dataset.write_text("x,y\n1,2\n", encoding="utf-8")
    docs_dataset.write_text("case,value\nfast,1\n", encoding="utf-8")
    non_dataset.write_text("not,a,dataset\n", encoding="utf-8")
    _git(repo, "add", ".")

    records = dataset_release_assets.discover_dataset_records(repo)

    paths = [record["path"] for record in records]
    assert paths == [
        "docs/source/data/benchmark.csv",
        "src/agilab/apps/builtin/demo_project/src/demo/sample_data/example.csv",
        "src/agilab/apps/builtin/demo_project/src/demo_worker/dataset.7z",
    ]
    assert records[1]["pypi_packaged"] is True
    assert records[2]["pypi_packaged"] is True
    assert all(record["looks_like_lfs_pointer"] is False for record in records)


def test_dataset_release_assets_writes_content_addressed_manifest_and_full_archive(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "out"
    repo.mkdir()
    _git(repo, "init")

    dataset = repo / "src/agilab/apps/builtin/demo_project/src/demo_worker/dataset.7z"
    dataset.parent.mkdir(parents=True)
    dataset.write_bytes(b"full dataset contents")
    _git(repo, "add", ".")

    records = dataset_release_assets.discover_dataset_records(repo)
    manifest = dataset_release_assets.build_manifest(records, "v2026.6.1")
    out.mkdir()
    archive_path = out / f"agilab-datasets-{manifest['dataset_manifest_sha256'][:16]}.tar.gz"
    manifest_path = out / "dataset-release-manifest.json"
    dataset_release_assets.write_manifest(manifest, manifest_path)
    dataset_release_assets.write_dataset_archive(repo, records, archive_path)

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved_manifest["dataset_release_tag"] == f"datasets-{saved_manifest['dataset_manifest_sha256'][:16]}"
    assert saved_manifest["dataset_count"] == 1
    assert saved_manifest["datasets"][0]["path"] == "src/agilab/apps/builtin/demo_project/src/demo_worker/dataset.7z"

    with tarfile.open(archive_path, "r:gz") as tar:
        member = tar.extractfile("src/agilab/apps/builtin/demo_project/src/demo_worker/dataset.7z")
        assert member is not None
        assert member.read() == b"full dataset contents"


def test_dataset_release_assets_detects_lfs_pointer_files(tmp_path: Path) -> None:
    pointer = tmp_path / "dataset.7z"
    pointer.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:593536ccdc000000000000000000000000000000000000000000000000000000\n"
        "size 123\n",
        encoding="utf-8",
    )

    assert dataset_release_assets.looks_like_lfs_pointer(pointer) is True
