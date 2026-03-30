from __future__ import annotations

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

import tomllib
import types


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


pipeline_steps = _import_agilab_module("agilab.pipeline_steps")


def test_normalize_runtime_path_prefers_existing_app(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    app_dir = apps_root / "flight_project"
    app_dir.mkdir()

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)

    env = SimpleNamespace(apps_path=apps_root)
    normalized = pipeline_steps.normalize_runtime_path("flight_project", env=env)

    assert normalized == str(app_dir)


def test_module_key_normalization_and_sequence_roundtrip(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_dir = export_root / "flight_project"
    module_dir.mkdir(parents=True)
    steps_file = tmp_path / "lab_steps.toml"
    absolute_key = str(module_dir.resolve())
    steps_file.write_text(
        f'[[ "{absolute_key}" ]]\n'
        'Q = "First step"\n'
        'C = "print(1)"\n',
        encoding="utf-8",
    )

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})

    pipeline_steps.ensure_primary_module_key(module_dir, steps_file, env=env)
    pipeline_steps.persist_sequence_preferences(module_dir, steps_file, [2, 0, 1], env=env)

    data = tomllib.loads(steps_file.read_text(encoding="utf-8"))
    assert "flight_project" in data
    assert absolute_key not in data
    assert pipeline_steps.load_sequence_preferences(module_dir, steps_file, env=env) == [2, 0, 1]


def test_get_available_virtualenvs_discovers_direct_and_nested_envs(monkeypatch, tmp_path):
    active_app = tmp_path / "apps" / "flight_project"
    apps_path = tmp_path / "apps"
    runenv = tmp_path / "runenv"
    direct = active_app / ".venv"
    nested = runenv / "worker_a"
    nested_venv = nested / ".venv"
    for path in (direct, nested_venv):
        path.mkdir(parents=True)
        (path / "pyvenv.cfg").write_text("home = /tmp/python\n", encoding="utf-8")

    env = SimpleNamespace(
        active_app=active_app,
        apps_path=apps_path,
        runenv=runenv,
        wenv_abs="",
        agi_env="",
    )

    pipeline_steps._cached_virtualenvs.clear()
    discovered = pipeline_steps.get_available_virtualenvs(env)

    assert direct.resolve() in discovered
    assert nested_venv.resolve() in discovered


def test_orchestrate_lock_helpers_cover_bool_and_question_forms():
    locked = {
        pipeline_steps.ORCHESTRATE_LOCKED_STEP_KEY: "yes",
        pipeline_steps.ORCHESTRATE_LOCKED_SOURCE_KEY: "AGI_run.py",
    }
    inferred = {"Q": "Imported snippet: generated_step.py"}

    assert pipeline_steps.is_orchestrate_locked_step(locked) is True
    assert pipeline_steps.orchestrate_snippet_source(locked) == "AGI_run.py"
    assert pipeline_steps.is_orchestrate_locked_step(inferred) is True
    assert pipeline_steps.orchestrate_snippet_source(inferred) == "generated_step.py"


def test_prune_invalid_entries_keeps_requested_index():
    entries = [
        {"Q": "Visible"},
        {"Q": "", "C": ""},
        {"C": "print('ok')"},
    ]

    pruned = pipeline_steps.prune_invalid_entries(entries, keep_index=1)

    assert pruned == entries


def test_upgrade_exported_steps_is_noop_and_preserves_file(monkeypatch, tmp_path):
    export_root = tmp_path / "export"
    module_dir = export_root / "sb3_trainer_project"
    module_dir.mkdir(parents=True)
    steps_file = tmp_path / "lab_steps.toml"
    original = (
        '[[sb3_trainer_project]]\n'
        'Q = "Legacy step"\n'
        'C = """from pathlib import Path\n'
        'import agilab\n'
        'from agi_env import AgiEnv\n'
        '\n'
        'APP = "sb3_trainer_project"\n'
        'APPS_DIR = Path(agilab.__file__).resolve().parent / "apps"\n'
        'PROJECT_SRC = APPS_DIR / APP / "src"\n'
        'env = AgiEnv(apps_dir=APPS_DIR, app=APP, verbose=1)\n'
        '"""\n'
    )
    steps_file.write_text(original, encoding="utf-8")

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})

    changed = pipeline_steps.upgrade_exported_steps(module_dir, steps_file, env=env)

    assert changed is False
    assert steps_file.read_text(encoding="utf-8") == original


