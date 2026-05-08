from __future__ import annotations

import ast
import logging
import os
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import streamlit as st
import tomli_w
import tomllib

from agi_env import AgiEnv

ORCHESTRATE_LOCKED_STEP_KEY = "_orchestrate_locked_step"
ORCHESTRATE_LOCKED_SOURCE_KEY = "_orchestrate_snippet_source"
LAB_STEPS_META_KEY = "__meta__"
LAB_STEPS_SCHEMA = "agilab.lab_steps.v1"
LAB_STEPS_SCHEMA_VERSION = 1
LEGACY_AGI_RUN_KEYWORDS = frozenset(
    {
        "args",
        "data_in",
        "data_out",
        "mode",
        "reset_target",
        "scheduler",
        "workers",
    }
)

logger = logging.getLogger(__name__)


def ensure_lab_steps_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp lab_steps data with the current persisted artifact contract."""
    meta = data.get(LAB_STEPS_META_KEY)
    if not isinstance(meta, dict):
        meta = {}
        data[LAB_STEPS_META_KEY] = meta
    meta.setdefault("schema", LAB_STEPS_SCHEMA)
    meta.setdefault("version", LAB_STEPS_SCHEMA_VERSION)
    return data


def lab_steps_contract_error(data: Dict[str, Any]) -> str:
    """Return a refusal reason when lab_steps metadata is unsupported."""
    meta = data.get(LAB_STEPS_META_KEY, {})
    if meta in ({}, None):
        return ""
    if not isinstance(meta, dict):
        return "lab_steps.toml __meta__ must be a TOML table."
    raw_version = meta.get("version")
    if raw_version in (None, ""):
        return ""
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        return f"Unsupported lab_steps.toml schema version {raw_version!r}."
    if version < 1 or version > LAB_STEPS_SCHEMA_VERSION:
        return (
            f"Unsupported lab_steps.toml schema version {version}; "
            "upgrade AGILAB before editing this pipeline."
        )
    return ""


def prepare_lab_steps_for_write(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and stamp lab_steps data before persisting it."""
    error = lab_steps_contract_error(data)
    if error:
        raise ValueError(error)
    return ensure_lab_steps_metadata(data)

def normalize_imported_orchestrate_snippet(
    code: Any,
    *,
    default_runtime: str = "",
) -> tuple[Any, str, str]:
    """Infer the execution mode for an imported ORCHESTRATE snippet without rewriting it."""
    if not isinstance(code, str):
        return code, "agi.run" if default_runtime else "runpy", default_runtime

    app_name = extract_step_app_name(code)
    runtime = app_name or default_runtime

    if "from agi_cluster.agi_distributor import AGI" in code or "AGI." in code:
        return code, "agi.run", runtime

    return code, "runpy", runtime


