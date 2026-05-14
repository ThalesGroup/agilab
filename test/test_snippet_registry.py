from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
SRC_PACKAGE = SRC_ROOT / "agilab"
sys.path.insert(0, str(SRC_ROOT))

import agilab as _agilab_package

if str(SRC_PACKAGE) not in _agilab_package.__path__:
    _agilab_package.__path__.insert(0, str(SRC_PACKAGE))

from agi_env.snippet_contract import snippet_contract_block
from agilab.snippet_registry import (
    SNIPPET_REGISTRY_SCHEMA,
    SnippetCandidateRegistry,
    SnippetCandidateSpec,
    discover_pipeline_snippets,
)


def test_discover_pipeline_snippets_returns_typed_deterministic_registry(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    lab_dir.mkdir()
    stages_file = lab_dir / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    lab_snippet = lab_dir / "AGI_run.py"
    lab_snippet.write_text("print('lab')\n", encoding="utf-8")

    explicit = tmp_path / "snippets" / "AGI_run.py"
    explicit.parent.mkdir()
    explicit.write_text("print('explicit')\n", encoding="utf-8")

    safe_template = tmp_path / "templates" / "AGI_run.py"
    safe_template.parent.mkdir()
    safe_template.write_text("print('safe')\n", encoding="utf-8")

    runenv = tmp_path / "runenv"
    runenv.mkdir()
    runenv_snippet = runenv / "AGI_run_flight_telemetry.py"
    runenv_snippet.write_text("print('runenv')\n", encoding="utf-8")

    app_settings = tmp_path / "app_settings.toml"
    app_settings.write_text("x=1\n", encoding="utf-8")
    settings_time = datetime(2026, 4, 1, 11, 0, 0).timestamp()
    runenv_time = datetime(2026, 4, 1, 12, 0, 0).timestamp()
    os.utime(app_settings, (settings_time, settings_time))
    os.utime(runenv_snippet, (runenv_time, runenv_time))

    registry = discover_pipeline_snippets(
        stages_file=stages_file,
        app_name="flight",
        explicit_snippet=explicit,
        safe_service_template=safe_template,
        runenv_root=runenv,
        app_settings_file=app_settings,
    )

    assert isinstance(registry, SnippetCandidateRegistry)
    assert tuple(candidate.source for candidate in registry) == (
        "lab_run",
        "session_state",
        "safe_service_template",
        "runenv",
    )
    assert registry.as_option_map() == {
        "AGI_run.py": lab_snippet.resolve(),
        "AGI_run.py (snippets)": explicit.resolve(),
        "AGI_run.py (templates)": safe_template.resolve(),
        "AGI_run_flight_telemetry.py": runenv_snippet.resolve(),
    }
    assert registry.as_rows()[0]["schema"] == SNIPPET_REGISTRY_SCHEMA


def test_discover_pipeline_snippets_filters_stale_and_wrong_app_runenv_snippets(tmp_path: Path) -> None:
    stages_file = tmp_path / "lab_stages.toml"
    stages_file.write_text("", encoding="utf-8")
    runenv = tmp_path / "runenv"
    runenv.mkdir()

    stale_snippet = runenv / "AGI_install_flight_telemetry.py"
    stale_snippet.write_text(
        "from agi_cluster.agi_distributor import AGI\n"
        "async def main():\n"
        "    await AGI.install(None)\n",
        encoding="utf-8",
    )
    current_snippet = runenv / "AGI_run_flight_telemetry.py"
    current_snippet.write_text(
        "from agi_cluster.agi_distributor import AGI\n"
        "from agi_env import AgiEnv\n"
        f"{snippet_contract_block(app='flight')}\n"
        "async def main():\n"
        "    await AGI.run(AgiEnv(apps_path='/tmp/apps', app='flight'))\n",
        encoding="utf-8",
    )
    wrong_app = runenv / "AGI_run_other.py"
    wrong_app.write_text("print('other')\n", encoding="utf-8")

    app_settings = tmp_path / "app_settings.toml"
    app_settings.write_text("x=1\n", encoding="utf-8")
    settings_time = datetime(2026, 4, 1, 11, 0, 0).timestamp()
    runenv_time = datetime(2026, 4, 1, 12, 0, 0).timestamp()
    os.utime(app_settings, (settings_time, settings_time))
    os.utime(stale_snippet, (runenv_time, runenv_time))
    os.utime(current_snippet, (runenv_time, runenv_time))
    os.utime(wrong_app, (runenv_time, runenv_time))

    registry = discover_pipeline_snippets(
        stages_file=stages_file,
        app_name="flight",
        runenv_root=runenv,
        app_settings_file=app_settings,
    )

    assert registry.as_option_map() == {"AGI_run_flight_telemetry.py": current_snippet.resolve()}
    assert registry.stale_snippets == (stale_snippet.resolve(),)


def test_snippet_candidate_registry_disambiguates_duplicate_labels(tmp_path: Path) -> None:
    left = tmp_path / "left" / "common" / "AGI_run.py"
    right = tmp_path / "right" / "common" / "AGI_run.py"
    root = tmp_path / "AGI_run.py"
    for path in (left, right, root):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("print('ok')\n", encoding="utf-8")

    registry = SnippetCandidateRegistry(
        [
            SnippetCandidateSpec(left, source="explicit"),
            SnippetCandidateSpec(right, source="safe_template"),
            SnippetCandidateSpec(root, source="lab_run"),
        ]
    )

    assert list(registry.as_option_map()) == [
        "AGI_run.py",
        "AGI_run.py (common)",
        "AGI_run.py (common #2)",
    ]
