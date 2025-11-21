#!/usr/bin/env python3
# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this
#    list of conditions and the following disclaimer in the documentation and/or other
#    materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or
#    THALES SIX GTS France SAS, may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT
# SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
# BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
# DAMAGE.

import os
import posixpath
import zipfile
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
import argparse
from pathlib import Path
from functools import lru_cache

EXCLUDE_DIRS = {'.git', '.venv', '__pycache__', 'node_modules'}
FOLLOW_SYMLINK_NAMES_DEFAULT = {"apps", "apps-pages"}

@lru_cache(maxsize=None)
def read_gitignore_cached(gitignore_path):
    try:
        with open(gitignore_path, "r") as f:
            patterns = f.read().splitlines()
        return PathSpec.from_lines(GitWildMatchPattern, patterns)
    except FileNotFoundError:
        return PathSpec.from_lines(GitWildMatchPattern, [])

def _normalize_relpath(relpath: str) -> str:
    return relpath.replace(os.sep, "/")


def should_include_file(relpath, spec, follow_symlink_names=None, verbose=False):
    relpath_norm = _normalize_relpath(relpath)
    if follow_symlink_names and _should_follow_symlink(relpath_norm, follow_symlink_names):
        if verbose:
            print(f"CHECK: {relpath_norm} --> INCLUDE (forced by follow names)")
        return True
    included = not spec.match_file(relpath_norm)
    if verbose:
        print(f"CHECK: {relpath_norm} --> {'INCLUDE' if included else 'EXCLUDE'}")
    return included


def split_file(path: Path, max_bytes: int, verbose: bool = False) -> list[Path]:
    """Split a file into parts of at most max_bytes. Returns created part paths."""
    size = path.stat().st_size
    if size <= max_bytes:
        if verbose:
            print(f"No split needed; size {size} bytes <= limit {max_bytes} bytes")
        return []
    parts: list[Path] = []
    with open(path, "rb") as src:
        idx = 1
        while True:
            chunk = src.read(max_bytes)
            if not chunk:
                break
            part_path = Path(f"{path}.part{idx:02d}")
            with open(part_path, "wb") as dst:
                dst.write(chunk)
            parts.append(part_path)
            if verbose:
                print(f"Wrote part {part_path} ({len(chunk)} bytes)")
            idx += 1
    path.unlink()
    return parts


def _should_follow_symlink(relpath: str, follow_names: set[str]) -> bool:
    if not follow_names:
        return False
    parts = _normalize_relpath(relpath).split("/")
    return any(part in follow_names for part in parts if part)


