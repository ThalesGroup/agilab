from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_lab = _load_module("agilab.pipeline_lab", "src/agilab/pipeline_lab.py")


def test_get_existing_snippets_deduplicates_and_disambiguates_labels(monkeypatch, tmp_path):
    steps_file = tmp_path / "lab_steps.toml"
    steps_file.write_text("", encoding="utf-8")

    snippet_dir = tmp_path / "snippets"
    snippet_dir.mkdir()
    explicit_snippet = snippet_dir / "AGI_run.py"
    explicit_snippet.write_text("print('explicit')\n", encoding="utf-8")

    safe_template = tmp_path / "templates" / "AGI_run.py"
    safe_template.parent.mkdir(parents=True)
    safe_template.write_text("print('safe')\n", encoding="utf-8")

    runenv_dir = tmp_path / "runenv"
    runenv_dir.mkdir()
    runenv_snippet = runenv_dir / "AGI_run_flight.py"
    runenv_snippet.write_text("print('runenv')\n", encoding="utf-8")

    app_settings = tmp_path / "app_settings.toml"
    app_settings.write_text("x=1\n", encoding="utf-8")
    os.utime(runenv_snippet, None)

    fake_st = SimpleNamespace(session_state={"snippet_file": str(explicit_snippet)})
    monkeypatch.setattr(pipeline_lab, "st", fake_st)

    env = SimpleNamespace(
        runenv=runenv_dir,
        app_settings_file=app_settings,
        app="flight",
    )
    deps = SimpleNamespace(
        ensure_safe_service_template=lambda *_args, **_kwargs: safe_template,
        safe_service_template_filename="unused.py",
        safe_service_template_marker="marker",
    )

    option_map = pipeline_lab.get_existing_snippets(env, steps_file, deps)

    labels = list(option_map.keys())
    assert "AGI_run.py" in labels
    assert "AGI_run.py (templates)" in labels
    assert "AGI_run_flight.py" in labels
    assert len(option_map) == 3