def _convert_paths_to_strings(obj: Any) -> Any:
    """Recursively convert pathlib.Path objects to strings for TOML serialization."""
    if isinstance(obj, dict):
        return {key: _convert_paths_to_strings(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_convert_paths_to_strings(item) for item in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def normalize_runtime_path(raw: Optional[Union[str, Path]], env: Optional[AgiEnv] = None) -> str:
    """Return a canonical project directory for a runtime selection."""
    if not raw:
        return ""
    try:
        text = str(raw).strip()
        if not text:
            return ""
        candidate = Path(text).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return str(raw)

    env_obj = env or st.session_state.get("env")
    apps_root: Optional[Path] = None
    try:
        apps_root = Path(env_obj.apps_path).expanduser()  # type: ignore[attr-defined]
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        apps_root = None

    if not candidate.is_absolute() and apps_root:
        candidate = apps_root / candidate

    if apps_root and not candidate.exists():
        fallback = apps_root / candidate.name
        if fallback.exists():
            candidate = fallback

    if candidate.name == ".venv":
        candidate = candidate.parent
    return str(candidate)


def step_summary(entry: Optional[Dict[str, Any]], width: int = 60) -> str:
    """Return a concise summary for a workflow stage entry."""
    if not isinstance(entry, dict):
        return ""

    question = str(entry.get("Q") or "").strip()
    if question:
        collapsed = " ".join(question.split())
        return textwrap.shorten(collapsed, width=width, placeholder="…")

    code = str(entry.get("C") or "").strip()
    if code:
        first_line = code.splitlines()[0]
        collapsed = " ".join(first_line.split())
        return textwrap.shorten(collapsed, width=width, placeholder="…")

    return ""


def step_project_name(entry: Optional[Dict[str, Any]], env: Optional[AgiEnv] = None) -> str:
    """Return the best available project/app name for a saved workflow stage."""
    if not isinstance(entry, dict):
        return ""

    app_name = extract_step_app_name(entry.get("C", ""))
    if app_name:
        return app_name

    runtime = normalize_runtime_path(entry.get("E", ""), env=env)
    if not runtime:
        return ""

    try:
        candidate = Path(runtime).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        candidate = Path(str(runtime))

    name = candidate.name.strip()
    if name == ".venv":
        name = candidate.parent.name.strip()
    if name:
        return name

    text = str(runtime).replace("\\", "/").rstrip("/")
    return text.split("/")[-1].strip() if text else ""


def step_label_for_multiselect(
    idx: int,
    entry: Optional[Dict[str, Any]],
    *,
    env: Optional[AgiEnv] = None,
) -> str:
    """Label for the stage-order multiselect widget."""
    summary = step_summary(entry)
    project = step_project_name(entry, env=env)
    if summary and project:
        return f"Stage {idx + 1}: [{project}] {summary}"
    if summary:
        return f"Stage {idx + 1}: {summary}"
    if project:
        return f"Stage {idx + 1}: [{project}]"
    return f"Stage {idx + 1}"


def step_button_label(display_idx: int, step_idx: int, entry: Optional[Dict[str, Any]]) -> str:
    """Label for a rendered stage button respecting the selected order."""
    summary = step_summary(entry)
    if summary:
        return f"{display_idx + 1}. {summary}"
    return f"{display_idx + 1}. Stage {step_idx + 1}"


def upgrade_legacy_step_code(code: Any) -> Any:
    """Legacy snippet migration has been removed; return code unchanged."""
    return code


def extract_step_app_name(code: Any) -> str:
    """Extract the app/project name referenced by a saved AGI snippet."""
    if not isinstance(code, str) or not code:
        return ""
    match = re.search(r'(?m)^\s*APP\s*=\s*["\']([^"\']+)["\']\s*$', code)
    return str(match.group(1)).strip() if match else ""


def looks_like_runtime_reference(raw: Any) -> bool:
    """Return True when a runtime value looks like a real path/app reference."""
    text = str(raw or "").strip()
    if not text:
        return False
    if Path(text).expanduser().is_absolute():
        return True
    if re.match(r"^[A-Za-z]:[\\/]", text):
        return True
    if " " in text:
        return False
    if any(sep in text for sep in ("/", "\\")):
        return True
    if text.endswith(".venv"):
        return True
    if text.endswith("_project") and " " not in text:
        return True
    return False


def upgrade_legacy_step_runtime(raw_runtime: Any, *, engine: Any, app_name: str) -> Any:
    """Legacy runtime migration has been removed; keep the stored runtime unchanged."""
    return raw_runtime


def upgrade_legacy_step_entry(entry: Any) -> bool:
    """Legacy stage migration has been removed; do not mutate entries implicitly."""
    return False


def upgrade_steps_file(steps_file: Path, *, write: bool = True) -> Dict[str, int]:
    """Legacy lab-stage migration has been removed; report scan counts only."""
    if not steps_file.exists():
        return {"files": 0, "changed_steps": 0, "scanned_steps": 0}

    try:
        with steps_file.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {"files": 0, "changed_steps": 0, "scanned_steps": 0}

    scanned_steps = 0
    for key, entries in data.items():
        if key == LAB_STEPS_META_KEY or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            scanned_steps += 1
    return {"files": 1, "changed_steps": 0, "scanned_steps": scanned_steps}


def upgrade_exported_steps(module: Union[str, Path], steps_file: Path, env: Optional[AgiEnv] = None) -> bool:
    """Legacy exported-stage migration has been removed; this is now a no-op."""
    return False


def pipeline_export_root(env: Optional[AgiEnv]) -> Path:
    """Return the effective export root, correcting empty/invalid AGI_EXPORT_DIR values."""
    home_root = Path(getattr(env, "home_abs", Path.home()) or Path.home()).expanduser().resolve()
    fallback = (home_root / "export").resolve()
    raw_candidates: List[Any] = []
    if env is not None:
        raw_candidates.append(getattr(env, "AGILAB_EXPORT_ABS", None))
        raw_candidates.append(getattr(getattr(env, "envars", {}), "get", lambda *_: None)("AGI_EXPORT_DIR"))
    raw_candidates.append(st.session_state.get("AGI_EXPORT_DIR"))
    raw_candidates.append(os.environ.get("AGI_EXPORT_DIR"))
    for raw in raw_candidates:
        if raw in (None, ""):
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (home_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if candidate == home_root:
            return fallback
        return candidate
    return fallback


def module_keys(module: Union[str, Path], env: Optional[AgiEnv] = None) -> List[str]:
    """Return preferred TOML keys for the provided module path."""
    raw_path = Path(module)
    keys: List[str] = []
    try:
        base = pipeline_export_root(env or st.session_state.get("env"))
        if raw_path.is_absolute():
            try:
                candidate = raw_path.resolve()
            except (OSError, RuntimeError):
                candidate = raw_path
        else:
            candidate = (base / raw_path).resolve()
        rel = str(candidate.relative_to(base))
        keys.append(rel)
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    keys.append(str(raw_path))
    ordered: List[str] = []
    seen: set[str] = set()
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered or [str(raw_path)]


def _append_unique(values: List[str], raw: Any) -> None:
    text = str(raw or "").strip()
    if not text:
        return
    if text not in values:
        values.append(text)


def _append_lab_name(values: List[str], raw: Any) -> None:
    text = str(raw or "").strip()
    if not text:
        return
    try:
        name = Path(text).expanduser().name
    except (OSError, RuntimeError, TypeError, ValueError):
        name = text.replace("\\", "/").rstrip("/").split("/")[-1]
    _append_unique(values, name or text)


def _lab_step_key_candidates(module: Union[str, Path], env: Optional[AgiEnv] = None) -> List[str]:
    names: List[str] = []
    for key in module_keys(module, env=env):
        _append_unique(names, key)
        _append_lab_name(names, key)
    if env is not None:
        for attr in ("target", "app", "active_app", "app_src"):
            _append_lab_name(names, getattr(env, attr, None))

    expanded: List[str] = []
    for name in names:
        _append_unique(expanded, name)
        if name.endswith("_project"):
            _append_unique(expanded, name.removesuffix("_project"))
        else:
            _append_unique(expanded, f"{name}_project")
    return expanded


def _dedupe_paths(paths: List[Path]) -> List[Path]:
    deduped: List[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            key = str(path.expanduser().resolve())
        except (OSError, RuntimeError, TypeError, ValueError):
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _coerce_app_dir(raw: Any) -> Optional[Path]:
    if raw in (None, ""):
        return None
    try:
        path = Path(raw).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return path.parent if path.name == "src" else path


def _candidate_lab_step_dirs(module: Union[str, Path], env: Optional[AgiEnv] = None) -> List[Path]:
    names = _lab_step_key_candidates(module, env=env)
    candidates: List[Path] = []

    if env is not None:
        for attr in ("active_app", "app_src"):
            app_dir = _coerce_app_dir(getattr(env, attr, None))
            if app_dir is not None:
                candidates.append(app_dir)

    roots: List[Path] = []
    if env is not None:
        for attr in ("apps_path", "builtin_apps_path", "apps_repository_root"):
            root = _coerce_app_dir(getattr(env, attr, None))
            if root is not None:
                roots.append(root)

    package_apps = Path(__file__).resolve().parent / "apps"
    repo_root = Path(__file__).resolve().parents[2]
    roots.extend(
        [
            package_apps,
            package_apps / "builtin",
            repo_root / "apps",
            repo_root / "src" / "agilab" / "apps",
        ]
    )

    for root in _dedupe_paths(roots):
        for name in names:
            candidates.extend(
                [
                    root / name,
                    root / "builtin" / name,
                    root / "apps" / name,
                    root / "apps" / "builtin" / name,
                    root / "src" / "agilab" / "apps" / name,
                    root / "src" / "agilab" / "apps" / "builtin" / name,
                ]
            )

    return _dedupe_paths(candidates)


def _iter_lab_steps_sources(
    module: Union[str, Path],
    steps_file: Path,
    env: Optional[AgiEnv] = None,
) -> Iterator[Path]:
    for app_dir in _candidate_lab_step_dirs(module, env=env):
        try:
            if not app_dir.is_dir():
                continue
        except (OSError, RuntimeError):
            continue
        exact = app_dir / steps_file.name
        if exact.is_file():
            yield exact
        try:
            for source in sorted(app_dir.glob("lab_steps*.toml")):
                if source != exact and source.is_file():
                    yield source
        except OSError:
            continue


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except (FileNotFoundError, OSError):
        try:
            return left.expanduser().resolve() == right.expanduser().resolve()
        except (OSError, RuntimeError):
            return str(left) == str(right)


def _select_lab_steps_payload(
    source: Path,
    key_candidates: List[str],
) -> Optional[Tuple[Dict[str, Any], str, List[Dict[str, Any]]]]:
    try:
        with source.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None

    def _usable(key: str, entries: Any) -> Optional[Tuple[Dict[str, Any], str, List[Dict[str, Any]]]]:
        if not isinstance(entries, list):
            return None
        typed_entries = [entry for entry in entries if isinstance(entry, dict)]
        if not prune_invalid_entries(typed_entries):
            return None
        return data, key, typed_entries

    for key in key_candidates:
        selected = _usable(key, data.get(key))
        if selected is not None:
            return selected

    fallback: List[Tuple[Dict[str, Any], str, List[Dict[str, Any]]]] = []
    for key, entries in data.items():
        if key == LAB_STEPS_META_KEY:
            continue
        selected = _usable(str(key), entries)
        if selected is not None:
            fallback.append(selected)
    return fallback[0] if len(fallback) == 1 else None


def restore_missing_export_steps(
    module: Union[str, Path],
    steps_file: Path,
    env: Optional[AgiEnv] = None,
) -> Optional[Path]:
    """Restore a missing/empty exported lab_steps.toml from the app source tree.

    The export copy is user-editable state, so this function deliberately refuses
    to overwrite any non-empty file.
    """
    target = Path(steps_file)
    try:
        if target.exists() and target.stat().st_size > 0:
            return None
    except OSError:
        return None

    env_obj = env or st.session_state.get("env")
    primary_key = module_keys(module, env=env_obj)[0]
    key_candidates = _lab_step_key_candidates(module, env=env_obj)
    if primary_key not in key_candidates:
        key_candidates.insert(0, primary_key)

    for source in _iter_lab_steps_sources(module, target, env=env_obj):
        if _same_path(source, target):
            continue
        selected = _select_lab_steps_payload(source, key_candidates)
        if selected is None:
            continue

        data, source_key, entries = selected
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            normalized = dict(data)
            if source_key != primary_key:
                normalized[primary_key] = entries
                for key in key_candidates:
                    if key != primary_key:
                        normalized.pop(key, None)
            meta = normalized.get(LAB_STEPS_META_KEY)
            if isinstance(meta, dict):
                primary_meta_key = sequence_meta_key(primary_key)
                for key in key_candidates:
                    old_meta_key = sequence_meta_key(key)
                    if old_meta_key in meta and primary_meta_key not in meta:
                        meta[primary_meta_key] = meta[old_meta_key]
                for key in key_candidates:
                    old_meta_key = sequence_meta_key(key)
                    if old_meta_key != primary_meta_key:
                        meta.pop(old_meta_key, None)
            with target.open("wb") as handle:
                tomli_w.dump(_convert_paths_to_strings(prepare_lab_steps_for_write(normalized)), handle)
            logger.info("Restored missing Workflow stage contract %s from %s", target, source)
            return source
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to restore Workflow stage contract %s from %s: %s", target, source, exc)
    return None


def ensure_primary_module_key(module: Union[str, Path], steps_file: Path, env: Optional[AgiEnv] = None) -> None:
    """Ensure stages are stored under the primary module key."""
    if not steps_file.exists():
        return
    try:
        with steps_file.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return

    keys = module_keys(module, env=env)
    primary = keys[0]
    base = pipeline_export_root(env or st.session_state.get("env"))
    module_path = Path(module)
    try:
        resolved_module = module_path.expanduser().resolve()
    except (OSError, RuntimeError):
        resolved_module = module_path.expanduser()

    def _matches_module(candidate_key: str) -> bool:
        if candidate_key in keys:
            return True
        key_path = Path(candidate_key).expanduser()
        try:
            if key_path.is_absolute():
                return key_path.resolve() == resolved_module
            return (base / key_path).resolve() == resolved_module
        except (OSError, RuntimeError):
            return False

    candidates: List[Tuple[str, List[Dict[str, Any]]]] = []
    for key, entries in data.items():
        if key == LAB_STEPS_META_KEY:
            continue
        if isinstance(entries, list) and entries and _matches_module(str(key)):
            candidates.append((key, entries))

    if not candidates:
        return

    candidates.sort(key=lambda kv: (len(kv[1]), kv[0] != primary), reverse=True)
    best_key, best_entries = candidates[0]
    changed = best_key != primary or any(key != primary for key, _ in candidates[1:])
    if not changed:
        return

    data[primary] = best_entries
    for key, _ in candidates:
        if key != primary:
            data.pop(key, None)

    try:
        with steps_file.open("wb") as handle:
            tomli_w.dump(_convert_paths_to_strings(prepare_lab_steps_for_write(data)), handle)
    except (OSError, TypeError, ValueError):
        logger.warning("Failed to normalize module keys for %s", steps_file)


def sequence_meta_key(module_key: str) -> str:
    return f"{module_key}__sequence"


def load_sequence_preferences(module: Union[str, Path], steps_file: Path, env: Optional[AgiEnv] = None) -> List[int]:
    """Return the stored execution order for a module, if any."""
    module_key = module_keys(module, env=env)[0]
    try:
        with steps_file.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return []
    except tomllib.TOMLDecodeError as exc:
        logger.warning("Failed to parse sequence metadata from %s: %s", steps_file, exc)
        return []
    meta = data.get(LAB_STEPS_META_KEY, {})
    if not isinstance(meta, dict):
        return []
    raw_sequence = meta.get(sequence_meta_key(module_key), [])
    if not isinstance(raw_sequence, list):
        return []
    return [idx for idx in raw_sequence if isinstance(idx, int) and idx >= 0]


def persist_sequence_preferences(
    module: Union[str, Path],
    steps_file: Path,
    sequence: List[int],
    env: Optional[AgiEnv] = None,
) -> None:
    """Persist the execution sequence ordering alongside the stage contract."""
    module_key = module_keys(module, env=env)[0]
    normalized = [int(idx) for idx in sequence if isinstance(idx, int) and idx >= 0]
    try:
        if steps_file.exists():
            with steps_file.open("rb") as handle:
                data = tomllib.load(handle)
        else:
            data = {}
    except tomllib.TOMLDecodeError as exc:
        logger.error("Failed to load stages while saving sequence metadata: %s", exc)
        return
    try:
        prepare_lab_steps_for_write(data)
    except ValueError as exc:
        logger.error("Refusing to persist execution sequence to %s: %s", steps_file, exc)
        return
    meta = data.setdefault(LAB_STEPS_META_KEY, {})
    meta_key = sequence_meta_key(module_key)
    if meta.get(meta_key) == normalized:
        return
    meta[meta_key] = normalized
    try:
        steps_file.parent.mkdir(parents=True, exist_ok=True)
        with steps_file.open("wb") as handle:
            tomli_w.dump(_convert_paths_to_strings(prepare_lab_steps_for_write(data)), handle)
    except (OSError, TypeError, ValueError) as exc:
        logger.error("Failed to persist execution sequence to %s: %s", steps_file, exc)


def is_displayable_step(entry: Dict[str, Any]) -> bool:
    """Return True if a stage should be shown in the UI."""
    if not entry:
        return False
    question = entry.get("Q", "")
    if isinstance(question, str) and question.strip():
        return True
    code = entry.get("C", "")
    if isinstance(code, str) and code.strip():
        return True
    return False


def is_runnable_step(entry: Dict[str, Any]) -> bool:
    """Return True if a stage has executable code content."""
    if not entry:
        return False
    code = entry.get("C", "")
    return isinstance(code, str) and bool(code.strip())


def legacy_agi_run_call_lines(code: Any) -> List[int]:
    """Return line numbers for direct legacy ``AGI.run(..., mode=...)`` calls."""
    if not isinstance(code, str) or "AGI.run" not in code:
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    lines: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "run"
            and isinstance(func.value, ast.Name)
            and func.value.id == "AGI"
        ):
            continue
        keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
        has_request_keyword = "request" in keyword_names
        has_kwargs_expansion = any(kw.arg is None for kw in node.keywords)
        has_legacy_keyword = bool(keyword_names & LEGACY_AGI_RUN_KEYWORDS)
        if not has_request_keyword and (has_legacy_keyword or has_kwargs_expansion):
            lines.append(int(getattr(node, "lineno", 0) or 0))
    return sorted(set(lines))


def find_legacy_agi_run_steps(
    steps: List[Dict[str, Any]],
    sequence: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Return selected pipeline stages that still use the pre-RunRequest AGI.run API."""
    selected = sequence if sequence is not None else list(range(len(steps)))
    stale_steps: List[Dict[str, Any]] = []
    for idx in selected:
        if idx < 0 or idx >= len(steps):
            continue
        entry = steps[idx]
        if not isinstance(entry, dict) or not is_runnable_step(entry):
            continue
        lines = legacy_agi_run_call_lines(entry.get("C", ""))
        if not lines:
            continue
        stale_steps.append(
            {
                "index": idx,
                "step": idx + 1,
                "line": lines[0],
                "lines": lines,
                "summary": step_summary(entry, width=80),
                "project": step_project_name(entry),
            }
        )
    return stale_steps


def looks_like_step(value: Any) -> bool:
    """Heuristic: True when value represents a non-negative integer stage index."""
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False


def prune_invalid_entries(entries: List[Dict[str, Any]], keep_index: Optional[int] = None) -> List[Dict[str, Any]]:
    """Remove invalid stages, optionally preserving the entry at keep_index."""
    pruned: List[Dict[str, Any]] = []
    for idx, entry in enumerate(entries):
        if is_displayable_step(entry) or (keep_index is not None and idx == keep_index):
            pruned.append(entry)
    return pruned


def bump_history_revision() -> None:
    """Increment the history revision so the HISTORY tab refreshes."""
    st.session_state["history_rev"] = st.session_state.get("history_rev", 0) + 1


def _normalize_venv_root(candidate: Path) -> Optional[Path]:
    """Return the resolved virtual environment directory when present."""
    try:
        path = candidate.expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        path = candidate
    if not path.exists() or not path.is_dir():
        return None
    cfg = path / "pyvenv.cfg"
    if cfg.exists():
        try:
            return path.resolve()
        except (OSError, RuntimeError):
            return path
    return None


def _iter_venv_roots(base: Path) -> Iterator[Path]:
    """Yield virtual environments discovered directly underneath ``base``."""
    direct = _normalize_venv_root(base)
    if direct:
        yield direct
    dot = _normalize_venv_root(base / ".venv")
    if dot:
        yield dot
    try:
        for child in base.iterdir():
            if not child.is_dir():
                continue
            direct_child = _normalize_venv_root(child)
            if direct_child:
                yield direct_child
            dot_child = _normalize_venv_root(child / ".venv")
            if dot_child:
                yield dot_child
    except OSError:
        return


@st.cache_data(show_spinner=False)
def _cached_virtualenvs(base_dirs: Tuple[str, ...]) -> List[str]:
    """Return cached virtual environment paths under ``base_dirs``."""
    discovered: List[str] = []
    seen: set[str] = set()
    for raw in base_dirs:
        if not raw:
            continue
        base = Path(raw)
        if not base.exists() or not base.is_dir():
            continue
        for venv_root in _iter_venv_roots(base):
            key = str(venv_root)
            if key in seen:
                continue
            seen.add(key)
            discovered.append(key)
    discovered.sort()
    return discovered


def get_available_virtualenvs(env: AgiEnv) -> List[Path]:
    """Return virtual environments relevant to the active AGILab session."""
    base_dirs: List[str] = [str(Path(env.active_app)), str(Path(env.apps_path))]
    if env.runenv:
        base_dirs.append(str(Path(env.runenv)))
    if env.wenv_abs:
        base_dirs.append(str(Path(env.wenv_abs)))
    if env.agi_env:
        base_dirs.append(str(Path(env.agi_env)))
    cache_key = tuple(dict.fromkeys(base_dirs))
    venv_paths = _cached_virtualenvs(cache_key) if cache_key else []
    return [Path(path) for path in venv_paths]


def snippet_source_guidance(has_snippets: bool, app_name: str) -> str:
    """Return the explanatory message displayed near the stage source selector."""
    if has_snippets:
        return (
            f"Snippets are refreshed from the latest ORCHESTRATE run for `{app_name}`. "
            "If they look stale, rerun INSTALL → DISTRIBUTE → RUN in ORCHESTRATE."
        )
    return (
        "No ORCHESTRATE-generated snippet is available yet. "
        "Run INSTALL → DISTRIBUTE → RUN in ORCHESTRATE first (same project) "
        "to generate the INSTALL / DISTRIBUTE / RUN snippets, then come back to WORKFLOW."
    )


def is_orchestrate_locked_step(entry: Dict[str, Any]) -> bool:
    """Return True for stages that originated from an ORCHESTRATE snippet."""
    if not isinstance(entry, dict):
        return False
    value = entry.get(ORCHESTRATE_LOCKED_STEP_KEY)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    question = (entry.get("Q") or "").strip().lower()
    return question.startswith("imported snippet:")


def orchestrate_snippet_source(entry: Dict[str, Any]) -> str:
    """Return the source filename for a locked ORCHESTRATE-derived stage."""
    if not isinstance(entry, dict):
        return ""
    source = entry.get(ORCHESTRATE_LOCKED_SOURCE_KEY)
    if isinstance(source, str) and source.strip():
        return source.strip()
    question = (entry.get("Q") or "").strip()
    lower_question = question.lower()
    if lower_question.startswith("imported snippet:"):
        prefix_len = len("Imported snippet:")
        return question[prefix_len:].strip()
    return ""
