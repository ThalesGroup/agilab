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
import subprocess

from setuptools import setup, find_packages, Extension, SetuptoolsDeprecationWarning
from Cython.Build import cythonize


def _inject_shared_site_packages() -> None:
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        Path.home() / "agilab/.venv/lib" / version / "site-packages",
        Path.home() / ".agilab/.venv/lib" / version / "site-packages",
    ]
    for candidate in candidates:
        path_str = str(candidate)
        if path_str not in sys.path:
            sys.path.append(path_str)


_inject_shared_site_packages()

from agi_env import AgiEnv, normalize_path
from agi_env import AgiLogger
import warnings
warnings.filterwarnings("ignore", category=SetuptoolsDeprecationWarning)

try:
    from pathlib import Path as _Path
    _Path('Modules/_hacl').mkdir(parents=True, exist_ok=True)
except Exception:
    # Non-fatal if directory can't be created (e.g., read-only env)
    pass

def _relative_to_home(path: Path) -> Path:
    try:
        return path.relative_to(Path.home())
    except ValueError:
        return path


def parse_custom_args(raw_args: list[str], app_dir: Path) -> argparse.Namespace:
    """
    Parse custom CLI arguments and return an argparse Namespace.
    Known args:
      - packages: comma-separated list
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
    # install_type removed — environment flags in AgiEnv drive behavior now
    default_dir = _relative_to_home(app_dir)
    parser.add_argument(
        '--build-dir', '-b',
        dest='build_dir',
        default=default_dir,
        help='Output directory for build_ext (must be a directory)'
    )
    parser.add_argument(
        '--dist-dir', '-d',
        dest='dist_dir',
        help='Output directory for bdist_egg (must be a directory)',
        default=default_dir
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
        AgiEnv.logger.info(f"Found Python directory: {python_dirs[0]}")
        return str(python_dirs[0])
    return sys.prefix


def create_symlink_for_module(env, pck: str) -> list[Path]:
    # e.g. "node"
    pck_src = pck.replace('.', '/')            # -> Path("agi-core")/"workers"/"node"
    # extract "core" from "agi-core"
    pck_root = pck.split('.')[0]
    node_path = Path("src/agi_node")
    src_abs = env.agi_node / node_path / pck_src
    if pck_root == "agi_env":
        src_abs = env.agi_env / pck_src
        dest = Path("src") / pck_src
    elif pck_root == env.target_worker:
        src_abs = env.app_src / pck_src
        dest = Path("src") / pck_src
    else:
        dest = node_path / pck_src

    created_links: list[Path] = []
    try:
        dest = dest.absolute()
    except FileNotFoundError:
        AgiEnv.logger.error(f"Source path does not exist: {src_abs}")
        raise FileNotFoundError(f"Source path does not exist: {src_abs}")

    if not dest.parent.exists():
        AgiEnv.logger.info(f"Creating directory: {dest.parent}")
        dest.parent.mkdir(parents=True, exist_ok=True)

    if not dest.exists():
        AgiEnv.logger.info(f"Linking {src_abs} -> {dest}")
        if AgiEnv._is_managed_pc:
            try:
                AgiEnv.create_junction_windows(src_abs, dest)
            except Exception as link_err:
                AgiEnv.logger.error(f"Failed to create link from {src_abs} to {dest}: {link_err}")
                raise
        else:
            try:
                AgiEnv.create_symlink(src_abs, dest)
                created_links.append(dest)
                AgiEnv.logger.info(f"Symlink created: {dest} -> {src_abs}")
            except Exception as symlink_err:
                AgiEnv.logger.warning(f"Symlink creation failed: {symlink_err}. Trying hard link instead.")
                try:
                    os.link(src_abs, dest)
                    created_links.append(dest)
                    AgiEnv.logger.info(f"Hard link created: {dest} -> {src_abs}")
                except Exception as link_err:
                    AgiEnv.logger.error(f"Failed to create link from {src_abs} to {dest}: {link_err}")
                    raise
    else:
        AgiEnv.logger.debug(f"Link already exists for {dest}")

    return created_links

def cleanup_links(links: list[Path]) -> None:
    for link in links:
        try:
            if link.is_symlink() or link.exists():
                AgiEnv.logger.info(f"Removing link or file: {link}")
                if link.is_dir() and not link.is_symlink():
                    shutil.rmtree(link)
                else:
                    link.unlink()
        except Exception as e:
            AgiEnv.logger.warning(f"Failed to remove {link}: {e}")

# Also scrub any hardcoded -L flags that point to nowhere
def _keep_lflag(arg: str) -> bool:
    if not arg.startswith("-L"):
        return True
    cand = arg[2:]
    return Path(cand).exists()

def main(argv: list[str] | None = None) -> None:
    raw_args = sys.argv[1:] if argv is None else list(argv)
    prog_name = sys.argv[0]

    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--app-path", dest="app_path")
    global_args, remaining = pre_parser.parse_known_args(raw_args)

    if global_args.app_path:
        active_app = Path(global_args.app_path).expanduser().resolve()
    else:
        active_app = Path(__file__).parent.resolve()

    os.chdir(active_app)
    opts = parse_custom_args(remaining, active_app)
    cmd = opts.command
    quiet = True if opts.remaining and ("-q" in opts.remaining or "--quiet" in opts.remaining) else False
    packages = opts.packages
    # install_type removed

    outdir = opts.build_dir if cmd == "build_ext" else opts.dist_dir
    if not outdir:
        AgiEnv.logger.error("Cannot determine target package name.")
        raise RuntimeError("Cannot determine target package name")

    outdir = Path(outdir)
    name = outdir.name.removesuffix("_worker").removesuffix("_project")

    target_pkg = outdir.with_name(name)
    target_module = name.replace("-", "_")

    verbose = 0 if quiet else 2
    env = AgiEnv(
        apps_dir=active_app.parent,
        active_app=active_app.name,
        verbose=verbose,
    )

    p = Path(outdir)
    if p.suffix and not p.is_dir():
        AgiEnv.logger.warning(f"'{outdir}' looks like a file; using its parent directory instead.")
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
            AgiEnv.logger.error("build_ext requires --build-dir/-b argument")
            raise ValueError("build_ext requires --build-dir/-b argument")
        try:
            ext_path = truncate_path_at_segment(opts.build_dir)
        except ValueError as e:
            AgiEnv.logger.error(e)
            raise

        worker_py = env.worker_path
        worker_pyx = worker_py.with_suffix('.pyx')
        if not worker_pyx.exists() and env.pre_install:
            pre_cmd = [
                sys.executable,
                str(env.pre_install),
                "remove_decorators",
                "--worker_path",
                str(worker_py),
            ]
            if env.verbose:
                pre_cmd.append("--verbose")
            AgiEnv.logger.info("Ensuring Cython source via pre_install: %s", " ".join(pre_cmd))
            subprocess.run(pre_cmd, check=True)

    sys.argv = [prog_name, cmd, flag, env.home_abs / out_arg / "dist"]
    worker_module = target_module + "_worker"
    links_created: list[Path] = []
    ext_modules = []

    # Change directory to build_dir BEFORE setup if build_ext
    if cmd == 'build_ext':
        AgiEnv.logger.info(f"cwd: {active_app}")
        #os.chdir(opts.build_dir)
        AgiEnv.logger.info(f"build_dir: {opts.build_dir}")
        src_rel = Path("src") / worker_module / f"{worker_module}.pyx"
        prefix = Path(find_sys_prefix("~/MyApp"))

        # Seed from existing values if any; otherwise start empty
        library_dirs = list(library_dirs) if 'library_dirs' in locals() else []
        extra_link_args = list(extra_link_args) if 'extra_link_args' in locals() else []

        # Filter out non-existent directories and bogus -L flags
        library_dirs = [d for d in library_dirs if Path(d).exists()]

        def _keep_lflag(arg: str) -> bool:
            return not arg.startswith("-L") or Path(arg[2:]).exists()

        extra_link_args = [arg for arg in extra_link_args if _keep_lflag(arg)]

        # Compile flags: only add the Clang-specific one on macOS
        extra_compile_args = []
        if sys.platform == "darwin":
            extra_compile_args += ["-Wno-unknown-warning-option", "-Wno-unreachable-code-fallthrough"]

        define_macros = [("CYTHON_FALLTHROUGH", "")]
        if sys.platform.startswith("win") and env.pyvers_worker[-1] == "t":
            define_macros.append(("Py_GIL_DISABLED", "1"))

        os.makedirs(Path() /"Modules/_hacl", exist_ok=True)
        mod = Extension(
            name=f"{worker_module}_cy",
            sources=[str(src_rel)],
            include_dirs=[str(prefix / "include")],
            extra_compile_args=extra_compile_args,
            define_macros=define_macros,
            library_dirs=library_dirs,
            extra_link_args=extra_link_args,
        )

        compil_directives =  {}
        if env.pyvers_worker[-1] == "t":
            # free-threaded CPython compatibility
            compil_directives = {"freethreading_compatible": True}

        if (opts.remaining and ("-q" in opts.remaining or "--quiet" in opts.remaining)):
            ext_modules = cythonize([mod], language_level=3, quiet=True, compiler_directives=compil_directives)
        else:
            ext_modules = cythonize([mod], language_level=3, compiler_directives=compil_directives)
        AgiEnv.logger.info(f"Cython extension configured: {worker_module}_cy")

    elif not env.is_worker_env:
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
    if cmd == 'bdist_egg' and (not env.is_worker_env):
        out_dir = env.home_abs / out_arg
        dest_src =  out_dir / "src"
        dest_src.mkdir(exist_ok=True, parents=True)
        for egg in (out_dir / 'dist').glob("*.egg"):
            AgiEnv.logger.info(f"Unpacking {egg} -> {dest_src}")
            with ZipFile(egg, 'r') as zf:
                zf.extractall(dest_src)

        worker_py = dest_src / worker_module / f"{worker_module}.py"
        cmd = (
            f"uv -q run python -m agi_node.agi_dispatcher.pre_install remove_decorators "
            f"--worker_path '{env.worker_path}' --verbose"
        )
        AgiEnv.logger.info(f"Stripping decorators via:\n  {cmd}")
        os.system(cmd)

        # Cleanup copied modules
        if links_created:
            cleanup_links(links_created)
            AgiEnv.logger.info("Cleanup of created symlinks/files done.")

if __name__ == "__main__":
    main()
