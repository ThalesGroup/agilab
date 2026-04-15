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
import re
import stat
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

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)

def _ensure_hacl_dir(log=logger, path_factory=Path) -> None:
    hacl_dir = path_factory("Modules/_hacl")
    log.info(f"mkdir {hacl_dir}")
    try:
        hacl_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Non-fatal if directory can't be created (e.g., read-only env)
        pass


_ensure_hacl_dir()

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
        logger.info(f"mkdir {dest.parent}")
        dest.parent.mkdir(parents=True, exist_ok=True)

    if not dest.exists():
        AgiEnv.logger.info(f"Linking {src_abs} -> {dest}")
        if AgiEnv._is_managed_pc:
            try:
                AgiEnv.create_junction_windows(src_abs, dest)
            except OSError as link_err:
                AgiEnv.logger.error(f"Failed to create link from {src_abs} to {dest}: {link_err}")
                raise
        else:
            try:
                AgiEnv.create_symlink(src_abs, dest)
                created_links.append(dest)
                AgiEnv.logger.info(f"Symlink created: {dest} -> {src_abs}")
            except OSError as symlink_err:
                AgiEnv.logger.warning(f"Symlink creation failed: {symlink_err}. Trying hard link instead.")
                try:
                    os.link(src_abs, dest)
                    created_links.append(dest)
                    AgiEnv.logger.info(f"Hard link created: {dest} -> {src_abs}")
                except OSError as link_err:
                    AgiEnv.logger.error(f"Failed to create link from {src_abs} to {dest}: {link_err}")
                    raise
    else:
        AgiEnv.logger.debug(f"Link already exists for {dest}")

    return created_links


def _load_pre_install_module():
    from agi_node.agi_dispatcher import pre_install as pre_install_module

    return pre_install_module


def _resolve_pre_install_script(env) -> Path | None:
    raw_path = getattr(env, "pre_install", None)
    if raw_path:
        candidate = Path(raw_path)
        if candidate.exists():
            return candidate

    try:
        module_file = getattr(_load_pre_install_module(), "__file__", None)
        if module_file:
            return Path(module_file).resolve()
    except (ImportError, ModuleNotFoundError, OSError):
        pass

    return Path(raw_path) if raw_path else None


def cleanup_links(links: list[Path]) -> None:
    for link in links:
        try:
            if link.is_symlink() or link.exists():
                AgiEnv.logger.info(f"Removing link or file: {link}")
                if link.is_dir() and not link.is_symlink():
                    shutil.rmtree(link)
                else:
                    link.unlink()

            parent = link.parent
            while parent and parent.name:
                if parent.name == "agi_node" or \
                   (parent.parent and parent.parent.name == "agi_node"):
                    try:
                        if any(parent.iterdir()):
                            break
                        parent.rmdir()
                    except OSError:
                        break
                    parent = parent.parent
                    continue
                break
        except OSError as e:
            AgiEnv.logger.warning(f"Failed to remove {link}: {e}")

# Also scrub any hardcoded -L flags that point to nowhere
def _keep_lflag(arg: str) -> bool:
    if not arg.startswith("-L"):
        return True
    cand = arg[2:]
    return Path(cand).exists()


