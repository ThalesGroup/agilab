from __future__ import annotations

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

logger = logging.getLogger(__name__)


def _apps_path_bootstrap(app_name: str) -> str:
    return (
        f'APP = "{app_name}"\n\n'
        'APPS_PATH_RAW = os.environ.get("APPS_PATH", "").strip()\n\n'
        'if not APPS_PATH_RAW:\n\n'
        '    raise RuntimeError(\n\n'
        '        "APPS_PATH is not set. Run this snippet from AGILab PIPELINE/ORCHESTRATE, "\n\n'
        '        "or export APPS_PATH before executing it."\n\n'
        '    )\n\n'
        'APPS_PATH = Path(APPS_PATH_RAW).expanduser()\n\n'
        'APP_ROOT = APPS_PATH / APP\n'
    )


def normalize_imported_orchestrate_snippet(
    code: Any,
    *,
    default_runtime: str = "",
) -> tuple[Any, str, str]:
    """Normalize an imported ORCHESTRATE snippet and infer its execution mode."""
    if not isinstance(code, str):
        return code, "agi.run" if default_runtime else "runpy", default_runtime

    updated = upgrade_legacy_step_code(code)
    app_name = extract_step_app_name(updated)
    runtime = app_name or default_runtime

    if (
        "from sb3_trainer_worker.sb3_trainer_worker import Sb3TrainerWorker" in updated
        and "trainer_ilp_stepper" in updated
    ):
        updated = (
            "import asyncio\n"
            "import os\n"
            "from pathlib import Path\n\n"
            "from agi_cluster.agi_distributor import AGI\n"
            "from agi_env import AgiEnv\n\n"
            f"{_apps_path_bootstrap(app_name or 'sb3_trainer_project')}"
            "async def main():\n"
            "    app_env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)\n"
            "    share = app_env.share_root_path()\n"
            "    res = await AGI.run(\n"
            "        app_env,\n"
            "        mode=4,\n"
            "        data_in=str(share / \"network_sim/pipeline\"),\n"
            "        data_out=str(share / \"sb3_trainer/dataframe\"),\n"
            "        args=[\n"
            "            {\n"
            "                \"name\": \"ilp_stepper\",\n"
            "                \"args\": {\n"
            "                    \"data_in\": \"network_sim/pipeline\",\n"
            "                    \"data_out\": \"sb3_trainer/dataframe\",\n"
            "                    \"time_horizon\": 16,\n"
            "                    \"trajectories_glob\": \"flight_trajectory/pipeline/*.parquet\",\n"
            "                    \"sat_trajectories_glob\": \"sat_trajectory/pipeline/*.parquet\",\n"
            "                },\n"
            "            },\n"
            "        ],\n"
            "    )\n"
            "    print(res)\n"
            "    return res\n\n\n"
            "if __name__ == \"__main__\":\n"
            "    asyncio.run(main())\n"
        )
        return updated, "agi.run", runtime

    if (
        "link_level_summary.parquet" in updated
        and "pd.read_parquet" in updated
        and "from agi_env import AgiEnv" in updated
    ):
        return updated, "runpy", ""

    if "from agi_cluster.agi_distributor import AGI" in updated or "AGI." in updated:
        return updated, "agi.run", runtime

    return updated, "runpy", ""


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
    except Exception:
        return str(raw)

    env_obj = env or st.session_state.get("env")
    apps_root: Optional[Path] = None
    try:
        apps_root = Path(env_obj.apps_path).expanduser()  # type: ignore[attr-defined]
    except Exception:
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
    """Return a concise summary for a step entry."""
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


def step_label_for_multiselect(idx: int, entry: Optional[Dict[str, Any]]) -> str:
    """Label for the step-order multiselect widget."""
    summary = step_summary(entry)
    return f"Step {idx + 1}: {summary}" if summary else f"Step {idx + 1}"


