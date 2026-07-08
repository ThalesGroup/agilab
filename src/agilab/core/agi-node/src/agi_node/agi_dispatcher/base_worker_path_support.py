from __future__ import annotations

import os
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Iterable

PATH_FALLBACK_EXCEPTIONS = (OSError, TypeError, ValueError)
SHARE_ROOT_FALLBACK_EXCEPTIONS = PATH_FALLBACK_EXCEPTIONS + (AttributeError,)


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
    except PATH_FALLBACK_EXCEPTIONS:
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
    except PATH_FALLBACK_EXCEPTIONS:
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
    except PATH_FALLBACK_EXCEPTIONS:
        return path_obj.expanduser()


def share_root_path(
    env: Any | None,
    *,
    path_cls: type[Path] = Path,
) -> Path | None:
    if env is None:
        return None

    for name in ("AGILAB_WORKFLOW_DATA_ROOT", "agi_workflow_data_root", "workflow_data_root"):
        active_root = getattr(env, name, None)
        if not active_root and isinstance(getattr(env, "envars", None), dict):
            active_root = env.envars.get(name)
        if not active_root:
            continue
        try:
            base = path_cls(active_root).expanduser()
            if not base.is_absolute():
                home = getattr(env, "home_abs", None)
                base_home = path_cls(home).expanduser() if home else path_cls.home()
                base = base_home / base
            return base.resolve(strict=False)
        except SHARE_ROOT_FALLBACK_EXCEPTIONS:
            continue

    try:
        base = path_cls(env.share_root_path()).expanduser()
        if base:
            return base
    except SHARE_ROOT_FALLBACK_EXCEPTIONS:
        pass

    is_worker_env = bool(getattr(env, "is_worker_env", False))
    candidates = (
        (env.agi_share_path, True),
        (env.agi_share_path_abs, False),
    ) if is_worker_env else (
        (env.agi_share_path_abs, False),
        (env.agi_share_path, False),
    )
    for candidate, use_runtime_home in candidates:
        if candidate:
            base = path_cls(candidate).expanduser()
            if not base.is_absolute():
                home = path_cls.home() if use_runtime_home else path_cls(env.home_abs).expanduser()
                base = (home / base).expanduser()
            return base
    return path_cls(env.home_abs).expanduser()


def physical_share_root_path(
    env: Any | None,
    *,
    path_cls: type[Path] = Path,
) -> Path | None:
    """Return the physical cluster/share root, ignoring workflow-session scoping."""

    if env is None:
        return None

    share_root_method = getattr(env, "share_root_path", None)
    if callable(share_root_method):
        try:
            return path_cls(share_root_method()).expanduser().resolve(strict=False)
        except SHARE_ROOT_FALLBACK_EXCEPTIONS:
            pass

    for candidate, use_runtime_home in (
        (getattr(env, "agi_share_path_abs", None), False),
        (getattr(env, "agi_share_path", None), bool(getattr(env, "is_worker_env", False))),
    ):
        if not candidate:
            continue
        try:
            base = path_cls(candidate).expanduser()
            if not base.is_absolute():
                if use_runtime_home:
                    home = path_cls.home()
                else:
                    home_abs = getattr(env, "home_abs", None)
                    home = path_cls(home_abs).expanduser() if home_abs else path_cls.home()
                base = home / base
            return base.resolve(strict=False)
        except SHARE_ROOT_FALLBACK_EXCEPTIONS:
            continue
    return None


