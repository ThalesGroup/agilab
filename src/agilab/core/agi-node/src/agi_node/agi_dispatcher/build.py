#!/usr/bin/env python3
"""
AGI app setup
Author: Jean-Pierre Morard
Tested on Windows, Linux and MacOS
"""
import getpass
import sys
import os
import shutil
import logging
from pathlib import Path
from zipfile import ZipFile
import argparse

from setuptools import setup, find_packages, Extension, SetuptoolsDeprecationWarning
from Cython.Build import cythonize
from agi_env import AgiEnv, normalize_path
import warnings
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=SetuptoolsDeprecationWarning)



def parse_custom_args(raw_args: list[str], cwd) -> argparse.Namespace:
    """
    Parse custom CLI arguments and return an argparse Namespace.
    Known args:
      - packages: comma-separated list
      - install_type: integer install type
      - build_dir: output directory for build_ext (alias -b)
      - dist_dir: output directory for bdist_egg (alias -d)
      - command: setup command ("build_ext" or "bdist_egg")
    Unknown args are left in remaining.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('command', choices=['build_ext', 'bdist_egg'])
    parser.add_argument(
        '--packages', '-p',
        type=lambda s: [pkg.strip() for pkg in s.split(',') if pkg.strip()],
        default=[]
    )
    parser.add_argument(
        '--install-type', '-i',
        dest='install_type',
        type=int,
        default=1
    )
    parser.add_argument(
        '--build-dir', '-b',
        dest='build_dir',
        default=cwd.relative_to(Path().home()),
        help='Output directory for build_ext (must be a directory)'
    )
    parser.add_argument(
        '--dist-dir', '-d',
        dest='dist_dir',
        help='Output directory for bdist_egg (must be a directory)',
        default=cwd.relative_to(Path().home())
    )
    known, remaining = parser.parse_known_args(raw_args)
    known.remaining = remaining

    if known.command == 'build_ext' and not known.build_dir:
        parser.error("'build_ext' requires --build-dir / -b <out-dir>")
    if known.command == 'bdist_egg' and not known.dist_dir:
        parser.error("'bdist_egg' requires --dist-dir / -d <out-dir>")

    return known


def truncate_path_at_segment(
        path_str: str,
        segment: str = "_worker",
        exact_match: bool = False,
        multiple: bool = False,
) -> Path:
    """
    Return the Path up through the last directory whose name ends with `segment`,
    e.g. '/foo/flight_worker/bar.py' → '/foo/flight_worker'.

    exact_match and multiple are kept for signature compatibility but ignored,
    since we want any dir name ending in segment.
    """
    parts = Path(path_str).parts
    # find all indices where the directory name ends with our segment
    idxs = [i for i, p in enumerate(parts) if p.endswith(segment)]
    if not idxs:
        raise ValueError(f"No directory ending with '{segment}' found in '{path_str}'")
    # pick the last occurrence
    idx = idxs[-1]
    return Path(*parts[: idx + 1])


def find_sys_prefix(base_dir: str) -> str:
    base = Path(base_dir).expanduser()
    python_dirs = sorted(base.glob("Python???"))
    if python_dirs:
        logging.info(f"Found Python directory: {python_dirs[0]}")
        return str(python_dirs[0])
    return sys.prefix


def create_symlink_for_module(env, pck: str) -> list[Path]:
    # e.g. "node"
    pck_src = pck.replace('.', '/')            # -> Path("agi-core")/"workers"/"node"
    # extract "core" from "agi-core"
    pck_root = pck.split('.')[0]
    src_abs = env.node_root / "src/agi_node" / pck_src
    if pck_root == "agi_env":
        src_abs = env.env_src / pck_src
    elif pck_root == env.target_worker:
        src_abs = env.app_src / pck_src

    dest = Path('src') / pck_src
    created_links: list[Path] = []
    try:
        dest = dest.absolute()
    except FileNotFoundError:
        logging.error(f"Source path does not exist: {src_abs}")
        sys.exit(1)

    if not dest.parent.exists():
        logging.info(f"Creating directory: {dest.parent}")
        dest.parent.mkdir(parents=True, exist_ok=True)

    if not dest.exists():
        logging.info(f"Linking {src_abs} -> {dest}")
        if AgiEnv.is_managed_pc:
            try:
                AgiEnv.create_junction_windows(src_abs, dest)
            except Exception as link_err:
                logging.error(f"Failed to create link from {src_abs} to {dest}: {link_err}")
                sys.exit(1)
        else:
            try:
                AgiEnv.create_symlink(src_abs, dest)
                created_links.append(dest)
                logging.info(f"Symlink created: {dest} -> {src_abs}")
            except Exception as symlink_err:
                logging.warning(f"Symlink creation failed: {symlink_err}. Trying hard link instead.")
                try:
                    os.link(src_abs, dest)
                    created_links.append(dest)
                    logging.info(f"Hard link created: {dest} -> {src_abs}")
                except Exception as link_err:
                    logging.error(f"Failed to create link from {src_abs} to {dest}: {link_err}")
                    sys.exit(1)
    else:
        logging.debug(f"Link already exists for {dest}")

    return created_links

def cleanup_links(links: list[Path]) -> None:
    for link in links:
        try:
            if link.is_symlink() or link.exists():
                logging.info(f"Removing link or file: {link}")
                if link.is_dir() and not link.is_symlink():
                    shutil.rmtree(link)
                else:
                    link.unlink()
        except Exception as e:
            logging.warning(f"Failed to remove {link}: {e}")

def main() -> None:
    active_app = Path(__file__).parent
    os.chdir(active_app)
    opts = parse_custom_args(sys.argv[1:], active_app)
    cmd = opts.command
    packages = opts.packages
    install_type = opts.install_type

    outdir = opts.build_dir if cmd == "build_ext" else opts.dist_dir
    if not outdir:
        logging.error("Cannot determine target package name.")
        sys.exit(1)

    outdir = Path(outdir)
    name = outdir.name.removesuffix("_worker").removesuffix("_project")

    target_pkg = outdir.with_name(name)
    target_module = name.replace("-", "_")

    env = AgiEnv(active_app=active_app, install_type=install_type)

    p = Path(outdir)
    if p.suffix and not p.is_dir():
        logging.warning(f"'{outdir}' looks like a file; using its parent directory instead.")
        p = p.parent
    try:
        out_arg = p.relative_to(env.home_abs).as_posix()
    except Exception:
        out_arg = str(p)

    # Rebuild sys.argv for setuptools with correct flags
    flag = '-b' if cmd == 'build_ext' else '-d'

    # ext_path only relevant for build_ext
    ext_path = None
    if cmd == 'build_ext':
        if not opts.build_dir:
            logging.error("build_ext requires --build-dir/-b argument")
            sys.exit(1)
        try:
            ext_path = truncate_path_at_segment(opts.build_dir)
        except ValueError as e:
            logging.error(e)
            sys.exit(1)

    sys.argv = [sys.argv[0], cmd, flag, env.home_abs / out_arg / "dist"]
    worker_module = target_module + "_worker"
    links_created: list[Path] = []
    ext_modules = []

    # Change directory to build_dir BEFORE setup if build_ext
    if cmd == 'build_ext':
        logging.info(f"cwd: {active_app}")
        #os.chdir(opts.build_dir)
        logging.info(f"build_dir: {opts.build_dir}")
        src_rel = Path("src") / worker_module / f"{worker_module}.pyx"
        prefix = Path(find_sys_prefix("~/MyApp"))
        mod = Extension(
            name=worker_module + '_cy',
            sources=[str(src_rel)],
            include_dirs=[str(prefix / "include")],
            library_dirs=[str(prefix / sys.platlibdir)],
        )
        ext_modules = cythonize([mod], language_level=3)
        logging.info(f"Cython extension configured: {worker_module}_cy")

    elif install_type != 2:
        # For bdist_egg copy modules under src
        os.chdir(env.active_app)
        for module in packages:
            links_created.extend(create_symlink_for_module(env, module))

    # Discover packages and combine with custom modules
    package_dir = {'': 'src'}
    found_pkgs = find_packages(where='src')

    # TO SUPPRESS WARNING
    readme = "README.md"
    if not Path(readme).exists():
        with open(readme, "w", encoding="utf-8") as f:
            f.write("a README.md file is required")

    # Now call setup()
    setup(
        name=worker_module,
        version="0.1.0",
        package_dir=package_dir,
        packages=found_pkgs,
        include_package_data=True,
        package_data={'': ['*.7z']},
        ext_modules=ext_modules,
        zip_safe=False,
    )

    # Post bdist_egg steps: unpack, decorator stripping, cleanup
    if cmd == 'bdist_egg' and install_type != 2:
        out_dir = env.home_abs / out_arg
        dest_src =  out_dir / "src"
        dest_src.mkdir(exist_ok=True, parents=True)
        for egg in (out_dir / 'dist').glob("*.egg"):
            logging.info(f"Unpacking {egg} -> {dest_src}")
            with ZipFile(egg, 'r') as zf:
                zf.extractall(dest_src)

        worker_py = dest_src / worker_module / f"{worker_module}.py"
        cmd = (
            f"uv -q run python \"{env.pre_install}\" remove_decorators "
            f"--worker_path \"{env.worker_path}\" --verbose"
        )
        logging.info(f"Stripping decorators via:\n  {cmd}")
        os.system(cmd)

        # Cleanup copied modules
        if links_created:
            cleanup_links(links_created)
            logging.info("Cleanup of created symlinks/files done.")

if __name__ == "__main__":
    main()