def step_button_label(display_idx: int, step_idx: int, entry: Optional[Dict[str, Any]]) -> str:
    """Label for a rendered step button respecting the selected order."""
    summary = step_summary(entry)
    if summary:
        return f"{display_idx + 1}. {summary}"
    return f"{display_idx + 1}. Step {step_idx + 1}"


def upgrade_legacy_step_code(code: Any) -> Any:
    """Rewrite known legacy AGI app snippets to the current APPS_PATH/app form."""
    if not isinstance(code, str) or not code:
        return code

    updated = code
    if (
        "import agilab" not in updated
        and "APPS_DIR" not in updated
        and "apps_dir=APPS_DIR" not in updated
        and "APP_ROOT = APPS_ROOT / APP" not in updated
        and "APPS_ROOT = Path.cwd().resolve().parent" not in updated
        and "agilab.__file__" not in updated
        and "Path(sys.executable).resolve().parents[2]" not in updated
        and "Path(sys.prefix).resolve().parent" not in updated
    ):
        return updated

    updated = re.sub(r"(?m)^\s*import agilab\s*\n?", "", updated)
    updated = re.sub(
        r"(?m)^(?P<indent>\s*)APPS_DIR\s*=\s*.*agilab\.__file__.*$",
        "",
        updated,
    )
    updated = re.sub(r"(?m)^\s*APPS_ROOT\s*=\s*Path\.cwd\(\)\.resolve\(\)\.parent\s*\n?", "", updated)
    updated = updated.replace('PROJECT_SRC = APPS_DIR / APP / "src"', 'PROJECT_SRC = APP_ROOT / "src"')
    updated = updated.replace("PROJECT_SRC = APPS_DIR / APP / 'src'", "PROJECT_SRC = APP_ROOT / 'src'")
    updated = updated.replace("APPS_DIR / APP /", "APP_ROOT /")
    updated = updated.replace("APPS_DIR / APP", "APP_ROOT")
    updated = re.sub(r"(?m)^\s*APP_ROOT\s*=\s*APPS_ROOT\s*/\s*APP\s*\n?", "", updated)
    updated = re.sub(
        r"(?m)^\s*APP_ROOT\s*=\s*Path\(sys\.executable\)\.resolve\(\)\.parents\[2\]\s*\n?",
        "",
        updated,
    )
    updated = re.sub(
        r"(?m)^\s*APP_ROOT\s*=\s*Path\(sys\.prefix\)\.resolve\(\)\.parent\s*\n?",
        "",
        updated,
    )

    if (
        "Path(sys.executable).resolve().parents[2]" in updated
        or "Path(sys.prefix).resolve().parent" in updated
    ) and "import sys" not in updated:
        if "from pathlib import Path\n" in updated:
            updated = updated.replace("from pathlib import Path\n", "from pathlib import Path\nimport sys\n", 1)
        else:
            updated = f"import sys\n{updated}"

    def _insert_app_root(match: re.Match[str]) -> str:
        indent = match.group("indent")
        app_value = match.group("app")
        return (
            f'{indent}APP = {app_value}\n'
            f'{indent}APPS_PATH_RAW = os.environ.get("APPS_PATH", "").strip()\n'
            f'{indent}if not APPS_PATH_RAW:\n'
            f'{indent}    raise RuntimeError(\n'
            f'{indent}        "APPS_PATH is not set. Run this snippet from AGILab PIPELINE/ORCHESTRATE, "\n'
            f'{indent}        "or export APPS_PATH before executing it."\n'
            f'{indent}    )\n'
            f'{indent}APPS_PATH = Path(APPS_PATH_RAW).expanduser()\n'
            f'{indent}APP_ROOT = APPS_PATH / APP'
        )

    updated = re.sub(
        r'(?m)^(?P<indent>\s*)APP\s*=\s*(?P<app>["\'][^"\']+["\'])\s*$',
        _insert_app_root,
        updated,
        count=1,
    )
    if "APPS_PATH_RAW = os.environ.get(" in updated and "import os" not in updated:
        if "from pathlib import Path\n" in updated:
            updated = updated.replace("from pathlib import Path\n", "import os\nfrom pathlib import Path\n", 1)
        else:
            updated = f"import os\n{updated}"
    updated = re.sub(
        r"AgiEnv\(\s*apps_(?:dir|path)\s*=\s*APPS_DIR\s*,\s*app\s*=\s*APP\s*,\s*",
        "AgiEnv(apps_path=APPS_PATH, app=APP, ",
        updated,
    )
    updated = re.sub(
        r"AgiEnv\(\s*apps_(?:dir|path)\s*=\s*APPS_DIR\s*,\s*app\s*=\s*APP\s*\)",
        "AgiEnv(apps_path=APPS_PATH, app=APP)",
        updated,
    )
    updated = re.sub(
        r"AgiEnv\(\s*active_app\s*=\s*APP_ROOT\s*,\s*",
        "AgiEnv(apps_path=APPS_PATH, app=APP, ",
        updated,
    )
    updated = re.sub(
        r"AgiEnv\(\s*active_app\s*=\s*APP_ROOT\s*\)",
        "AgiEnv(apps_path=APPS_PATH, app=APP)",
        updated,
    )
    return updated


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
    """Replace descriptive legacy runtime text with the actual app runtime key."""
    if not app_name or not str(engine or "").startswith("agi."):
        return raw_runtime
    if looks_like_runtime_reference(raw_runtime):
        return raw_runtime
    return app_name


