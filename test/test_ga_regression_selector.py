from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("tools/ga_regression_selector.py").resolve()


def _load_module():
    tools_dir = str(MODULE_PATH.parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    spec = importlib.util.spec_from_file_location("ga_regression_selector_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_selection_prioritizes_direct_impact_tests() -> None:
    module = _load_module()

    result = module.build_selection(
        ["src/agilab/orchestrate_page_support.py"],
        timings={
            "test/test_orchestrate_page_support.py": 0.25,
            "test/test_orchestrate_execute.py": 25.0,
        },
        budget_seconds=5,
        population=16,
        generations=10,
        seed=7,
    )

    assert "test/test_orchestrate_page_support.py" in result.selected_tests
    assert "test/test_orchestrate_page_support.py" in result.required_tests
    assert result.command[:8] == (
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "pytest",
        "-q",
        "-o",
        "addopts=",
    )


def test_selection_is_deterministic_for_same_seed() -> None:
    module = _load_module()
    kwargs = {
        "timings": {
            "test/test_pipeline_ai.py": 3.0,
            "test/test_pipeline_openai.py": 0.8,
            "test/test_pipeline_runtime.py": 2.0,
        },
        "budget_seconds": 8,
        "population": 18,
        "generations": 12,
        "seed": 2026,
    }

    first = module.build_selection(["src/agilab/pipeline_ai.py"], **kwargs)
    second = module.build_selection(["src/agilab/pipeline_ai.py"], **kwargs)

    assert first.selected_tests == second.selected_tests
    assert first.estimated_seconds == second.estimated_seconds


def test_selection_prunes_optional_tests_to_budget() -> None:
    module = _load_module()

    result = module.build_selection(
        ["src/agilab/pipeline_mistral.py"],
        timings={
            "test/test_pipeline_mistral.py": 0.5,
            "test/test_pipeline_ai.py": 3.0,
            "test/test_pipeline_editor.py": 3.0,
            "test/test_pipeline_runtime.py": 3.0,
        },
        budget_seconds=4,
        population=16,
        generations=8,
        seed=11,
    )

    assert "test/test_pipeline_mistral.py" in result.selected_tests
    assert result.estimated_seconds <= 4


def test_load_timings_accepts_json_and_junit(tmp_path: Path) -> None:
    module = _load_module()
    json_path = tmp_path / "timings.json"
    junit_path = tmp_path / "junit.xml"
    json_path.write_text(json.dumps({"test/test_pipeline_ai.py": 1.5}), encoding="utf-8")
    junit_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
    <testcase classname="test.test_pipeline_ai" name="test_a" time="0.25" />
    <testcase classname="test.test_pipeline_ai" name="test_b" time="0.50" />
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    timings = module.load_timings([str(json_path), str(junit_path)])

    assert timings["test/test_pipeline_ai.py"] == 2.25


def test_main_json_output_for_explicit_files(capsys) -> None:
    module = _load_module()

    exit_code = module.main(
        [
            "--files",
            "src/agilab/pipeline_mistral.py",
            "--budget-seconds",
            "5",
            "--population",
            "12",
            "--generations",
            "4",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["files"] == ["src/agilab/pipeline_mistral.py"]
    assert "test/test_pipeline_mistral.py" in payload["selected_tests"]
    assert payload["command"][:5] == [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "pytest",
    ]


def test_empty_selection_has_no_broad_pytest_command(capsys, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_discover_test_files", lambda: [])

    exit_code = module.main(["--files", "README.md", "--print-command"])

    assert exit_code == 0
    assert capsys.readouterr().out == "\n"
    result = module.build_selection(["README.md"])
    assert result.selected_tests == ()
    assert result.command == ()


def test_collect_changed_files_uses_staged_diff(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_git_lines", lambda _args: ["src/agilab/pipeline_ai.py"])

    files = module.collect_changed_files(SimpleNamespace(files=None, staged=True, base="origin/main"))

    assert files == ["src/agilab/pipeline_ai.py"]
