from __future__ import annotations

import os
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Iterable


def remap_managed_pc_path(
    value: Path | str,
    *,
    env: Any | None = None,
    managed_pc_home_suffix: str = "MyApp",
    path_cls: type[Path] = Path,
    home_factory: Callable[[], Path] = Path.home,
) -> Path:
    if env is None or not env._is_managed_pc:
        return path_cls(value)

    home = home_factory()
    managed_root = home / managed_pc_home_suffix

    try:
        return path_cls(str(path_cls(value)).replace(str(home), str(managed_root)))
    except Exception:
        return path_cls(value)


def ensure_managed_pc_share_dir(
    env: Any | None,
    *,
    managed_pc_home_suffix: str = "MyApp",
    path_cls: type[Path] = Path,
    home_factory: Callable[[], Path] = Path.home,
) -> None:
    if env is None or not env._is_managed_pc:
        return

    agi_share_path = env.agi_share_path
    if agi_share_path is None:
        return

    home = home_factory()
    managed_root = home / managed_pc_home_suffix
    try:
        env.agi_share_path = path_cls(
            str(path_cls(agi_share_path)).replace(str(home), str(managed_root))
        )
    except Exception:
        return


def normalized_path(
    value: Path | str,
    *,
    normalize_path_fn: Callable[[Path], str | Path],
    path_cls: type[Path] = Path,
) -> Path:
    path_obj = path_cls(value)
    try:
        return path_cls(normalize_path_fn(path_obj)).expanduser()
    except Exception:
        return path_obj.expanduser()


def share_root_path(
    env: Any | None,
    *,
    path_cls: type[Path] = Path,
) -> Path | None:
    if env is None:
        return None

    try:
        base = path_cls(env.share_root_path()).expanduser()
        if base:
            return base
    except Exception:
        pass

    for candidate in (env.agi_share_path_abs, env.agi_share_path):
        if candidate:
            base = path_cls(candidate).expanduser()
            if not base.is_absolute():
                home = path_cls(env.home_abs).expanduser()
                base = (home / base).expanduser()
            return base
    return path_cls(env.home_abs).expanduser()


def resolve_data_dir(
    env: Any | None,
    data_path: Path | str | None,
    *,
    share_root_path_fn: Callable[[Any | None], Path | None],
    remap_managed_pc_path_fn: Callable[[Path | str], Path],
    normalized_path_fn: Callable[[Path | str], Path],
    path_cls: type[Path] = Path,
    home_factory: Callable[[], Path] = Path.home,
) -> Path:
    if data_path is None:
        raise ValueError("data_path must be provided to resolve a dataset directory")

    raw = path_cls(str(data_path)).expanduser()
    if not raw.is_absolute():
        base = share_root_path_fn(env) or home_factory()
        raw = path_cls(base).expanduser() / raw

    remapped = remap_managed_pc_path_fn(raw)
    try:
        resolved = normalized_path_fn(remapped)
    except Exception:
        resolved = path_cls(remapped).expanduser()

    try:
        return resolved.resolve(strict=False)
    except Exception:
        return path_cls(os.path.normpath(str(resolved)))


def relative_to_user_home(path: Path, *, path_cls: type[Path] = Path) -> Path | None:
    parts = path.parts
    if len(parts) >= 3 and parts[1].lower() in {"users", "home"}:
        return path_cls(*parts[3:]) if len(parts) > 3 else path_cls()
    return None


def remap_user_home(path: Path, *, username: str, path_cls: type[Path] = Path) -> Path | None:
    parts = path.parts
    if len(parts) < 3:
        return None
    root_marker = parts[1].lower()
    if root_marker not in {"users", "home"}:
        return None
    root = path_cls(parts[0]) if parts[0] else path_cls("/")
    base = root / parts[1] / username
    remainder = path_cls(*parts[3:]) if len(parts) > 3 else path_cls()
    return base / remainder if remainder != path_cls() else base


def strip_share_prefix(path: Path, aliases: set[str], *, path_cls: type[Path] = Path) -> Path:
    parts = path.parts
    if parts and parts[0] in aliases:
        return path_cls(*parts[1:]) if len(parts) > 1 else path_cls()
    return path


def can_create_path(path: Path, *, path_cls: type[Path] = Path) -> bool:
    target_dir = path
    if target_dir.suffix:
        target_dir = target_dir.parent
    probe = target_dir / f".agi_perm_{uuid.uuid4().hex}"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        probe.touch(exist_ok=False)
    except (PermissionError, FileNotFoundError, OSError):
        return False
    else:
        return True
    finally:
        with suppress(Exception):
            probe.unlink()


