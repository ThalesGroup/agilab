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

def _has_samples(folder: Path) -> bool:
    return folder.exists() and len(_iter_data_files(folder)) >= 2


def _try_link_dir(link_path: Path, target_path: Path) -> bool:
    """Best-effort directory linking (symlink on POSIX, junction/symlink fallback on Windows)."""

    link_path = Path(link_path)
    target_path = Path(target_path)

    try:
        link_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False

    # If link_path already points to the right place, keep it.
    if link_path.is_symlink():
        try:
            if link_path.resolve(strict=False) == target_path.resolve(strict=False):
                return True
        except Exception:
            pass
        try:
            link_path.unlink()
        except Exception:
            return False

    if link_path.exists():
        # Only replace an existing directory when it has no usable data.
        try:
            if link_path.is_dir() and not _has_samples(link_path):
                # Remove empty-ish directory (ignore hidden metadata files).
                entries = [
                    p
                    for p in link_path.iterdir()
                    if not p.name.startswith(("._", "."))
                ]
                if len(entries) == 0:
                    shutil.rmtree(link_path, ignore_errors=True)
            else:
                return False
        except Exception:
            return False

    try:
        os.symlink(str(target_path), str(link_path), target_is_directory=True)
        return True
    except Exception:
        pass

    if os.name == "nt":
        try:
            import subprocess

            subprocess.check_call(
                ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    return False


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


def _dir_is_duplicate_of(source_dir: Path, reference_dir: Path) -> bool:
    """Heuristic to decide if `source_dir` only contains copies of `reference_dir` data files."""

    if not source_dir.is_dir() or not reference_dir.is_dir():
        return False

    source_files = {p.name: p.stat().st_size for p in _iter_data_files(source_dir)}
    if len(source_files) < 2:
        return False

    reference_files = {p.name: p.stat().st_size for p in _iter_data_files(reference_dir)}
    if len(reference_files) < 2:
        return False

    if not set(source_files).issubset(reference_files):
        return False

    for name, size in source_files.items():
        if reference_files.get(name) != size:
            return False

    extras = [
        p
        for p in source_dir.iterdir()
        if not p.name.startswith(("._", "."))
        and p.name not in source_files
    ]
    return len(extras) == 0


def _looks_like_generated_trajectory(path: Path) -> bool:
    name = path.name.lower()
    return (
        "_trajectory" in name
        or name.startswith("starlink-")
        or name.endswith("_traj.csv")
        or name.endswith("_traj.parquet")
    )


def _folder_looks_large(folder: Path) -> bool:
    """Detect large/generated trajectory folders that can stall downstream apps/tests."""

    files = _iter_data_files(folder)
    if len(files) < 2:
        return False
    if any(_looks_like_generated_trajectory(path) for path in files):
        return True
    if len(files) > 20:
        return True
    try:
        if max(path.stat().st_size for path in files) >= 1_000_000:
            return True
    except OSError:
        return False
    return False


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

        # Prefer reusing trajectories produced by sat_trajectory to avoid duplicating data.
        share_root = env.share_root_path()
        sat_trajectory_root = (Path(share_root) / "sat_trajectory").resolve(strict=False)
        # Prefer the packaged sat_trajectory dataset for deterministic installs/tests.
        # The generated `dataframe/Trajectory` output can be very large (e.g. long
        # propagation horizons) and may significantly slow down downstream consumers.
        sat_trajectory_candidates = [
            sat_trajectory_root / "dataset" / "Trajectory",
            sat_trajectory_root / "dataframe" / "Trajectory",
        ]
        preferred_candidate = next(
            (candidate for candidate in sat_trajectory_candidates if _has_samples(candidate)),
            None,
        )
        preserve_existing = os.environ.get("AGILAB_PRESERVE_LINK_SIM_SAT", "0") not in {
            "",
            "0",
            "false",
            "False",
        }

        if preferred_candidate is not None:
            if sat_folder.is_symlink():
                try:
                    current_target = sat_folder.resolve(strict=False)
                    preferred_target = preferred_candidate.resolve(strict=False)
                    if current_target == preferred_target:
                        return 0
                    # If the existing link points to sat_trajectory output, relink it to the
                    # preferred deterministic dataset (avoids accidentally binding to large
                    # generated trajectories).
                    if sat_trajectory_root in current_target.parents and sat_trajectory_root in preferred_target.parents:
                        if _try_link_dir(sat_folder, preferred_candidate):
                            print(f"[post_install] relinked {sat_folder} -> {preferred_candidate}")
                        return 0
                except Exception:
                    pass

            if _has_samples(sat_folder):
                if preserve_existing:
                    return 0
                if _dir_is_duplicate_of(sat_folder, preferred_candidate):
                    try:
                        shutil.rmtree(sat_folder, ignore_errors=False)
                    except Exception:
                        return 0
                    if _try_link_dir(sat_folder, preferred_candidate):
                        print(f"[post_install] deduplicated {sat_folder} -> {preferred_candidate}")
                if _folder_looks_large(sat_folder):
                    try:
                        shutil.rmtree(sat_folder, ignore_errors=False)
                    except Exception:
                        return 0
                    if _try_link_dir(sat_folder, preferred_candidate):
                        print(f"[post_install] replaced large {sat_folder} -> {preferred_candidate}")
                    return 0
                return 0

            if _try_link_dir(sat_folder, preferred_candidate):
                print(f"[post_install] linked {sat_folder} -> {preferred_candidate}")
                return 0
        elif _has_samples(sat_folder):
            return 0

        trajectory_archive = dataset_archive.parent / "Trajectory.7z"
        trajectory_folder = dataset_root / "Trajectory"

        if not _has_samples(trajectory_folder) and trajectory_archive.exists():
            print(f"[post_install] extracting optional trajectories: {trajectory_archive}")
            _extract_archive(trajectory_archive, dataset_root)

        if not _has_samples(trajectory_folder):
            return 0

        if _try_link_dir(sat_folder, trajectory_folder):
            print(f"[post_install] linked {sat_folder} -> {trajectory_folder}")
            return 0

        # Last resort: copy (may duplicate data, but keeps the app runnable).
        sat_folder.mkdir(parents=True, exist_ok=True)
        copied = 0
        for src in _iter_data_files(trajectory_folder):
            dest = sat_folder / src.name
            if dest.exists():
                continue
            shutil.copy2(src, dest)
            copied += 1
        if copied:
            print(f"[post_install] copied {copied} trajectory file(s) into {sat_folder}")
    except Exception as exc:
        print(f"[post_install] optional dataset seeding skipped: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
