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
import zipfile
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
import argparse
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=None)
def read_gitignore_cached(gitignore_path):
    """
    Read a .gitignore file and create a PathSpec object from its patterns,
    caching the result for efficiency.
    """
    try:
        with open(gitignore_path, "r") as f:
            patterns = f.read().splitlines()
        return PathSpec.from_lines(GitWildMatchPattern, patterns)
    except FileNotFoundError:
        # If the file doesn't exist, return an empty spec.
        return PathSpec.from_lines(GitWildMatchPattern, [])

def should_include_file(filepath, spec):
    """
    Check if a file should be included based on the file matching criterion.
    """
    return not spec.match_file(filepath)

def zip_directory(target_dir, zip_filepath, top_spec, no_top=False, verbose=False):
    """
    Zip a directory while filtering files using .gitignore files.
    Uses a cached lookup for local .gitignore files and a recursive
    directory traversal with os.scandir for improved performance.
    """
    target_dir = os.path.abspath(target_dir)
    base_name = os.path.basename(target_dir)
    output_zip_abs = os.path.abspath(zip_filepath)

    with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
        def process_directory(current_dir, relative_to):
            try:
                with os.scandir(current_dir) as it:
                    # Check for a local .gitignore once per directory.
                    gitignore_path = os.path.join(current_dir, ".gitignore")
                    if os.path.exists(gitignore_path):
                        local_spec = read_gitignore_cached(gitignore_path)
                        # For matching, use paths relative to the current directory.
                        match_base = current_dir
                        if verbose:
                            print(f"Using local .gitignore from {current_dir}")
                    else:
                        local_spec = top_spec
                        match_base = target_dir

                    for entry in it:
                        full_path = os.path.join(current_dir, entry.name)
                        # Skip zip file self-inclusion.
                        if os.path.abspath(full_path) == output_zip_abs:
                            continue

                        # Skip .git directories.
                        if entry.is_dir(follow_symlinks=False) and entry.name == ".git":
                            continue

                        if entry.is_dir(follow_symlinks=False):
                            # Recurse into the directory.
                            process_directory(full_path, os.path.join(relative_to, entry.name))
                        else:
                            # Compute the path for matching relative to match_base.
                            rel_for_match = os.path.relpath(full_path, start=match_base)
                            # Compute the archive path.
                            if no_top:
                                archive_path = os.path.join(relative_to, entry.name)
                            else:
                                archive_path = os.path.join(base_name, relative_to, entry.name)

                            if should_include_file(rel_for_match, local_spec):
                                if verbose:
                                    print(f"Adding {archive_path} (matched: {rel_for_match})")
                                zipf.write(full_path, archive_path)
                            else:
                                if verbose:
                                    print(f"Excluded by .gitignore: {archive_path} (matched: {rel_for_match})")
            except PermissionError:
                if verbose:
                    print(f"Permission denied: {current_dir}")

        # Start processing from the target directory.
        process_directory(target_dir, "")

if __name__ == "__main__":
    """
    Zip a directory into a zip file.

    Usage: zip-agi --dir2zip <dir> --zipfile <file> [--no-top] [--verbose|-v]
    """
    parser = argparse.ArgumentParser(description="Zip a project directory.")
    parser.add_argument(
        "--dir2zip",
        type=Path,
        required=True,
        help="Path of the directory to zip"
    )
    parser.add_argument(
        "--zipfile",
        type=Path,
        required=True,
        help="Path and name of the zip file to create"
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
    args = parser.parse_args()

    project_dir = args.dir2zip.absolute()
    zip_file = args.zipfile.absolute()
    verbose = args.verbose
    no_top = args.no_top

    if verbose:
        print("Directory to zip:", project_dir)
        print("Zip file will be:", zip_file)
        print("No top directory:", no_top)

    os.makedirs(zip_file.parent, exist_ok=True)

    # Read the top-level .gitignore if it exists; otherwise, use an empty spec.
    top_gitignore = project_dir / ".gitignore"
    if top_gitignore.exists():
        top_spec = read_gitignore_cached(str(top_gitignore))
        if verbose:
            print(f"Using top-level .gitignore from {top_gitignore}")
    else:
        if verbose:
            print(f"No top-level .gitignore found at {top_gitignore}. No files will be filtered at this level.")
        top_spec = PathSpec.from_lines(GitWildMatchPattern, [])

    zip_directory(str(project_dir), str(zip_file), top_spec, no_top, verbose)
    print(f"Zipped {project_dir} into {zip_file}")