def upgrade_legacy_step_entry(entry: Any) -> bool:
    """Upgrade one saved step entry in place."""
    if not isinstance(entry, dict):
        return False

    changed = False
    original_code = entry.get("C")
    upgraded_code = upgrade_legacy_step_code(original_code)
    if upgraded_code != original_code:
        entry["C"] = upgraded_code
        changed = True

    app_name = extract_step_app_name(entry.get("C"))
    original_runtime = entry.get("E")
    upgraded_runtime = upgrade_legacy_step_runtime(
        original_runtime,
        engine=entry.get("R"),
        app_name=app_name,
    )
    if upgraded_runtime != original_runtime:
        entry["E"] = upgraded_runtime
        changed = True

    return changed


def upgrade_steps_file(steps_file: Path, *, write: bool = True) -> Dict[str, int]:
    """Upgrade every recognized legacy step snippet in a lab steps file."""
    if not steps_file.exists():
        return {"files": 0, "changed_steps": 0, "scanned_steps": 0}

    try:
        with steps_file.open("rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return {"files": 0, "changed_steps": 0, "scanned_steps": 0}

    changed = False
    changed_steps = 0
    scanned_steps = 0
    for key, entries in data.items():
        if key == "__meta__" or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            scanned_steps += 1
            if upgrade_legacy_step_entry(entry):
                changed = True
                changed_steps += 1

    if changed and write:
        try:
            steps_file.parent.mkdir(parents=True, exist_ok=True)
            with steps_file.open("wb") as handle:
                tomli_w.dump(_convert_paths_to_strings(data), handle)
        except Exception as exc:
            logger.warning("Failed to persist upgraded exported steps to %s: %s", steps_file, exc)
            return {"files": 0, "changed_steps": 0, "scanned_steps": scanned_steps}
    return {"files": 1, "changed_steps": changed_steps, "scanned_steps": scanned_steps}


def upgrade_exported_steps(module: Union[str, Path], steps_file: Path, env: Optional[AgiEnv] = None) -> bool:
    """Persist known step-code migrations directly in the exported lab steps file."""
    if not steps_file.exists():
        return False

    module_path = Path(module)
    ensure_primary_module_key(module_path, steps_file, env=env)
    return bool(upgrade_steps_file(steps_file)["changed_steps"])


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
            except Exception:
                candidate = raw_path
        else:
            candidate = (base / raw_path).resolve()
        rel = str(candidate.relative_to(base))
        keys.append(rel)
    except Exception:
        pass
    keys.append(str(raw_path))
    ordered: List[str] = []
    seen: set[str] = set()
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered or [str(raw_path)]


def ensure_primary_module_key(module: Union[str, Path], steps_file: Path, env: Optional[AgiEnv] = None) -> None:
    """Ensure steps are stored under the primary module key."""
    if not steps_file.exists():
        return
    try:
        with steps_file.open("rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return

    keys = module_keys(module, env=env)
    primary = keys[0]
    base = pipeline_export_root(env or st.session_state.get("env"))
    module_path = Path(module)
    try:
        resolved_module = module_path.expanduser().resolve()
    except Exception:
        resolved_module = module_path.expanduser()

    def _matches_module(candidate_key: str) -> bool:
        if candidate_key in keys:
            return True
        try:
            key_path = Path(candidate_key).expanduser()
        except Exception:
            return False
        try:
            if key_path.is_absolute():
                return key_path.resolve() == resolved_module
            return (base / key_path).resolve() == resolved_module
        except Exception:
            return False

    candidates: List[Tuple[str, List[Dict[str, Any]]]] = []
    for key, entries in data.items():
        if key == "__meta__":
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
            tomli_w.dump(_convert_paths_to_strings(data), handle)
    except Exception:
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
    meta = data.get("__meta__", {})
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
    """Persist the execution sequence ordering alongside the steps file."""
    module_key = module_keys(module, env=env)[0]
    normalized = [int(idx) for idx in sequence if isinstance(idx, int) and idx >= 0]
    try:
        if steps_file.exists():
            with steps_file.open("rb") as handle:
                data = tomllib.load(handle)
        else:
            data = {}
    except tomllib.TOMLDecodeError as exc:
        logger.error("Failed to load steps while saving sequence metadata: %s", exc)
        return
    meta = data.setdefault("__meta__", {})
    meta_key = sequence_meta_key(module_key)
    if meta.get(meta_key) == normalized:
        return
    meta[meta_key] = normalized
    try:
        steps_file.parent.mkdir(parents=True, exist_ok=True)
        with steps_file.open("wb") as handle:
            tomli_w.dump(_convert_paths_to_strings(data), handle)
    except Exception as exc:
        logger.error("Failed to persist execution sequence to %s: %s", steps_file, exc)


def is_displayable_step(entry: Dict[str, Any]) -> bool:
    """Return True if a step should be shown in the UI."""
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
    """Return True if a step has executable code content."""
    if not entry:
        return False
    code = entry.get("C", "")
    return isinstance(code, str) and bool(code.strip())


def looks_like_step(value: Any) -> bool:
    """Heuristic: True when value represents a non-negative integer step index."""
    try:
        return int(value) >= 0
    except Exception:
        return False


def prune_invalid_entries(entries: List[Dict[str, Any]], keep_index: Optional[int] = None) -> List[Dict[str, Any]]:
    """Remove invalid steps, optionally preserving the entry at keep_index."""
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
    except Exception:
        path = candidate
    if not path.exists() or not path.is_dir():
        return None
    cfg = path / "pyvenv.cfg"
    if cfg.exists():
        try:
            return path.resolve()
        except Exception:
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
    """Return the explanatory message displayed near the step source selector."""
    if has_snippets:
        return (
            f"Snippets are refreshed from the latest ORCHESTRATE run for `{app_name}`. "
            "If they look stale, rerun INSTALL → DISTRIBUTE → RUN in ORCHESTRATE."
        )
    return (
        "No ORCHESTRATE-generated snippet is available yet. "
        "Run INSTALL → DISTRIBUTE → RUN in ORCHESTRATE first (same project) "
        "to generate the INSTALL / DISTRIBUTE / RUN snippets, then come back to PIPELINE."
    )


def is_orchestrate_locked_step(entry: Dict[str, Any]) -> bool:
    """Return True for steps that originated from an ORCHESTRATE snippet."""
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
    """Return the source filename for a locked ORCHESTRATE-derived step."""
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
