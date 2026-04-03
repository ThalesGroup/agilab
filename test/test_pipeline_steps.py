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


def test_step_project_name_prefers_app_name_from_snippet():
    entry = {
        "C": (
            "import asyncio\n"
            'APP = "sb3_trainer_project"\n'
            "print('run')\n"
        ),
        "E": "/tmp/other_project",
    }

    assert pipeline_steps.step_project_name(entry) == "sb3_trainer_project"


def test_step_label_for_multiselect_includes_project_name_from_runtime(monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    network_sim = apps_root / "network_sim_project"
    network_sim.mkdir()

    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)
    env = SimpleNamespace(apps_path=apps_root)
    entry = {"Q": "Build topology and demands", "E": "network_sim_project"}

    label = pipeline_steps.step_label_for_multiselect(2, entry, env=env)

    assert label == "Step 3: [network_sim_project] Build topology and demands"


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


def test_pipeline_steps_helper_utilities_cover_runtime_and_summary_branches(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"AGI_EXPORT_DIR": "relative-export"})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)

    env = SimpleNamespace(
        home_abs=tmp_path,
        AGILAB_EXPORT_ABS=tmp_path,
        envars={"AGI_EXPORT_DIR": ""},
    )

    assert pipeline_steps.normalize_imported_orchestrate_snippet(None, default_runtime="demo") == (None, "agi.run", "demo")
    assert pipeline_steps._convert_paths_to_strings({"path": Path("demo"), "items": [Path("/tmp/x")]}) == {
        "path": "demo",
        "items": ["/tmp/x"],
    }
    assert pipeline_steps.step_summary({"Q": "   long   question text   "}, width=20) == "long question text"
    assert pipeline_steps.step_summary({"C": "print('hello world')\nprint('again')"}, width=18) == "print('hello…"
    assert pipeline_steps.step_button_label(1, 7, {"Q": ""}) == "2. Step 8"
    assert pipeline_steps.looks_like_runtime_reference("/tmp/demo") is True
    assert pipeline_steps.looks_like_runtime_reference("demo_project") is True
    assert pipeline_steps.looks_like_runtime_reference("not a runtime") is False
    assert pipeline_steps.pipeline_export_root(env) == (tmp_path / "export")
    assert pipeline_steps.pipeline_export_root(SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=None, envars={})) == (
        tmp_path / "relative-export"
    )


def test_pipeline_steps_module_keys_and_sequence_error_branches(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)

    export_root = tmp_path / "export"
    export_root.mkdir()
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=export_root, envars={})
    module_dir = export_root / "demo_project"
    module_dir.mkdir()

    keys = pipeline_steps.module_keys(module_dir, env=env)
    assert keys[0] == "demo_project"
    assert keys[1] == str(module_dir)

    missing = pipeline_steps.load_sequence_preferences(module_dir, tmp_path / "missing.toml", env=env)
    assert missing == []

    broken_file = tmp_path / "broken.toml"
    broken_file.write_text("[[broken]\n", encoding="utf-8")
    assert pipeline_steps.load_sequence_preferences(module_dir, broken_file, env=env) == []

    same_sequence_file = tmp_path / "same_sequence.toml"
    same_sequence_file.write_text(
        '[__meta__]\n"demo_project__sequence" = [0, 2]\n',
        encoding="utf-8",
    )
    before = same_sequence_file.read_text(encoding="utf-8")
    pipeline_steps.persist_sequence_preferences(module_dir, same_sequence_file, [0, 2], env=env)
    assert same_sequence_file.read_text(encoding="utf-8") == before


def test_pipeline_steps_virtualenv_helpers_and_guidance(tmp_path):
    env_root = tmp_path / "env_a"
    env_root.mkdir()
    (env_root / "pyvenv.cfg").write_text("home=/tmp/python\n", encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    (child / ".venv").mkdir()
    ((child / ".venv") / "pyvenv.cfg").write_text("home=/tmp/python\n", encoding="utf-8")

    roots = list(pipeline_steps._iter_venv_roots(tmp_path))

    assert env_root.resolve() in roots
    assert (child / ".venv").resolve() in roots
    assert pipeline_steps._normalize_venv_root(tmp_path / "missing") is None
    assert "Run INSTALL" in pipeline_steps.snippet_source_guidance(False, "flight_project")
    assert "Snippets are refreshed" in pipeline_steps.snippet_source_guidance(True, "flight_project")


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


def test_pipeline_export_root_and_module_keys_handle_home_fallback(monkeypatch, tmp_path):
    fake_st = SimpleNamespace(session_state={"AGI_EXPORT_DIR": ""})
    monkeypatch.setattr(pipeline_steps, "st", fake_st)
    env = SimpleNamespace(home_abs=tmp_path, AGILAB_EXPORT_ABS=tmp_path, envars={})

    export_root = pipeline_steps.pipeline_export_root(env)
    module_dir = export_root / "network_sim_project"

    assert export_root == (tmp_path / "export")
    assert pipeline_steps.module_keys(module_dir, env=env)[0] == "network_sim_project"


def test_step_helper_labels_and_runtime_reference_flags():
    entry = {"Q": "  Build topology   and   demands  ", "C": "print('fallback')", "R": "runpy"}

    assert pipeline_steps.step_summary(entry, width=18) == "Build topology…"
    assert pipeline_steps.step_button_label(2, 4, entry) == "3. Build topology and demands"
    assert pipeline_steps.step_button_label(0, 2, {}) == "1. Step 3"
    assert pipeline_steps.looks_like_runtime_reference("demo_project") is True
    assert pipeline_steps.looks_like_runtime_reference("just words here") is False
    assert pipeline_steps.is_displayable_step({"Q": "go"}) is True
    assert pipeline_steps.is_displayable_step({"C": "print(1)"}) is True
    assert pipeline_steps.is_displayable_step({"Q": "   ", "C": ""}) is False
    assert pipeline_steps.is_runnable_step({"C": "print(1)"}) is True
    assert pipeline_steps.is_runnable_step({"C": "  "}) is False
    assert pipeline_steps.looks_like_step("4") is True
    assert pipeline_steps.looks_like_step("-1") is False


def test_sequence_preferences_and_guidance_ignore_invalid_metadata(tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text(
        "[__meta__]\n"
        'demo_project__sequence = [2, -1, "bad", 0]\n',
        encoding="utf-8",
    )

    assert pipeline_steps.load_sequence_preferences("demo_project", steps_file) == [2, 0]
    assert "latest ORCHESTRATE run" in pipeline_steps.snippet_source_guidance(True, "demo_project")
    assert "No ORCHESTRATE-generated snippet" in pipeline_steps.snippet_source_guidance(False, "demo_project")


def test_pipeline_steps_misc_helpers_cover_path_conversion_and_locked_source():
    converted = pipeline_steps._convert_paths_to_strings({"items": [Path("/tmp/demo"), {"path": Path("x")}]})
    assert converted == {"items": ["/tmp/demo", {"path": "x"}]}

    assert pipeline_steps.extract_step_app_name('APP = "flight_project"\nprint(1)\n') == "flight_project"
    assert pipeline_steps.extract_step_app_name("print(1)") == ""
    assert pipeline_steps.orchestrate_snippet_source({"Q": "Imported snippet: AGI_run_demo.py"}) == "AGI_run_demo.py"