def collect_share_aliases(
    env: Any | None,
    share_base: Path,
    *,
    path_cls: type[Path] = Path,
) -> set[str]:
    aliases = {share_base.name, "data", "clustershare", "datashare"}
    if env:
        if env.AGILAB_SHARE_HINT:
            hint_path = path_cls(str(env.AGILAB_SHARE_HINT))
            parts = [p for p in hint_path.parts if p not in {"", "."}]
            aliases.update(parts[-2:])
        if env.AGILAB_SHARE_REL:
            try:
                aliases.add(path_cls(env.AGILAB_SHARE_REL).name)
            except Exception:
                pass
        if env.agi_share_path:
            try:
                aliases.add(path_cls(env.agi_share_path).name)
            except Exception:
                pass
    return {alias for alias in aliases if alias}


def iter_input_files(
    folder: Path,
    *,
    patterns: Iterable[str] | None = None,
) -> list[Path]:
    file_patterns = tuple(patterns or ("*.csv", "*.parquet", "*.pq", "*.parq"))
    files: list[Path] = []
    for pattern in file_patterns:
        files.extend(sorted(folder.glob(pattern)))
    return [path for path in files if path.is_file() and not path.name.startswith("._")]


def has_min_input_files(
    folder: Path,
    *,
    min_files: int = 1,
    patterns: Iterable[str] | None = None,
    iter_input_files_fn: Callable[..., list[Path]] = iter_input_files,
) -> bool:
    if not folder.exists() or not folder.is_dir():
        return False
    return len(iter_input_files_fn(folder, patterns=patterns)) >= min_files


def candidate_named_dataset_roots(
    env: Any | None,
    dataset_root: Path | str,
    *,
    namespace: str | None = None,
    parent_levels: int = 4,
    normalized_path_fn: Callable[[Path | str], Path],
    share_root_path_fn: Callable[[Any | None], Path | None],
    path_cls: type[Path] = Path,
) -> list[Path]:
    root = normalized_path_fn(dataset_root)
    candidates: list[Path] = [root]

    if namespace:
        dataset_name = root.name
        for ancestor in list(root.parents)[:parent_levels]:
            candidates.append(ancestor / namespace / dataset_name)
            candidates.append(ancestor / namespace)

        share_root = share_root_path_fn(env)
        if share_root:
            candidates.append(share_root / namespace / dataset_name)
            candidates.append(share_root / namespace)

    unique_roots: list[Path] = []
    seen_roots: set[str] = set()
    for candidate in candidates:
        try:
            normalized = normalized_path_fn(candidate).resolve(strict=False)
        except Exception:
            normalized = normalized_path_fn(candidate)
        key = str(normalized)
        if key not in seen_roots:
            seen_roots.add(key)
            unique_roots.append(normalized)
    return unique_roots


def resolve_input_folder(
    env: Any | None,
    dataset_root: Path | str,
    relative_dir: Path | str,
    *,
    descriptor: str,
    fallback_subdirs: Iterable[str] = (),
    dataset_namespace: str | None = None,
    min_files: int = 1,
    patterns: Iterable[str] | None = None,
    required_label: str = "data files",
    normalized_path_fn: Callable[[Path | str], Path],
    has_min_input_files_fn: Callable[..., bool],
    candidate_named_dataset_roots_fn: Callable[..., list[Path]],
    warn_fn: Callable[..., Any] | None = None,
    path_cls: type[Path] = Path,
) -> Path:
    dataset_root_path = normalized_path_fn(dataset_root)
    target = path_cls(relative_dir).expanduser()
    if not target.is_absolute():
        target = dataset_root_path / target
    target = normalized_path_fn(target)

    if has_min_input_files_fn(target, min_files=min_files, patterns=patterns):
        return target.resolve(strict=False)

    for fallback_subdir in fallback_subdirs:
        nested_target = normalized_path_fn(target / fallback_subdir)
        if has_min_input_files_fn(nested_target, min_files=min_files, patterns=patterns):
            if warn_fn is not None:
                warn_fn(
                    "Needed %s data under '%s' but none found; using nested fallback '%s' instead.",
                    descriptor,
                    target,
                    nested_target,
                )
            return nested_target.resolve(strict=False)

    for root in candidate_named_dataset_roots_fn(
        env,
        dataset_root_path,
        namespace=dataset_namespace,
    ):
        for fallback_subdir in fallback_subdirs:
            fallback = normalized_path_fn(root / fallback_subdir)
            if has_min_input_files_fn(fallback, min_files=min_files, patterns=patterns):
                if warn_fn is not None:
                    warn_fn(
                        "Needed %s data under '%s' but none found; using fallback '%s' instead.",
                        descriptor,
                        target,
                        fallback,
                    )
                return fallback.resolve(strict=False)

    raise FileNotFoundError(
        f"Need at least {min_files} {required_label} under '{target}'. "
        f"Run {descriptor} to generate inputs before executing."
    )
