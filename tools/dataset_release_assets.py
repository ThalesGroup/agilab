#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
from typing import Any


SCHEMA = "agilab.dataset_release_assets.v1"
DATASET_SUFFIXES = {".7z", ".csv", ".npz", ".parquet"}
DATASET_DIR_PARTS = {"analysis_artifacts", "data", "dataset", "datasets", "sample_data"}
DATASET_FILENAMES = {"dataset.7z"}
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"


def _run_git(repo_root: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    return completed.stdout.decode("utf-8", errors="replace")


def _run_git_optional(repo_root: Path, args: list[str]) -> str:
    try:
        return _run_git(repo_root, args)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def _git_tracked_files(repo_root: Path) -> list[Path]:
    output = _run_git(repo_root, ["ls-files", "-z"])
    return [Path(part) for part in output.split("\0") if part]


def _git_lfs_files(repo_root: Path) -> set[str]:
    output = _run_git_optional(repo_root, ["lfs", "ls-files", "--name-only"])
    return {line.strip() for line in output.splitlines() if line.strip()}


def is_dataset_path(relative_path: Path) -> bool:
    if relative_path.name in DATASET_FILENAMES:
        return True
    if relative_path.suffix.lower() not in DATASET_SUFFIXES:
        return False
    return any(part in DATASET_DIR_PARTS for part in relative_path.parts)


def looks_like_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_dataset_records(repo_root: Path) -> list[dict[str, Any]]:
    lfs_paths = _git_lfs_files(repo_root)
    records: list[dict[str, Any]] = []
    for relative_path in sorted(_git_tracked_files(repo_root), key=lambda value: value.as_posix()):
        if not is_dataset_path(relative_path):
            continue
        absolute_path = repo_root / relative_path
        if not absolute_path.is_file():
            continue
        records.append(
            {
                "path": relative_path.as_posix(),
                "sha256": _file_sha256(absolute_path),
                "size_bytes": absolute_path.stat().st_size,
                "lfs_tracked": relative_path.as_posix() in lfs_paths,
                "looks_like_lfs_pointer": looks_like_lfs_pointer(absolute_path),
                "pypi_packaged": relative_path.as_posix().startswith("src/agilab/"),
            }
        )
    return records


def manifest_content_hash(records: list[dict[str, Any]]) -> str:
    stable_payload = {
        "datasets": records,
        "schema": SCHEMA,
    }
    encoded = json.dumps(stable_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_manifest(records: list[dict[str, Any]], release_tag: str) -> dict[str, Any]:
    content_hash = manifest_content_hash(records)
    return {
        "schema": SCHEMA,
        "release_tag": release_tag,
        "dataset_release_tag": f"datasets-{content_hash[:16]}",
        "dataset_manifest_sha256": content_hash,
        "generated_at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "dataset_count": len(records),
        "total_size_bytes": sum(int(record["size_bytes"]) for record in records),
        "datasets": records,
    }


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_dataset_archive(repo_root: Path, records: list[dict[str, Any]], archive_path: Path) -> None:
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        for record in records:
            relative_path = Path(record["path"])
            absolute_path = repo_root / relative_path
            tar_info = tar.gettarinfo(str(absolute_path), arcname=relative_path.as_posix())
            tar_info.uid = 0
            tar_info.gid = 0
            tar_info.uname = ""
            tar_info.gname = ""
            tar_info.mtime = 0
            tar_info.mode = 0o644
            with absolute_path.open("rb") as handle:
                tar.addfile(tar_info, handle)

    with archive_path.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as gzip_file:
            gzip_file.write(tar_buffer.getvalue())


def write_sha256sums(output_dir: Path, checksum_path: Path) -> None:
    lines: list[str] = []
    for path in sorted(output_dir.iterdir(), key=lambda value: value.name):
        if not path.is_file() or path == checksum_path:
            continue
        lines.append(f"{_file_sha256(path)}  {path.name}")
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_github_output(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _append_step_summary(path: Path, manifest: dict[str, Any], archive_name: str) -> None:
    lines = [
        "## AGILAB dataset release assets",
        "",
        f"- Dataset release tag: `{manifest['dataset_release_tag']}`",
        f"- Dataset manifest sha256: `{manifest['dataset_manifest_sha256']}`",
        f"- Dataset files: `{manifest['dataset_count']}`",
        f"- Archive: `{archive_name}`",
        "",
        "PyPI packages keep their packaged datasets. This separate GitHub release provides the full tracked dataset payload for source checkouts and LFS-pointer replacement.",
        "",
    ]
    path.open("a", encoding="utf-8").write("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build AGILAB GitHub dataset release assets.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-tag", default=os.environ.get("RELEASE_TAG", "dev"))
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-step-summary", type=Path)
    parser.add_argument("--fail-on-lfs-pointer", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    records = discover_dataset_records(repo_root)
    pointer_paths = [record["path"] for record in records if record["looks_like_lfs_pointer"]]
    if args.fail_on_lfs_pointer and pointer_paths:
        formatted_paths = "\n".join(f"- {path}" for path in pointer_paths)
        raise SystemExit(
            "Dataset release assets require materialized file contents, but Git LFS pointer files were found:\n"
            f"{formatted_paths}\n"
            "Run the workflow checkout with lfs: true or run git lfs pull before building dataset assets."
        )

    manifest = build_manifest(records, args.release_tag)
    tag_suffix = manifest["dataset_manifest_sha256"][:16]
    archive_name = f"agilab-datasets-{tag_suffix}.tar.gz"
    manifest_path = output_dir / "dataset-release-manifest.json"
    archive_path = output_dir / archive_name
    checksum_path = output_dir / "dataset-SHA256SUMS.txt"

    write_manifest(manifest, manifest_path)
    write_dataset_archive(repo_root, records, archive_path)
    write_sha256sums(output_dir, checksum_path)

    outputs = {
        "dataset_count": str(manifest["dataset_count"]),
        "dataset_manifest_sha256": str(manifest["dataset_manifest_sha256"]),
        "dataset_release_tag": str(manifest["dataset_release_tag"]),
        "dataset_archive": archive_path.name,
        "dataset_manifest": manifest_path.name,
    }
    if args.github_output:
        _append_github_output(args.github_output, outputs)
    if args.github_step_summary:
        _append_step_summary(args.github_step_summary, manifest, archive_name)

    print(json.dumps({**outputs, "output_dir": str(output_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
