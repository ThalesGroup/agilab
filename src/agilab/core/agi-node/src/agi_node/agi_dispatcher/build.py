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
from collections.abc import Mapping

try:
    from .bootstrap_source_paths import bootstrap_core_source_paths
except ImportError:  # pragma: no cover - script execution fallback
    from bootstrap_source_paths import bootstrap_core_source_paths

bootstrap_core_source_paths(source_file=__file__)

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


_CYTHON_CACHE_DISABLED_VALUES = {"0", "false", "no", "off", "disable", "disabled"}
_CYTHON_CACHE_ENABLED_VALUES = {"1", "true", "yes", "on", "enable", "enabled"}
_TOP_LEVEL_UI_MODULE_PATTERNS = ("app_args_form.py", "*_args_form.py")
_TOP_LEVEL_UI_BYTECODE_PATTERNS = ("app_args_form.*.pyc", "*_args_form.*.pyc")


def _resolve_cython_cache_option(
    *,
    environ: Mapping[str, str] | None = None,
    path_cls=Path,
) -> str | bool:
    """Return the cythonize cache setting used to avoid repeated .pyx conversion."""
    if environ is None:
        environ = os.environ

    raw_value = environ.get("AGILAB_CYTHON_CACHE", "").strip()
    default_cache_dir = path_cls.home() / ".cache" / "agilab" / "cython"
    if not raw_value or raw_value.lower() in _CYTHON_CACHE_ENABLED_VALUES:
        return str(default_cache_dir)
    if raw_value.lower() in _CYTHON_CACHE_DISABLED_VALUES:
        return False
    return str(path_cls(raw_value).expanduser())