def _relative_share_prefixes(
    env: Any | None,
    share_base: Path,
    *,
    path_cls: type[Path] = Path,
    home_factory: Callable[[], Path] = Path.home,
) -> list[Path]:
    prefixes: list[Path] = []

    def add_prefix(value: Any) -> None:
        if not value:
            return
        try:
            prefix = path_cls(value).expanduser()
        except PATH_FALLBACK_EXCEPTIONS:
            return
        if prefix.is_absolute():
            return
        if prefix not in {path_cls(), path_cls(".")}:
            prefixes.append(prefix)

    if env is not None:
        for attr in ("agi_share_path", "AGILAB_SHARE_REL"):
            add_prefix(getattr(env, attr, None))

        share_abs = getattr(env, "agi_share_path_abs", None)
        home_abs = getattr(env, "home_abs", None)
        if share_abs and home_abs:
            try:
                add_prefix(path_cls(share_abs).expanduser().relative_to(path_cls(home_abs).expanduser()))
            except PATH_FALLBACK_EXCEPTIONS:
                pass

    try:
        home = path_cls(home_factory()).expanduser()
        add_prefix(path_cls(share_base).expanduser().relative_to(home))
    except PATH_FALLBACK_EXCEPTIONS:
        pass

    unique: list[Path] = []
    seen: set[tuple[str, ...]] = set()
    for prefix in sorted(prefixes, key=lambda value: len(value.parts), reverse=True):
        parts = tuple(part for part in prefix.parts if part not in {"", "."})
        if not parts or parts in seen:
            continue
        seen.add(parts)
        unique.append(path_cls(*parts))
    return unique


def _resolve_relative_data_path(
    raw: Path,
    share_base: Path,
    env: Any | None,
    *,
    path_cls: type[Path] = Path,
    home_factory: Callable[[], Path] = Path.home,
) -> Path:
    raw_parts = tuple(part for part in raw.parts if part not in {"", "."})
    for prefix in _relative_share_prefixes(
        env,
        share_base,
        path_cls=path_cls,
        home_factory=home_factory,
    ):
        prefix_parts = prefix.parts
        if raw_parts[: len(prefix_parts)] != prefix_parts:
            continue
        remainder_parts = raw_parts[len(prefix_parts) :]
        remainder = path_cls(*remainder_parts) if remainder_parts else path_cls()
        return path_cls(share_base).expanduser() / remainder
    share_leaf = path_cls(share_base).expanduser().name
    if raw_parts and raw_parts[0] == share_leaf:
        remainder_parts = raw_parts[1:]
        remainder = path_cls(*remainder_parts) if remainder_parts else path_cls()
        return path_cls(share_base).expanduser() / remainder
    return path_cls(share_base).expanduser() / raw


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


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
        session_candidate = _resolve_relative_data_path(
            raw,
            path_cls(base).expanduser(),
            env,
            path_cls=path_cls,
            home_factory=home_factory,
        )
        raw = session_candidate

        physical_base = physical_share_root_path(env, path_cls=path_cls)
        if physical_base is not None:
            try:
                same_base = path_cls(base).expanduser().resolve(strict=False) == physical_base
            except SHARE_ROOT_FALLBACK_EXCEPTIONS:
                same_base = False
            if not same_base:
                physical_candidate = _resolve_relative_data_path(
                    path_cls(str(data_path)).expanduser(),
                    physical_base,
                    env,
                    path_cls=path_cls,
                    home_factory=home_factory,
                )
                if not _path_exists(session_candidate) and _path_exists(physical_candidate):
                    raw = physical_candidate

    remapped = remap_managed_pc_path_fn(raw)
    try:
        resolved = normalized_path_fn(remapped)
    except PATH_FALLBACK_EXCEPTIONS:
        resolved = path_cls(remapped).expanduser()

    try:
        return resolved.resolve(strict=False)
    except OSError:
        return path_cls(os.path.normpath(str(resolved)))