def _sanitize_build_ext_link_settings(
    library_dirs: list[str] | None = None,
    extra_link_args: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    sanitized_library_dirs = [
        path for path in (list(library_dirs) if library_dirs else []) if Path(path).exists()
    ]
    sanitized_extra_link_args = [
        arg for arg in (list(extra_link_args) if extra_link_args else []) if _keep_lflag(arg)
    ]
    return sanitized_library_dirs, sanitized_extra_link_args


def _build_ext_compile_config(
    *,
    sys_platform: str,
    pyvers_worker: str,
) -> tuple[list[str], list[tuple[str, str]], dict[str, bool]]:
    extra_compile_args: list[str] = []
    if sys_platform == "darwin":
        extra_compile_args.extend(
            ["-Wno-unknown-warning-option", "-Wno-unreachable-code-fallthrough"]
        )

    define_macros: list[tuple[str, str]] = [("CYTHON_FALLTHROUGH", "")]
    if sys_platform.startswith("win") and pyvers_worker.endswith("t"):
        define_macros.append(("Py_GIL_DISABLED", "1"))

    compiler_directives: dict[str, bool] = {}
    if pyvers_worker.endswith("t"):
        # free-threaded CPython compatibility
        compiler_directives = {"freethreading_compatible": True}

    return extra_compile_args, define_macros, compiler_directives


def _build_worker_extension(
    *,
    worker_module: str,
    src_rel: Path,
    prefix: Path,
    extra_compile_args: list[str],
    define_macros: list[tuple[str, str]],
    library_dirs: list[str],
    extra_link_args: list[str],
) -> Extension:
    return Extension(
        name=f"{worker_module}_cy",
        sources=[str(src_rel)],
        include_dirs=[str(prefix / "include")],
        extra_compile_args=extra_compile_args,
        define_macros=define_macros,
        library_dirs=library_dirs,
        extra_link_args=extra_link_args,
    )


def _cythonize_worker_extension(
    *,
    extension: Extension,
    compiler_directives: dict[str, bool],
    quiet: bool,
    cythonize_fn=None,
) -> list[Extension]:
    if cythonize_fn is None:
        cythonize_fn = cythonize
    return cythonize_fn(
        [extension],
        language_level=3,
        quiet=quiet,
        compiler_directives=compiler_directives,
    )


def _unpack_worker_eggs(
    *,
    dist_dir: Path,
    dest_src: Path,
    zip_cls=None,
    log=None,
) -> None:
    if zip_cls is None:
        zip_cls = ZipFile
    if log is None:
        log = AgiEnv.logger or logger
    log.info(f"mkdir {dest_src}")
    dest_src.mkdir(exist_ok=True, parents=True)
    for egg in dist_dir.glob("*.egg"):
        log.info(f"Unpacking {egg} -> {dest_src}")
        with zip_cls(egg, "r") as zf:
            zf.extractall(dest_src)


def _build_remove_decorators_command(worker_path: str) -> str:
    return (
        "uv -q run python -m agi_node.agi_dispatcher.pre_install remove_decorators "
        f'--worker_path "{worker_path}" --verbose'
    )


def _postprocess_bdist_egg_output(
    *,
    env,
    out_dir: Path,
    links_created: list[Path],
    cleanup_links_fn=None,
    os_system_fn=None,
    zip_cls=None,
    log=None,
) -> None:
    if cleanup_links_fn is None:
        cleanup_links_fn = cleanup_links
    if os_system_fn is None:
        os_system_fn = os.system
    if zip_cls is None:
        zip_cls = ZipFile
    if log is None:
        log = AgiEnv.logger or logger
    dest_src = out_dir / "src"
    _unpack_worker_eggs(dist_dir=out_dir / "dist", dest_src=dest_src, zip_cls=zip_cls, log=log)

    cmd = _build_remove_decorators_command(env.worker_path)
    log.info(f"Stripping decorators via:\n  {cmd}")
    os_system_fn(cmd)

    if links_created:
        cleanup_links_fn(links_created)
        log.info("Cleanup of created symlinks/files done.")


def _force_remove_tree(path: Path) -> None:
    if not path.exists():
        return
    try:
        os.chmod(path, stat.S_IRWXU)
    except OSError:
        pass
    if os.name != "nt":
        subprocess.run(["chmod", "-R", "u+rwx", str(path)], check=False, capture_output=True)
    shutil.rmtree(path)


def _purge_worker_venv_artifacts(app_root: Path, worker_module: str) -> list[Path]:
    """
    Remove nested worker virtualenvs that should never be packaged.

    A source-worker `pyproject.toml` makes `uv --project src/<worker>` create
    `src/<worker>/.venv`. If left behind, setuptools can copy it into `build/lib`
    and then repackage it into the worker egg, making step 9 appear frozen.
    """
    removed: list[Path] = []
    candidates = [
        app_root / "src" / worker_module / ".venv",
        app_root / "build" / "lib" / worker_module / ".venv",
    ]
    build_root = app_root / "build"
    if build_root.exists():
        candidates.extend(build_root.glob(f"bdist*/egg/{worker_module}/.venv"))
        candidates.extend(build_root.glob(f"bdist*/**/{worker_module}/.venv"))

    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve(strict=False)
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        logger.warning(f"Removing nested worker virtualenv before packaging: {candidate}")
        _force_remove_tree(candidate)
        removed.append(candidate)
    return removed

def _fix_windows_drive(path_str: str) -> str:
    """Insert a path separator after a Windows drive letter if missing.

    Example: 'C:Users\\me' -> 'C:\\Users\\me'.
    No-op on non-Windows or when already absolute.
    """
    if os.name == "nt" and isinstance(path_str, str):
        if re.match(r'^[A-Za-z]:(?![\\/])', path_str):
            return path_str[:2] + "\\" + path_str[2:]
    return path_str


def main(argv: list[str] | None = None) -> None:
    raw_args = sys.argv[1:] if argv is None else list(argv)
    prog_name = sys.argv[0]

    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--app-path", dest="app_path")
    global_args, remaining = pre_parser.parse_known_args(raw_args)

    if global_args.app_path:
        app_path_str = _fix_windows_drive(global_args.app_path)
        active_app = Path(app_path_str).expanduser().resolve()
    else:
        active_app = Path(__file__).parent.resolve()

    os.chdir(active_app)
    opts = parse_custom_args(remaining, active_app)
    # Normalise user-provided output dirs that may be missing the separator after the drive
    if getattr(opts, "build_dir", None):
        opts.build_dir = _fix_windows_drive(str(opts.build_dir))
    if getattr(opts, "dist_dir", None):
        opts.dist_dir = _fix_windows_drive(str(opts.dist_dir))
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
        active_app=active_app,
        verbose=verbose,
    )

    p = Path(outdir)
    if p.suffix and not p.is_dir():
        AgiEnv.logger.warning(f"'{outdir}' looks like a file; using its parent directory instead.")
        p = p.parent
    try:
        out_arg = p.relative_to(Path(env.home_abs)).as_posix()
    except ValueError:
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

        worker_py = Path(env.worker_path)
        if not worker_py.is_absolute():
            try:
                worker_py = (Path(env.home_abs) / worker_py).resolve()
            except OSError:
                worker_py = (Path.cwd() / worker_py).resolve()
        worker_pyx = worker_py.with_suffix('.pyx')
        pre_install_script = _resolve_pre_install_script(env)
        if not worker_pyx.exists() and pre_install_script:
            pre_cmd = [
                sys.executable,
                str(pre_install_script),
                "remove_decorators",
                "--worker_path",
                str(worker_py),
            ]
            if env.verbose:
                pre_cmd.append("--verbose")
            AgiEnv.logger.info("Ensuring Cython source via pre_install: %s", " ".join(pre_cmd))
            subprocess.run(pre_cmd, check=True)

    sys.argv = [prog_name, cmd, flag, Path(env.home_abs) / out_arg / "dist"]
    worker_module = target_module + "_worker"
    links_created: list[Path] = []
    ext_modules = []
    purged_venvs: list[Path] = []

    if not env.is_worker_env:
        purged_venvs = _purge_worker_venv_artifacts(env.active_app, worker_module)
        if purged_venvs:
            logger.info(
                "Purged nested worker virtualenv artifacts before %s: %s",
                cmd,
                ", ".join(str(path) for path in purged_venvs),
            )

    # Change directory to build_dir BEFORE setup if build_ext
    if cmd == 'build_ext':
        AgiEnv.logger.info(f"cwd: {active_app}")
        #os.chdir(opts.build_dir)
        AgiEnv.logger.info(f"build_dir: {opts.build_dir}")
        src_rel = Path("src") / worker_module / f"{worker_module}.pyx"
        prefix = Path(find_sys_prefix("~/MyApp"))

        # Seed from existing values if any; otherwise start empty
        library_dirs, extra_link_args = _sanitize_build_ext_link_settings(
            library_dirs if 'library_dirs' in locals() else None,
            extra_link_args if 'extra_link_args' in locals() else None,
        )

        extra_compile_args, define_macros, compil_directives = _build_ext_compile_config(
            sys_platform=sys.platform,
            pyvers_worker=env.pyvers_worker,
        )
        _ensure_hacl_dir()
        mod = _build_worker_extension(
            worker_module=worker_module,
            src_rel=src_rel,
            prefix=prefix,
            extra_compile_args=extra_compile_args,
            define_macros=define_macros,
            library_dirs=library_dirs,
            extra_link_args=extra_link_args,
        )

        ext_modules = _cythonize_worker_extension(
            extension=mod,
            compiler_directives=compil_directives,
            quiet=bool(opts.remaining and ("-q" in opts.remaining or "--quiet" in opts.remaining)),
        )
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
        _postprocess_bdist_egg_output(
            env=env,
            out_dir=Path(env.home_abs) / out_arg,
            links_created=links_created,
        )

if __name__ == "__main__":
    main()