def _cythonize_worker_extension(
    *,
    extension: Extension,
    compiler_directives: dict[str, bool],
    quiet: bool,
    cythonize_fn=None,
    resolve_cython_cache_option_fn=None,
) -> list[Extension]:
    if cythonize_fn is None:
        cythonize_fn = cythonize
    if resolve_cython_cache_option_fn is None:
        resolve_cython_cache_option_fn = _resolve_cython_cache_option
    return cythonize_fn(
        [extension],
        language_level=3,
        quiet=quiet,
        compiler_directives=compiler_directives,
        cache=resolve_cython_cache_option_fn(),
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
    _remove_top_level_ui_modules(dest_src, log=log)


def _remove_top_level_ui_modules(dest_src: Path, *, log=None) -> list[Path]:
    """Remove stale UI-only top-level modules from headless worker sources."""
    if log is None:
        log = AgiEnv.logger or logger
    removed: list[Path] = []

    for pattern in _TOP_LEVEL_UI_MODULE_PATTERNS:
        for candidate in dest_src.glob(pattern):
            if candidate.is_file():
                candidate.unlink()
                removed.append(candidate)

    pycache_dir = dest_src / "__pycache__"
    if pycache_dir.exists():
        for pattern in _TOP_LEVEL_UI_BYTECODE_PATTERNS:
            for candidate in pycache_dir.glob(pattern):
                if candidate.is_file():
                    candidate.unlink()
                    removed.append(candidate)
        try:
            pycache_dir.rmdir()
        except OSError:
            pass

    for candidate in removed:
        log.info(f"Removed UI-only worker artifact: {candidate}")
    return removed


def _purge_top_level_ui_build_artifacts(app_root: Path, *, log=None) -> list[Path]:
    """Drop stale top-level UI modules from setuptools build caches."""
    if log is None:
        log = AgiEnv.logger or logger
    build_root = app_root / "build"
    if not build_root.exists():
        return []

    candidates = [build_root / "lib"]
    candidates.extend(build_root.glob("bdist*/egg"))
    candidates.extend(build_root.glob("bdist*/**/egg"))

    removed: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve(strict=False)
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        removed.extend(_remove_top_level_ui_modules(candidate, log=log))
    return removed


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


def _resolve_worker_python_path(env) -> Path:
    worker_py = Path(env.worker_path)
    if worker_py.is_absolute():
        return worker_py
    try:
        return (Path(env.home_abs) / worker_py).resolve()
    except OSError:
        return (Path.cwd() / worker_py).resolve()


def _build_pre_install_command(
    *,
    pre_install_script: Path,
    worker_py: Path,
    verbose: int | bool,
) -> list[str]:
    cmd = [
        sys.executable,
        str(pre_install_script),
        "remove_decorators",
        "--worker_path",
        str(worker_py),
    ]
    if verbose:
        cmd.append("--verbose")
    return cmd


def _ensure_worker_cython_source(
    env,
    *,
    resolve_pre_install_script_fn=None,
    subprocess_run=None,
    log=None,
) -> None:
    if resolve_pre_install_script_fn is None:
        resolve_pre_install_script_fn = _resolve_pre_install_script
    if subprocess_run is None:
        subprocess_run = subprocess.run
    if log is None:
        log = AgiEnv.logger or logger

    worker_py = _resolve_worker_python_path(env)
    worker_pyx = worker_py.with_suffix(".pyx")
    pre_install_script = resolve_pre_install_script_fn(env)
    if worker_pyx.exists() or not pre_install_script:
        return

    pre_cmd = _build_pre_install_command(
        pre_install_script=pre_install_script,
        worker_py=worker_py,
        verbose=env.verbose,
    )
    log.info("Ensuring Cython source via pre_install: %s", " ".join(pre_cmd))
    subprocess_run(pre_cmd, check=True)


def _resolve_build_output(
    outdir,
    *,
    home_abs: str | Path,
    log=None,
) -> tuple[Path, str, str]:
    if log is None:
        log = AgiEnv.logger or logger
    if not outdir:
        log.error("Cannot determine target package name.")
        raise RuntimeError("Cannot determine target package name")

    outdir_path = Path(outdir)
    target_name = outdir_path.name.removesuffix("_worker").removesuffix("_project")
    target_module = target_name.replace("-", "_")

    normalized_outdir = outdir_path
    if normalized_outdir.suffix and not normalized_outdir.is_dir():
        log.warning(f"'{outdir}' looks like a file; using its parent directory instead.")
        normalized_outdir = normalized_outdir.parent

    try:
        out_arg = normalized_outdir.relative_to(Path(home_abs)).as_posix()
    except ValueError:
        out_arg = str(normalized_outdir)

    return outdir_path, out_arg, target_module


def _build_setuptools_argv(
    *,
    prog_name: str,
    command: str,
    home_abs: str | Path,
    out_arg: str,
) -> list[object]:
    flag = "-b" if command == "build_ext" else "-d"
    return [prog_name, command, flag, Path(home_abs) / out_arg / "dist"]


def _ensure_build_readme(readme_path: Path | str = "README.md") -> Path:
    readme = Path(readme_path)
    if not readme.exists():
        with open(readme, "w", encoding="utf-8") as f:
            f.write("a README.md file is required")
    return readme


def _build_setup_kwargs(
    *,
    worker_module: str,
    ext_modules: list,
    find_packages_fn=None,
) -> dict:
    if find_packages_fn is None:
        find_packages_fn = find_packages
    return {
        "name": worker_module,
        "version": "0.1.0",
        "package_dir": {"": "src"},
        "packages": find_packages_fn(where="src"),
        # Dask imports uploaded top-level py_modules; worker eggs must stay headless.
        "py_modules": [],
        "include_package_data": True,
        "package_data": {"": ["*.7z"]},
        "ext_modules": ext_modules,
        "zip_safe": False,
    }


def _configure_build_ext_modules(
    *,
    active_app: Path,
    build_dir: str,
    remaining_args: list[str],
    worker_module: str,
    pyvers_worker: str,
    find_sys_prefix_fn=None,
    sanitize_build_ext_link_settings_fn=None,
    build_ext_compile_config_fn=None,
    ensure_hacl_dir_fn=None,
    build_worker_extension_fn=None,
    cythonize_worker_extension_fn=None,
    log=None,
) -> list:
    if find_sys_prefix_fn is None:
        find_sys_prefix_fn = find_sys_prefix
    if sanitize_build_ext_link_settings_fn is None:
        sanitize_build_ext_link_settings_fn = _sanitize_build_ext_link_settings
    if build_ext_compile_config_fn is None:
        build_ext_compile_config_fn = _build_ext_compile_config
    if ensure_hacl_dir_fn is None:
        ensure_hacl_dir_fn = _ensure_hacl_dir
    if build_worker_extension_fn is None:
        build_worker_extension_fn = _build_worker_extension
    if cythonize_worker_extension_fn is None:
        cythonize_worker_extension_fn = _cythonize_worker_extension
    if log is None:
        log = AgiEnv.logger or logger

    log.info(f"cwd: {active_app}")
    log.info(f"build_dir: {build_dir}")
    src_rel = Path("src") / worker_module / f"{worker_module}.pyx"
    prefix = Path(find_sys_prefix_fn("~/MyApp"))
    library_dirs, extra_link_args = sanitize_build_ext_link_settings_fn(None, None)
    extra_compile_args, define_macros, compil_directives = build_ext_compile_config_fn(
        sys_platform=sys.platform,
        pyvers_worker=pyvers_worker,
    )
    ensure_hacl_dir_fn()
    mod = build_worker_extension_fn(
        worker_module=worker_module,
        src_rel=src_rel,
        prefix=prefix,
        extra_compile_args=extra_compile_args,
        define_macros=define_macros,
        library_dirs=library_dirs,
        extra_link_args=extra_link_args,
    )
    ext_modules = cythonize_worker_extension_fn(
        extension=mod,
        compiler_directives=compil_directives,
        quiet=bool(remaining_args and ("-q" in remaining_args or "--quiet" in remaining_args)),
    )
    log.info(f"Cython extension configured: {worker_module}_cy")
    return ext_modules


def _prepare_bdist_egg_sources(
    *,
    env,
    packages: list[str],
    create_symlink_for_module_fn=None,
    chdir_fn=None,
) -> list[Path]:
    if create_symlink_for_module_fn is None:
        create_symlink_for_module_fn = create_symlink_for_module
    if chdir_fn is None:
        chdir_fn = os.chdir

    chdir_fn(env.active_app)
    links_created: list[Path] = []
    for module in packages:
        links_created.extend(create_symlink_for_module_fn(env, module))
    return links_created


def _prepare_build_ext_command(
    *,
    env,
    build_dir: str | None,
    truncate_path_at_segment_fn=None,
    ensure_worker_cython_source_fn=None,
    log=None,
) -> None:
    if truncate_path_at_segment_fn is None:
        truncate_path_at_segment_fn = truncate_path_at_segment
    if ensure_worker_cython_source_fn is None:
        ensure_worker_cython_source_fn = _ensure_worker_cython_source
    if log is None:
        log = AgiEnv.logger or logger

    if not build_dir:
        log.error("build_ext requires --build-dir/-b argument")
        raise ValueError("build_ext requires --build-dir/-b argument")

    try:
        truncate_path_at_segment_fn(build_dir)
    except ValueError as err:
        log.error(err)
        raise

    ensure_worker_cython_source_fn(env)


def _prepare_setup_artifacts(
    *,
    env,
    cmd: str,
    active_app: Path,
    build_dir: str | None,
    remaining_args: list[str],
    packages: list[str],
    worker_module: str,
    purge_worker_venv_artifacts_fn=None,
    purge_top_level_ui_build_artifacts_fn=None,
    configure_build_ext_modules_fn=None,
    prepare_bdist_egg_sources_fn=None,
    log=None,
) -> tuple[list, list[Path]]:
    if purge_worker_venv_artifacts_fn is None:
        purge_worker_venv_artifacts_fn = _purge_worker_venv_artifacts
    if purge_top_level_ui_build_artifacts_fn is None:
        purge_top_level_ui_build_artifacts_fn = _purge_top_level_ui_build_artifacts
    if configure_build_ext_modules_fn is None:
        configure_build_ext_modules_fn = _configure_build_ext_modules
    if prepare_bdist_egg_sources_fn is None:
        prepare_bdist_egg_sources_fn = _prepare_bdist_egg_sources
    if log is None:
        log = logger

    links_created: list[Path] = []
    ext_modules: list = []

    if not env.is_worker_env:
        purged_venvs = purge_worker_venv_artifacts_fn(env.active_app, worker_module)
        if purged_venvs:
            log.info(
                "Purged nested worker virtualenv artifacts before %s: %s",
                cmd,
                ", ".join(str(path) for path in purged_venvs),
            )
        purged_ui_modules = purge_top_level_ui_build_artifacts_fn(env.active_app, log=log)
        if purged_ui_modules:
            log.info(
                "Purged top-level UI modules before %s: %s",
                cmd,
                ", ".join(str(path) for path in purged_ui_modules),
            )

    if cmd == "build_ext":
        ext_modules = configure_build_ext_modules_fn(
            active_app=active_app,
            build_dir=build_dir,
            remaining_args=remaining_args,
            worker_module=worker_module,
            pyvers_worker=env.pyvers_worker,
        )
    elif not env.is_worker_env:
        links_created = prepare_bdist_egg_sources_fn(env=env, packages=packages)

    return ext_modules, links_created


def _finalize_setup_artifacts(
    *,
    env,
    cmd: str,
    out_arg: str,
    links_created: list[Path],
    postprocess_bdist_egg_output_fn=None,
) -> None:
    if postprocess_bdist_egg_output_fn is None:
        postprocess_bdist_egg_output_fn = _postprocess_bdist_egg_output

    if cmd == "bdist_egg" and not env.is_worker_env:
        postprocess_bdist_egg_output_fn(
            env=env,
            out_dir=Path(env.home_abs) / out_arg,
            links_created=links_created,
        )


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


def _resolve_main_inputs(
    argv: list[str] | None = None,
    *,
    file_path: str | Path | None = None,
    argv0: str | None = None,
    chdir_fn=None,
) -> tuple[str, Path, argparse.Namespace, bool, str, list[str], str | None]:
    if chdir_fn is None:
        chdir_fn = os.chdir

    raw_args = sys.argv[1:] if argv is None else list(argv)
    prog_name = sys.argv[0] if argv0 is None else argv0
    file_path = __file__ if file_path is None else file_path

    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--app-path", dest="app_path")
    global_args, remaining = pre_parser.parse_known_args(raw_args)

    if global_args.app_path:
        app_path_str = _fix_windows_drive(global_args.app_path)
        active_app = Path(app_path_str).expanduser().resolve()
    else:
        active_app = Path(file_path).parent.resolve()

    chdir_fn(active_app)
    opts = parse_custom_args(remaining, active_app)
    if getattr(opts, "build_dir", None):
        opts.build_dir = _fix_windows_drive(str(opts.build_dir))
    if getattr(opts, "dist_dir", None):
        opts.dist_dir = _fix_windows_drive(str(opts.dist_dir))

    quiet = bool(opts.remaining and ("-q" in opts.remaining or "--quiet" in opts.remaining))
    cmd = opts.command
    packages = opts.packages
    raw_outdir = opts.build_dir if cmd == "build_ext" else opts.dist_dir

    return prog_name, active_app, opts, quiet, cmd, packages, raw_outdir


def _prepare_main_execution(
    *,
    prog_name: str,
    active_app: Path,
    quiet: bool,
    cmd: str,
    raw_outdir: str | None,
    build_dir: str | None,
    remaining_args: list[str],
    packages: list[str],
    build_env_cls=None,
    resolve_build_output_fn=None,
    prepare_build_ext_command_fn=None,
    build_setuptools_argv_fn=None,
    prepare_setup_artifacts_fn=None,
    set_argv_fn=None,
) -> tuple[object, str, str, list, list[Path]]:
    if build_env_cls is None:
        build_env_cls = AgiEnv
    if resolve_build_output_fn is None:
        resolve_build_output_fn = _resolve_build_output
    if prepare_build_ext_command_fn is None:
        prepare_build_ext_command_fn = _prepare_build_ext_command
    if build_setuptools_argv_fn is None:
        build_setuptools_argv_fn = _build_setuptools_argv
    if prepare_setup_artifacts_fn is None:
        prepare_setup_artifacts_fn = _prepare_setup_artifacts
    if set_argv_fn is None:
        set_argv_fn = lambda argv: setattr(sys, "argv", argv)

    verbose = 0 if quiet else 2
    env = build_env_cls(
        active_app=active_app,
        verbose=verbose,
    )

    _, out_arg, target_module = resolve_build_output_fn(
        raw_outdir,
        home_abs=env.home_abs,
    )

    if cmd == "build_ext":
        prepare_build_ext_command_fn(env=env, build_dir=build_dir)

    set_argv_fn(
        build_setuptools_argv_fn(
            prog_name=prog_name,
            command=cmd,
            home_abs=env.home_abs,
            out_arg=out_arg,
        )
    )

    worker_module = target_module + "_worker"
    ext_modules, links_created = prepare_setup_artifacts_fn(
        env=env,
        cmd=cmd,
        active_app=active_app,
        build_dir=build_dir,
        remaining_args=remaining_args,
        packages=packages,
        worker_module=worker_module,
    )

    return env, out_arg, worker_module, ext_modules, links_created


def _execute_main_setup(
    *,
    env,
    cmd: str,
    out_arg: str,
    worker_module: str,
    ext_modules: list,
    links_created: list[Path],
    ensure_build_readme_fn=None,
    build_setup_kwargs_fn=None,
    setup_fn=None,
    finalize_setup_artifacts_fn=None,
) -> None:
    if ensure_build_readme_fn is None:
        ensure_build_readme_fn = _ensure_build_readme
    if build_setup_kwargs_fn is None:
        build_setup_kwargs_fn = _build_setup_kwargs
    if setup_fn is None:
        setup_fn = setup
    if finalize_setup_artifacts_fn is None:
        finalize_setup_artifacts_fn = _finalize_setup_artifacts

    ensure_build_readme_fn()
    setup_fn(**build_setup_kwargs_fn(worker_module=worker_module, ext_modules=ext_modules))
    finalize_setup_artifacts_fn(
        env=env,
        cmd=cmd,
        out_arg=out_arg,
        links_created=links_created,
    )


def main(argv: list[str] | None = None) -> None:
    prog_name, active_app, opts, quiet, cmd, packages, raw_outdir = _resolve_main_inputs(
        argv,
    )

    env, out_arg, worker_module, ext_modules, links_created = _prepare_main_execution(
        prog_name=prog_name,
        active_app=active_app,
        quiet=quiet,
        cmd=cmd,
        raw_outdir=raw_outdir,
        build_dir=opts.build_dir,
        remaining_args=opts.remaining,
        packages=packages,
    )

    _execute_main_setup(
        env=env,
        cmd=cmd,
        out_arg=out_arg,
        worker_module=worker_module,
        ext_modules=ext_modules,
        links_created=links_created,
    )

if __name__ == "__main__":
    main()
