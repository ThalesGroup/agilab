from __future__ import annotations

import glob
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def _candidate_edges_paths(bases: list[Path]) -> list[Path]:
    seen = set()
    candidates: list[Path] = []
    known_relative = (
        Path("pipeline/flows/topology.json"),
        Path("pipeline/topology.gml"),
        Path("pipeline/ilp_topology.gml"),
        Path("pipeline/routing_edges.jsonl"),
    )
    patterns = (
        # Common routing exports
        "routing_edges.jsonl",
        "routing_edges.ndjson",
        "routing_edges.json",
        "routing_edges.parquet",
        # Generic edge exports
        "edges.parquet",
        "edges.json",
        "edges.jsonl",
        "edges.ndjson",
        "edges.*.parquet",
        "edges.*.json",
        "edges.*.jsonl",
        "edges.*.ndjson",
        # Common topology exports (GML-format files often named .json)
        "topology.json",
        "topology.gml",
        "ilp_topology.gml",
    )
    for base in bases:
        if not base or not base.exists():
            continue
        # Fast path: check known default locations (avoids expensive globbing on large shares).
        for rel in known_relative:
            p = (base / rel).expanduser()
            if p.exists() and p.is_file() and p not in seen:
                if not any(part.startswith(".") for part in p.parts):
                    seen.add(p)
                    candidates.append(p)
        for pattern in patterns:
            for p in base.glob(f"**/{pattern}"):
                if p in seen:
                    continue
                if any(part.startswith(".") for part in p.parts):
                    continue
                seen.add(p)
                candidates.append(p)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return candidates

def _quick_share_edges_paths(share_root: Path) -> list[Path]:
    seen: set[Path] = set()
    candidates: list[Path] = []
    known_relative = (
        Path("pipeline/flows/topology.json"),
        Path("pipeline/topology.gml"),
        Path("pipeline/ilp_topology.gml"),
        Path("pipeline/routing_edges.jsonl"),
        Path("pipeline/routing_edges.parquet"),
        Path("pipeline/edges.parquet"),
        Path("pipeline/edges.json"),
        Path("pipeline/edges.jsonl"),
        Path("pipeline/edges.ndjson"),
        Path("pipeline/topology.json"),
        Path("pipeline/ilp_topology.json"),
    )
    if not share_root.exists():
        return []
    roots = [share_root]
    try:
        roots.extend(
            [
                entry
                for entry in sorted(share_root.iterdir())
                if entry.is_dir() and not entry.name.startswith(".")
            ]
        )
    except (OSError, RuntimeError):
        logger.debug("Unable to enumerate edge candidate roots under %s", share_root, exc_info=True)
        roots = [share_root]
    for root in roots:
        for rel in known_relative:
            p = (root / rel).expanduser()
            if p.exists() and p.is_file():
                try:
                    resolved = p.resolve(strict=False)
                except (OSError, RuntimeError):
                    logger.debug("Unable to resolve edge candidate %s", p, exc_info=True)
                    resolved = p
                if resolved in seen:
                    continue
                seen.add(resolved)
                candidates.append(p)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return candidates


def _quick_share_traj_globs(share_root: Path) -> list[str]:
    share_root = share_root.expanduser()
    candidates = [
        str(share_root / "*_trajectory" / "pipeline" / "*.parquet"),
        str(share_root / "*_trajectory" / "pipeline" / "*.csv"),
        str(share_root / "*trajectory*" / "pipeline" / "*.parquet"),
        str(share_root / "*trajectory*" / "pipeline" / "*.csv"),
    ]
    return [c for c in candidates if glob.glob(str(Path(c).expanduser()))]


def _candidate_files_from_globs(globs_list: list[str]) -> list[Path]:
    seen: set[Path] = set()
    candidates: list[Path] = []
    for pattern in globs_list:
        expanded = Path(pattern).expanduser()
        for match in glob.glob(str(expanded), recursive=True):
            path = Path(match).expanduser()
            if not path.is_file():
                continue
            try:
                resolved = path.resolve(strict=False)
            except Exception:
                resolved = path
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(path)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return candidates