def _safe_resolved_path(path: Path, *, path_cls: type[Path] = Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except PATH_FALLBACK_EXCEPTIONS:
        return path_cls(os.path.normpath(str(path.expanduser())))


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_generated_artifact_path(
    data_in_root: Path | str,
    data_out_root: Path | str,
    artifact_path: Path | str,
    *,
    normalized_path_fn: Callable[[Path | str], Path] | None = None,
    path_cls: type[Path] = Path,
) -> Path:
    """Resolve generated content under ``data_out`` instead of read-only input data.

    Relative artifact paths are anchored under ``data_out_root``. If a caller
    accidentally passes a path already rooted under ``data_in_root`` or prefixed
    by the dataset leaf, the dataset prefix is replaced with ``data_out_root``.
    The final path must not remain under ``data_in_root``.
    """

    if artifact_path is None:
        raise ValueError("artifact_path must be provided")

    normalize = normalized_path_fn or (lambda value: path_cls(value).expanduser())
    data_in = _safe_resolved_path(normalize(data_in_root), path_cls=path_cls)
    data_out = _safe_resolved_path(normalize(data_out_root), path_cls=path_cls)
    raw = path_cls(str(artifact_path)).expanduser()

    if raw == path_cls("."):
        candidate = data_out
    elif raw.is_absolute():
        resolved_raw = _safe_resolved_path(raw, path_cls=path_cls)
        if _path_is_relative_to(resolved_raw, data_in):
            relative = resolved_raw.relative_to(data_in)
            candidate = data_out / relative
        else:
            candidate = resolved_raw
    else:
        parts = tuple(part for part in raw.parts if part not in {"", "."})
        if parts and parts[0] == data_in.name:
            raw = path_cls(*parts[1:]) if len(parts) > 1 else path_cls(".")
        candidate = data_out if raw == path_cls(".") else data_out / raw

    resolved = _safe_resolved_path(candidate, path_cls=path_cls)
    if _path_is_relative_to(resolved, data_in):
        raise ValueError(
            "Generated artifact path resolves under read-only data_in: "
            f"{resolved} (data_in={data_in}, data_out={data_out})"
        )
    return resolved


def _env_value(env: Any | None, name: str) -> Any:
    if env is None:
        return None
    value = getattr(env, name, None)
    if value:
        return value
    envars = getattr(env, "envars", None)
    if isinstance(envars, dict):
        return envars.get(name)
    return None


def _target_relative_path(
    target: str,
    leaf: Path | str,
    *,
    path_cls: type[Path] = Path,
) -> Path:
    leaf_path = path_cls(leaf)
    if leaf_path == path_cls("."):
        return path_cls(target) if target else path_cls()
    return path_cls(target) / leaf_path if target else leaf_path


def resolve_artifact_dir(
    env: Any | None,
    leaf: Path | str,
    *,
    target: str | None = None,
    path_cls: type[Path] = Path,
    home_factory: Callable[[], Path] = Path.home,
) -> Path:
    """Resolve app evidence artifacts through the shared worker path contract.

    Precedence is explicit export root, runtime share resolver, active workflow
    share root, then an operator-local ``export`` directory. The final fallback
    uses ``env.home_abs`` when available so polluted process ``HOME`` values do
    not silently move evidence.
    """

    target_text = str(target if target is not None else _env_value(env, "target") or "")
    relative = _target_relative_path(target_text, leaf, path_cls=path_cls)

    export_root = _env_value(env, "AGILAB_EXPORT_ABS")
    if export_root:
        root = path_cls(export_root).expanduser()
        return root / relative if relative != path_cls() else root

    resolve_share_path = getattr(env, "resolve_share_path", None) if env is not None else None
    if callable(resolve_share_path):
        resolved = path_cls(resolve_share_path(relative)).expanduser()
        return resolved.resolve(strict=False)

    share_root = None
    has_share_hint = any(
        _env_value(env, name)
        for name in (
            "AGILAB_WORKFLOW_DATA_ROOT",
            "agi_workflow_data_root",
            "workflow_data_root",
            "agi_share_path_abs",
            "agi_share_path",
        )
    )
    if has_share_hint:
        share_root = share_root_path(env, path_cls=path_cls)
    else:
        share_root_method = getattr(env, "share_root_path", None) if env is not None else None
        if callable(share_root_method):
            try:
                share_root = path_cls(share_root_method()).expanduser().resolve(strict=False)
            except SHARE_ROOT_FALLBACK_EXCEPTIONS:
                share_root = None
    if share_root is not None:
        root = path_cls(share_root).expanduser()
        return (root / relative).resolve(strict=False) if relative != path_cls() else root.resolve(strict=False)

    home = _env_value(env, "home_abs") or home_factory()
    root = path_cls(home).expanduser() / "export"
    return root / relative if relative != path_cls() else root


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
        with suppress(OSError):
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
            except PATH_FALLBACK_EXCEPTIONS:
                pass
        if env.agi_share_path:
            try:
                aliases.add(path_cls(env.agi_share_path).name)
            except PATH_FALLBACK_EXCEPTIONS:
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
        normalized = normalized_path_fn(candidate)
        try:
            normalized = normalized.resolve(strict=False)
        except OSError:
            pass
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