def test_upgrade_steps_file_reports_scan_without_rewriting(tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    original = (
        '[[alpha]]\n'
        'C = """from pathlib import Path\nimport agilab\nAPP = "alpha"\nAPPS_DIR = Path(agilab.__file__).resolve().parent / "apps"\n"""\n'
        '[[beta]]\n'
        'C = """print(1)"""\n'
    )
    steps_file.write_text(original, encoding="utf-8")

    result = pipeline_steps.upgrade_steps_file(steps_file)

    assert result == {"files": 1, "changed_steps": 0, "scanned_steps": 2}
    assert steps_file.read_text(encoding="utf-8") == original


def test_upgrade_legacy_helpers_are_noop():
    code = (
        "from pathlib import Path\n"
        "import agilab\n"
        'APP = "network_sim_project"\n'
        'APPS_DIR = Path(agilab.__file__).resolve().parent / "apps"\n'
    )
    assert pipeline_steps.upgrade_legacy_step_code(code) == code
    assert pipeline_steps.upgrade_legacy_step_runtime(
        "Refresh network_sim worker before building topology/demands.",
        engine="agi.install",
        app_name="network_sim_project",
    ) == "Refresh network_sim worker before building topology/demands."
    assert pipeline_steps.upgrade_legacy_step_entry({"C": code, "E": "legacy text", "R": "agi.run"}) is False


def test_normalize_imported_orchestrate_snippet_keeps_sb3_worker_snippet_unchanged():
    code = (
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n\n"
        "from agi_env import AgiEnv\n\n"
        'APP = "sb3_trainer_project"\n\n'
        'APPS_PATH_RAW = os.environ.get("APPS_PATH", "").strip()\n\n'
        "APPS_PATH = Path(APPS_PATH_RAW).expanduser()\n\n"
        "APP_ROOT = APPS_PATH / APP\n"
        'PROJECT_SRC = APP_ROOT / "src"\n'
        "if str(PROJECT_SRC) not in sys.path:\n"
        "    sys.path.insert(0, str(PROJECT_SRC))\n\n"
        "from sb3_trainer_worker.sb3_trainer_worker import Sb3TrainerWorker\n\n"
        "env = AgiEnv(apps_path=APPS_PATH, app=APP, verbose=1)\n"
        "worker = Sb3TrainerWorker()\n"
        "worker.env = env\n"
        "res = worker.trainer_ilp_stepper({}, None)\n"
        "print(res)\n"
    )

    normalized, engine, runtime = pipeline_steps.normalize_imported_orchestrate_snippet(
        code,
        default_runtime="sb3_trainer_project",
    )

    assert normalized == code
    assert engine == "runpy"
    assert runtime == "sb3_trainer_project"


def test_normalize_imported_orchestrate_snippet_infers_agi_runtime_without_rewrite():
    code = (
        "import asyncio\n"
        "from agi_cluster.agi_distributor import AGI\n"
        "from agi_env import AgiEnv\n"
        'APP = "flight_trajectory_project"\n'
    )

    normalized, engine, runtime = pipeline_steps.normalize_imported_orchestrate_snippet(
        code,
        default_runtime="network_sim_project",
    )

    assert normalized == code
    assert engine == "agi.run"
    assert runtime == "flight_trajectory_project"


def test_normalize_imported_orchestrate_snippet_keeps_runpy_runtime():
    code = (
        "import os\n"
        "import pandas as pd\n"
        "from agi_env import AgiEnv\n"
        'SUMMARY_PARQUET = DATA_ROOT / "link_level_summary.parquet"\n'
        "df = pd.read_parquet(path)\n"
    )

    normalized, engine, runtime = pipeline_steps.normalize_imported_orchestrate_snippet(
        code,
        default_runtime="network_sim_project",
    )

    assert normalized == code
    assert engine == "runpy"
    assert runtime == "network_sim_project"