def _expand_glob_patterns(patterns: list[str], base_dirs: list[Path]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    bases = [base.expanduser() for base in base_dirs if base]
    for pattern in patterns:
        raw = pattern.strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        candidates = [str(path)] if path.is_absolute() else [str(base / raw) for base in bases]
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            expanded.append(candidate)
    return expanded


def _resolve_declared_path(value: str, base_dirs: list[Path]) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    if path.is_absolute():
        return str(path)
    bases = [base.expanduser() for base in base_dirs if base]
    for base in bases:
        candidate = (base / raw).expanduser()
        if candidate.exists():
            return str(candidate)
    return str((bases[0] / raw).expanduser()) if bases else raw


def _choose_existing_declared_path(current_value: str, default_value: str, base_dirs: list[Path]) -> str:
    for candidate in (current_value, default_value):
        raw = (candidate or "").strip()
        if not raw:
            continue
        resolved = _resolve_declared_path(raw, base_dirs)
        try:
            path = Path(resolved).expanduser()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if path.exists():
            return str(path)

    raw_current = (current_value or "").strip()
    if raw_current:
        return _resolve_declared_path(raw_current, base_dirs)

    raw_default = (default_value or "").strip()
    if raw_default:
        return _resolve_declared_path(raw_default, base_dirs)
    return ""


def _resolve_edges_file_path(value: str, base_dirs: list[Path]) -> Path | None:
    raw = (value or "").strip()
    if not raw:
        return None
    resolved = _resolve_declared_path(raw, base_dirs)
    try:
        return Path(resolved).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _candidate_cloudmap_paths(bases: list[Path], names: tuple[str, ...]) -> list[Path]:
    seen: set[Path] = set()
    candidates: list[Path] = []
    relative_paths = tuple(
        Path(prefix) / name
        for name in names
        for prefix in ("", "dataset", "pipeline")
    )
    for base in bases:
        base = base.expanduser()
        if not base.exists():
            continue
        roots = [base]
        try:
            roots.extend(
                entry
                for entry in sorted(base.iterdir())
                if entry.is_dir() and not entry.name.startswith(".")
            )
        except (OSError, RuntimeError):
            logger.debug("Unable to enumerate cloud map candidates under %s", base, exc_info=True)
        for root in roots:
            for rel in relative_paths:
                candidate = (root / rel).expanduser()
                if not candidate.exists() or not candidate.is_file():
                    continue
                try:
                    resolved = candidate.resolve(strict=False)
                except (OSError, RuntimeError):
                    logger.debug("Unable to resolve cloud map candidate %s", candidate, exc_info=True)
                    resolved = candidate
                if resolved in seen:
                    continue
                seen.add(resolved)
                candidates.append(candidate)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return candidates


def _allocation_search_roots(
    *,
    base_path: Path,
    datadir_path: Path,
    export_base: Path,
    local_share_root: Path,
    target_name: str,
) -> tuple[Path, list[Path]]:
    local_target_root = (local_share_root / str(target_name)).expanduser()
    selected_target_root = (base_path / str(target_name)).expanduser()
    preferred_target_root = (
        selected_target_root
        if selected_target_root.exists() or selected_target_root != local_target_root
        else local_target_root
    )

    roots: list[Path] = []
    seen: set[Path] = set()
    for root in (
        preferred_target_root,
        local_target_root,
        datadir_path,
        export_base,
    ):
        for candidate in (root, root / "pipeline", root / "dataframe"):
            try:
                resolved = candidate.expanduser().resolve(strict=False)
            except Exception:
                resolved = candidate.expanduser()
            if resolved in seen:
                continue
            seen.add(resolved)
            roots.append(candidate.expanduser())

    return preferred_target_root, roots


def _candidate_allocation_paths(bases: list[Path]) -> list[Path]:
    seen = set()
    candidates: list[Path] = []
    known_relative = (
        Path("pipeline/allocations_steps.parquet"),
        Path("pipeline/allocations_steps.json"),
        Path("pipeline/allocations_steps.jsonl"),
        Path("pipeline/allocations_steps.csv"),
        Path("dataframe/allocations_steps.parquet"),
        Path("dataframe/allocations_steps.json"),
        Path("dataframe/allocations_steps.jsonl"),
        Path("dataframe/allocations_steps.csv"),
    )
    patterns = (
        "allocations_steps.parquet",
        "allocations_steps.json",
        "allocations_steps.jsonl",
        "allocations_steps.ndjson",
        "allocations_steps.csv",
        "allocations*.parquet",
        "allocations*.json",
        "allocations*.jsonl",
        "allocations*.ndjson",
        "allocations*.csv",
        "*allocations*.parquet",
        "*allocations*.json",
        "*allocations*.jsonl",
        "*allocations*.ndjson",
        "*allocations*.csv",
    )
    for base in bases:
        if not base or not base.exists():
            continue
        for rel in known_relative:
            p = (base / rel).expanduser()
            if p.exists() and p.is_file() and p not in seen:
                if not any(part.startswith(".") for part in p.parts):
                    seen.add(p)
                    candidates.append(p)
        for pattern in patterns:
            for p in base.glob(f"**/{pattern}"):
                if p in seen:
                    continue
                if any(part.startswith(".") for part in p.parts):
                    continue
                seen.add(p)
                candidates.append(p)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return candidates

def _is_baseline_alloc_path(path: Path) -> bool:
    lowered = str(path).lower()
    return ("baseline" in lowered) or ("ilp" in lowered) or ("stepper" in lowered)


def _find_latest_allocations(base: Path, include: tuple[str, ...] = ()) -> Path | None:
    """Locate the most recent allocations file under a given base."""
    candidates: list[Path] = []
    for pattern in (
        "allocations*.parquet",
        "allocations*.json",
        "allocations*.jsonl",
        "allocations*.ndjson",
        "allocations*.csv",
        "*allocations*.parquet",
        "*allocations*.json",
        "*allocations*.jsonl",
        "*allocations*.ndjson",
        "*allocations*.csv",
        "allocations_steps.parquet",
        "allocations_steps.csv",
    ):
        candidates.extend(base.rglob(pattern))
    if not candidates:
        return None
    candidates = [p for p in candidates if p.is_file()]
    if include:
        lowered = [token.lower() for token in include if token]
        if lowered:
            candidates = [p for p in candidates if all(token in str(p).lower() for token in lowered)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)

# ----------------------------
