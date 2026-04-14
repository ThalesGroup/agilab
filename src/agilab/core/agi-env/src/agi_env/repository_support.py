import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableMapping


def resolve_package_root(root: Path) -> Path:
    """Return the package ``src`` directory when the package uses ``src/`` layout."""

    src_dir = root / "src" / root.name.replace("-", "_")
    return src_dir if src_dir.exists() else root


def get_apps_repository_root(
    *,
    envars: Mapping[str, str] | None,
    environ: Mapping[str, str] | None = None,
    logger: Any = None,
    fix_windows_drive_fn: Callable[[str], str],
) -> Path | None:
    """Return the configured apps repository directory when present."""

    environ = environ or os.environ
    repo_root = None
    if envars is not None:
        repo_root = envars.get("APPS_REPOSITORY")
    if not repo_root:
        repo_root = environ.get("APPS_REPOSITORY")
    if not repo_root:
        return None

    repo_root = repo_root.strip()
    if repo_root.startswith(("'", '"')) and repo_root.endswith(("'", '"')) and len(repo_root) >= 2:
        repo_root = repo_root[1:-1].strip()
    if not repo_root:
        return None

    repo_root = fix_windows_drive_fn(repo_root)
    repo_path = Path(repo_root).expanduser()

    candidate = repo_path / "src/agilab/apps"
    if candidate.exists():
        return candidate

    try:
        for alt in sorted(repo_path.glob("**/apps")):
            try:
                if any(child.name.endswith("_project") for child in alt.iterdir()):
                    return alt
            except OSError:
                continue
    except OSError as exc:
        if logger is not None:
            logger.debug(f"Error while scanning apps repository: {exc}")

    if logger is not None:
        logger.info(f"APPS_REPOSITORY is set but apps directory is missing under {repo_path}")
    return None


def dedupe_existing_paths(paths: Iterable[object]) -> list[str]:
    """Collapse ``paths`` into a list of unique, existing filesystem entries."""

    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if not path:
            continue
        path_str = str(path)
        if not path_str:
            continue
        if not Path(path_str).exists():
            continue
        if path_str in seen:
            continue
        seen.add(path_str)
        result.append(path_str)
    return result


def collect_pythonpath_entries(
    *,
    env_pck: Path,
    node_pck: Path,
    core_pck: Path,
    cluster_pck: Path,
    dist_abs: Path,
    app_src: Path,
    wenv_abs: Path,
    agilab_pck: Path,
    dedupe_paths_fn: Callable[[Iterable[object]], list[str]] = dedupe_existing_paths,
) -> list[str]:
    """Build an ordered list of paths that must live on ``PYTHONPATH``."""

    def import_root(path: Path) -> Path:
        try:
            init_file = path / "__init__.py"
        except TypeError:
            return path
        if init_file.exists():
            return path.parent
        return path

    candidates = [
        import_root(env_pck.parent),
        import_root(node_pck.parent),
        import_root(core_pck.parent),
        import_root(cluster_pck.parent),
        dist_abs,
        app_src,
        wenv_abs / "src",
        agilab_pck / "agilab",
    ]
    return dedupe_paths_fn(candidates)


def configure_pythonpath(
    entries: list[str],
    *,
    sys_path: list[str],
    environ: MutableMapping[str, str],
) -> None:
    """Inject ``entries`` into both ``sys.path`` and the ``PYTHONPATH`` env var."""

    if not entries:
        return

    for entry in entries:
        if entry not in sys_path:
            sys_path.append(entry)

    current = environ.get("PYTHONPATH", "")
    combined = entries.copy()
    if current:
        for part in current.split(os.pathsep):
            if part and part not in combined:
                combined.append(part)
    environ["PYTHONPATH"] = os.pathsep.join(combined)
