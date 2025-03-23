for root, dirs, files in os.walk(target_dir):
    # Make paths relative to `target_dir`
    relative_dir = os.path.relpath(root, target_dir)

    # Skip .git directories.
    if relative_dir == ".git" or relative_dir.startswith(".git" + os.sep):
        continue

    # Check if this directory has its own .gitignore; if so, use it.
    local_gitignore = os.path.join(root, ".gitignore")
    if os.path.exists(local_gitignore):
        local_spec = read_gitignore(local_gitignore)
        # You might want to merge it with the parent spec if desired.
    else:
        # Fall back to the spec from the top-level .gitignore (if it exists)
        local_spec = spec

    for filename in files:
        file_path = os.path.join(root, filename)
        # Skip adding the zip file itself if it resides in the directory.
        if os.path.abspath(file_path) == output_zip_abs:
            continue

        # Compute the file path relative to the project directory
        rel_file = os.path.relpath(file_path, start=project_dir)
        if no_top:
            relative_file_path = rel_file
        else:
            relative_file_path = os.path.join(os.path.basename(project_dir), rel_file)

        if should_include_file(relative_file_path, local_spec):
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