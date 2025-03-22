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


def read_gitignore(gitignore_path):
    """
    Read a .gitignore file and create a PathSpec object from its patterns.

    :param gitignore_path: The path to the .gitignore file.
    :type gitignore_path: str

    :return: A PathSpec object containing the patterns from the .gitignore file.
    :rtype: PathSpec

    :raises FileNotFoundError: If the .gitignore file cannot be found.
    """
    with open(gitignore_path, "r") as f:
        patterns = f.read().splitlines()
    return PathSpec.from_lines(GitWildMatchPattern, patterns)


def should_include_file(filepath, spec):
    """
    Check if a file should be included based on a specified file matching criterion.

    Args:
        filepath (str): The path of the file to be checked.
        spec (PathSpec): An object representing the file matching criterion.

    Returns:
        bool: True if the file should be included, False otherwise.
    """
    return not spec.match_file(filepath)


def zip_directory(parent_dir, dir_path, zip_filepath, spec, no_top=False, verbose=False):
    """
    Zip a directory with filtering based on a specification.

    Args:
        parent_dir (str): The parent directory containing the directory to zip.
        dir_path (str): The directory to zip.
        zip_filepath (str): The output zip file path.
        spec (PathSpec): The file specification to filter which files to include in the zip.
        no_top (bool): If True, do not include the top-level directory in the archive.
        verbose (bool): If True, print verbose output.

    Returns:
        None

    Note:
        This function zips the contents of a directory while excluding files based on the spec.
        It also skips the output zip file if it is found inside the directory to avoid self-inclusion.
    """
    # Construct the full target directory path from the parent and the directory to zip.
    target_dir = os.path.join(parent_dir, dir_path)
    base_name = os.path.basename(dir_path)  # e.g. 'agig'

    # Get the absolute path of the zip file to compare later.
    output_zip_abs = os.path.abspath(zip_filepath)

    with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(target_dir):
            # Make paths relative to `target_dir` to avoid extra nesting in the archive.
            relative_dir = os.path.relpath(root, target_dir)

            # Skip .git directories.
            if relative_dir == ".git" or relative_dir.startswith(".git" + os.sep):
                continue

            for filename in files:
                file_path = os.path.join(root, filename)
                # Skip adding the zip file itself if it resides in the directory.
                if os.path.abspath(file_path) == output_zip_abs:
                    continue

                # Construct the relative file path inside the zip archive.
                if no_top:
                    # Without the top-level directory, use the relative path from target_dir.
                    if relative_dir == ".":
                        relative_file_path = filename
                    else:
                        relative_file_path = os.path.join(relative_dir, filename)
                else:
                    # Include the top-level directory in the archive.
                    if relative_dir == ".":
                        relative_file_path = os.path.join(base_name, filename)
                    else:
                        relative_file_path = os.path.join(base_name, relative_dir, filename)

                if should_include_file(relative_file_path, spec):
                    if verbose:
                        print(f"Adding {relative_file_path} to zipfile")
                    zipf.write(file_path, relative_file_path)
                else:
                    if verbose:
                        print(f"Excluded by .gitignore: {relative_file_path}")


if __name__ == "__main__":
    """
    Zip a directory into a zip file.

    Usage: zip-agi --dir2zip <dir> --zipfile <file> [--no-top] [--verbose|-v]
      --dir2zip: Path of the directory to zip (mandatory)
      --zipfile: Path and name of the zip file to create (mandatory)
      --no-top: Do not include the top-level directory in the zip archive.
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

    # Convert to absolute paths if not already
    project_dir = args.dir2zip.absolute()
    zip_file = args.zipfile.absolute()
    verbose = args.verbose
    no_top = args.no_top

    if verbose:
        print("Directory to zip:", project_dir)
        print("Zip file will be:", zip_file)
        print("No top directory:" , no_top)

    parent_dir = project_dir.parent
    os.makedirs(zip_file.parent, exist_ok=True)

    gitignore_path = project_dir / ".gitignore"
    if not gitignore_path.exists():
        print(f"No .gitignore file found at {gitignore_path}.")
    else:
        # Generate the file matching specification from the .gitignore file.
        spec = read_gitignore(gitignore_path)
        # Pass the no_top flag to the zip_directory function.
        zip_directory(str(parent_dir), str(project_dir), str(zip_file), spec, no_top, verbose)
        print(f"Zipped {project_dir} into {zip_file}")