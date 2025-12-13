# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
import shutil
import sys
from pathlib import Path
import py7zr

from agi_env import AgiEnv


def _usage() -> None:
    print("Usage: python post_install.py <app>")


def _build_env(app_arg: Path) -> AgiEnv:
    """Instantiate :class:`AgiEnv` for the given app path.

    install_type is deprecated; heuristics inside AgiEnv determine flags
    like is_worker_env and is_source_env based on the provided paths.
    """

    return AgiEnv(apps_path=app_arg.parent, active_app=app_arg.name)

def _iter_data_files(folder: Path) -> list[Path]:
    patterns = ("*.csv", "*.parquet", "*.pq", "*.parq")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(folder.glob(pattern)))
    return [path for path in files if not path.name.startswith("._")]


def _extract_archive(archive: Path, dest: Path) -> None:
    if not archive.exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(archive, mode="r") as zf:
        zf.extractall(path=dest)


def _dataset_archive_candidates(env: AgiEnv) -> list[Path]:
    target_name = env.share_target_name
    candidates: list[Path] = []

    dataset_archive = getattr(env, "dataset_archive", None)
    if isinstance(dataset_archive, Path):
        candidates.append(dataset_archive)

    packaged = (
        env.agilab_pck
        / "apps"
        / f"{target_name}_project"
        / "src"
        / f"{target_name}_worker"
        / "dataset.7z"
    )
    candidates.append(packaged)

    seen: set[Path] = set()
    unique: list[Path] = []
    for item in candidates:
        try:
            key = item.resolve(strict=False)
        except Exception:
            key = item
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        _usage()
        return 1
    candidate = Path(args[0]).expanduser()
    # Use robust absolute-path detection across platforms (Windows, POSIX)
    if candidate.is_absolute():
        app_arg = candidate
    else:
        app_arg = Path.home() / "wenv" / candidate

    env = _build_env(app_arg)
    target_name = env.share_target_name
    dest_arg = env.resolve_share_path(target_name)
    dataset_archive = next(
        (candidate for candidate in _dataset_archive_candidates(env) if candidate.exists()),
        None,
    )
    if dataset_archive is None:
        print(
            f"[post_install] dataset archive not found for '{target_name}'. "
            f"Looked under {env.dataset_archive if hasattr(env, 'dataset_archive') else '<unknown>'} and packaged apps."
        )
        return 0

    print(f"[post_install] dataset archive: {dataset_archive}")
    print(f"[post_install] destination: {dest_arg}")
    env.unzip_data(dataset_archive, dest_arg)

    # Optional: seed satellite trajectories for LinkSim-style datasets.
    # Some app datasets ship satellite trajectories separately as Trajectory.7z to keep
    # the base dataset smaller. If present, extract it into the dataset folder and
    # mirror files into `dataset/sat` when that folder is empty.
    try:
        dataset_root = Path(dest_arg) / "dataset"
        sat_folder = dataset_root / "sat"
        sat_files = _iter_data_files(sat_folder)
        if len(sat_files) >= 2:
            return 0

        trajectory_archive = dataset_archive.parent / "Trajectory.7z"
        trajectory_folder = dataset_root / "Trajectory"

        if trajectory_archive.exists() and len(_iter_data_files(trajectory_folder)) < 2:
            print(f"[post_install] extracting optional trajectories: {trajectory_archive}")
            _extract_archive(trajectory_archive, dataset_root)

        trajectory_files = _iter_data_files(trajectory_folder)
        if len(trajectory_files) < 2:
            return 0

        sat_folder.mkdir(parents=True, exist_ok=True)
        copied = 0
        for src in trajectory_files:
            dest = sat_folder / src.name
            if dest.exists():
                continue
            shutil.copy2(src, dest)
            copied += 1
        if copied:
            print(
                f"[post_install] seeded {copied} trajectory file(s) into {sat_folder} "
                f"from {trajectory_folder}"
            )
    except Exception as exc:
        print(f"[post_install] optional dataset seeding skipped: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