def zip_directory(target_dir, zip_filepath, top_spec, no_top=False, verbose=False, follow_symlink_names=None, start_dir=None, exclude_dirs=None):
    target_dir = os.path.abspath(target_dir)
    walk_root = os.path.abspath(start_dir) if start_dir else target_dir
    base_name = os.path.basename(target_dir)
    output_zip_abs = os.path.abspath(zip_filepath)
    follow_symlink_names = set(follow_symlink_names or [])
    exclude_dir_set = set(EXCLUDE_DIRS)
    if exclude_dirs:
        exclude_dir_set |= set(exclude_dirs)
    visited_real_paths: set[str] = set()

    # Preserve archive paths relative to the original target dir even if we start deeper.
    start_relative = os.path.relpath(walk_root, target_dir)
    if start_relative == ".":
        start_relative = ""

    def process_directory(current_dir, relative_to, depth=0):
        if depth > 30:
            print(f"MAX DEPTH reached at {current_dir} - Possible recursion problem.")
            return
        real_current = os.path.realpath(current_dir)
        if real_current in visited_real_paths:
            if verbose:
                print(f"Skipping already visited directory: {real_current}")
            return
        visited_real_paths.add(real_current)
        try:
            with os.scandir(current_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False) and entry.name in exclude_dir_set:
                        if verbose:
                            print(f"Hard skip dir: {entry.name}")
                        continue
                    full_path = os.path.join(current_dir, entry.name)
                    archive_rel = entry.name if not relative_to else posixpath.join(relative_to, entry.name)
                    rel_for_match = archive_rel or entry.name
                    if os.path.abspath(full_path) == output_zip_abs:
                        continue
                    if entry.is_symlink() and not os.path.exists(full_path):
                        continue
                    if entry.is_symlink():
                        if follow_symlink_names and _should_follow_symlink(archive_rel, follow_symlink_names):
                            target_path = os.path.realpath(full_path)
                            if not os.path.exists(target_path):
                                if verbose:
                                    print(f"Symlink target missing, skipping: {full_path} -> {target_path}")
                                continue
                            if os.path.isdir(target_path):
                                if verbose:
                                    print(f"Following directory symlink: {archive_rel} -> {target_path}")
                                process_directory(target_path, archive_rel, depth+1)
                            else:
                                archive_path = archive_rel if no_top else posixpath.join(base_name, archive_rel)
                                if should_include_file(rel_for_match, top_spec, follow_symlink_names, verbose):
                                    zipf.write(target_path, archive_path)
                                    if verbose:
                                        print(f"Adding symlink file {archive_path} (target: {target_path})")
                            continue
                        else:
                            if verbose:
                                print(f"Skipping symlink: {full_path}")
                            continue
                    # Don't recurse into ignored directories
                    if entry.is_dir(follow_symlinks=False):
                        rel_dir = rel_for_match + '/'
                        if not should_include_file(rel_dir, top_spec, follow_symlink_names, verbose):
                            if verbose:
                                print(f"Skipping directory (ignored by .gitignore): {full_path}")
                            continue
                        process_directory(
                            full_path,
                            archive_rel,
                            depth+1
                        )
                    else:
                        archive_path = archive_rel if no_top else posixpath.join(base_name, archive_rel)
                        if should_include_file(rel_for_match, top_spec, follow_symlink_names, verbose):
                            if not os.path.exists(full_path):
                                if verbose:
                                    print(f"Warning: {full_path} does not exist, skipping.")
                                continue
                            zipf.write(full_path, archive_path)
                            if verbose:
                                print(f"Adding {archive_path} (matched: {rel_for_match})")
                        else:
                            if verbose:
                                print(f"Excluded by .gitignore: {archive_path} (matched: {rel_for_match})")
        except PermissionError:
            if verbose:
                print(f"Permission denied: {current_dir}")

    with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
        process_directory(walk_root, start_relative, 0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zip a project directory.")
    parser.add_argument(
        "--dir2zip",
        type=Path,
        default=None,
        help="Path of the directory to zip (default: --start-dir if set, otherwise cwd)"
    )
    parser.add_argument(
        "--zipfile",
        type=Path,
        default=None,
        help="Path and name of the zip file to create (default: <dir2zip>.zip)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--no-top",
        action="store_true",
        help="Do not include the top-level directory in the zip archive."
    )
    parser.add_argument(
        "--follow-app-links",
        action="store_true",
        help="Follow symlinks residing in 'apps' and 'apps-pages' directories."
    )
    parser.add_argument(
        "--start-dir",
        type=Path,
        default=None,
        help="Optional path relative to --dir2zip to start zipping from (only that subtree is archived)."
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Directory name to exclude (can be specified multiple times)."
    )
    parser.add_argument(
        "--split-mb",
        type=float,
        default=None,
        help="Split the resulting zip into parts of at most this many megabytes (original zip is removed)."
    )
    args = parser.parse_args()

    root_dir = args.dir2zip or args.start_dir or Path.cwd()
    root_dir = root_dir.absolute()

    zip_file = args.zipfile
    if zip_file is None:
        zip_file = root_dir.with_suffix(".zip")
    zip_file = zip_file.absolute()
    verbose = args.verbose
    no_top = args.no_top
    follow_app_links = args.follow_app_links
    start_dir = args.start_dir
    extra_excludes = set(args.exclude_dir or [])
    split_mb = args.split_mb

    if start_dir is not None:
        start_dir = start_dir if start_dir.is_absolute() else (root_dir / start_dir)
        start_dir = start_dir.resolve()
        if not start_dir.exists():
            raise SystemExit(f"--start-dir does not exist: {start_dir}")
        try:
            start_dir.relative_to(root_dir)
        except ValueError:
            raise SystemExit("--start-dir must be inside --dir2zip")

    if verbose:
        print("Directory to zip:", root_dir)
        print("Zip file will be:", zip_file)
        print("No top directory:", no_top)
        if follow_app_links:
            print("Following symlinks for: apps, apps-pages")
        if args.start_dir is not None:
            print("Start directory:", start_dir)
        if extra_excludes:
            print("Excluding directories:", ", ".join(sorted(extra_excludes)))
        if split_mb:
            print(f"Splitting archive into parts <= {split_mb} MB")

    os.makedirs(zip_file.parent, exist_ok=True)

    top_gitignore = root_dir / ".gitignore"
    if top_gitignore.exists():
        top_spec = read_gitignore_cached(str(top_gitignore))
        if verbose:
            print(f"Using top-level .gitignore from {top_gitignore}")
            print("PATTERNS:", [p.pattern for p in top_spec.patterns])
    else:
        if verbose:
            print(f"No top-level .gitignore found at {top_gitignore}. No files will be filtered at this level.")
        top_spec = PathSpec.from_lines(GitWildMatchPattern, [])

    follow_names = FOLLOW_SYMLINK_NAMES_DEFAULT if follow_app_links else None

    zip_directory(str(root_dir), str(zip_file), top_spec, no_top, verbose, follow_names, start_dir, extra_excludes)
    print(f"Zipped {start_dir or root_dir} into {zip_file}")

    if split_mb:
        max_bytes = int(split_mb * 1024 * 1024)
        parts = split_file(zip_file, max_bytes, verbose)
        if parts:
            print("Created parts:")
            for part in parts:
                print(f" - {part}")
