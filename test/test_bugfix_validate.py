from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("tools/bugfix_validate.py").resolve()


def _load_module():
    tools_dir = str(MODULE_PATH.parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    spec = importlib.util.spec_from_file_location("bugfix_validate_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _impact_report(module, files: list[str]):
    return module.impact_validate.ImpactReport(
        files=files,
        overall_risk="low",
        risk_zones=[],
        push_gates=[],
        artifact_actions=[],
        required_validations=[],
        guessed_tests=["test/test_demo.py"],
    )


def _selection(module, files: list[str], command=("python", "-c", "pass")):
    return module.ga_regression_selector.SelectionResult(
        files=tuple(files),
        selected_tests=("test/test_demo.py",),
        required_tests=("test/test_demo.py",),
        estimated_seconds=0.25,
        score=120.0,
        budget_seconds=45.0,
        command=command,
        reasons={"test/test_demo.py": ("direct impact match",)},
    )


def _patch_validation(monkeypatch, module, files, report, selection) -> None:
    monkeypatch.setattr(module, "_collect_changed_files", lambda _args: files)
    monkeypatch.setattr(module.impact_validate, "analyze_paths", lambda _paths: report)
    monkeypatch.setattr(
        module,
        "build_selection_for_args",
        lambda _files, _args, impact_report: selection,
    )


def test_main_reuses_single_impact_report_for_selection(capsys, monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files)
    calls = []

    monkeypatch.setattr(module, "_collect_changed_files", lambda _args: files)
    monkeypatch.setattr(module.impact_validate, "analyze_paths", lambda paths: report)
    monkeypatch.setattr(module.impact_validate, "_render_human", lambda _report: "IMPACT")
    monkeypatch.setattr(module.ga_regression_selector, "_render_human", lambda _selection: "GA")

    def _build_selection(input_files, args, *, impact_report):
        calls.append((list(input_files), impact_report))
        return selection

    monkeypatch.setattr(module, "build_selection_for_args", _build_selection)

    assert module.main(["--files", "src/agilab/demo.py"]) == 0

    assert calls == [(files, report)]
    assert capsys.readouterr().out == "IMPACT\n\nGA\n"


def test_json_output_combines_impact_and_selection(capsys, monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files)

    monkeypatch.setattr(module, "_collect_changed_files", lambda _args: files)
    monkeypatch.setattr(module.impact_validate, "analyze_paths", lambda _paths: report)
    monkeypatch.setattr(
        module,
        "build_selection_for_args",
        lambda _files, _args, impact_report: selection,
    )

    assert module.main(["--files", "src/agilab/demo.py", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["impact"]["guessed_tests"] == ["test/test_demo.py"]
    assert payload["selection"]["selected_tests"] == ["test/test_demo.py"]


def test_run_returns_selected_command_status(monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))
    subprocess_calls = []

    class Completed:
        returncode = 7

    monkeypatch.setattr(module, "_collect_changed_files", lambda _args: files)
    monkeypatch.setattr(module.impact_validate, "analyze_paths", lambda _paths: report)
    monkeypatch.setattr(
        module,
        "build_selection_for_args",
        lambda _files, _args, impact_report: selection,
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, *, cwd, check: subprocess_calls.append((command, cwd, check))
        or Completed(),
    )

    assert module.main(["--files", "src/agilab/demo.py", "--run"]) == 7
    assert subprocess_calls == [(selection.command, module.REPO_ROOT, False)]


def test_run_records_successful_result_cache(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))
    cache_path = tmp_path / "bugfix-cache.json"
    subprocess_calls = []

    class Completed:
        returncode = 0

    _patch_validation(monkeypatch, module, files, report, selection)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, *, cwd, check: subprocess_calls.append((command, cwd, check))
        or Completed(),
    )

    assert (
        module.main(
            [
                "--files",
                "src/agilab/demo.py",
                "--run",
                "--result-cache-path",
                str(cache_path),
            ]
        )
        == 0
    )

    key = module._result_cache_key(files, selection)
    cache = module._load_result_cache(cache_path)
    assert cache["entries"][key]["status"] == "passed"
    assert subprocess_calls == [(selection.command, module.REPO_ROOT, False)]


def test_run_uses_cached_success_without_subprocess(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))
    cache_path = tmp_path / "bugfix-cache.json"
    key = module._result_cache_key(files, selection)
    module._write_result_cache(
        cache_path,
        {
            "schema": module.RESULT_CACHE_SCHEMA,
            "entries": {key: {"status": "passed"}},
        },
    )

    _patch_validation(monkeypatch, module, files, report, selection)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cached pass should skip pytest subprocess")
        ),
    )

    assert (
        module.main(
            [
                "--files",
                "src/agilab/demo.py",
                "--run",
                "--result-cache-path",
                str(cache_path),
            ]
        )
        == 0
    )

    assert "cached pass for selected pytest subset" in capsys.readouterr().err


def test_run_does_not_cache_failed_result(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))
    cache_path = tmp_path / "bugfix-cache.json"

    class Completed:
        returncode = 7

    _patch_validation(monkeypatch, module, files, report, selection)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(),
    )

    assert (
        module.main(
            [
                "--files",
                "src/agilab/demo.py",
                "--run",
                "--result-cache-path",
                str(cache_path),
            ]
        )
        == 7
    )

    assert module._load_result_cache(cache_path)["entries"] == {}


def test_no_result_cache_bypasses_cached_success(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))
    cache_path = tmp_path / "bugfix-cache.json"
    key = module._result_cache_key(files, selection)
    module._write_result_cache(
        cache_path,
        {
            "schema": module.RESULT_CACHE_SCHEMA,
            "entries": {key: {"status": "passed"}},
        },
    )
    subprocess_calls = []

    class Completed:
        returncode = 0

    _patch_validation(monkeypatch, module, files, report, selection)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, *, cwd, check: subprocess_calls.append((command, cwd, check))
        or Completed(),
    )

    assert (
        module.main(
            [
                "--files",
                "src/agilab/demo.py",
                "--run",
                "--result-cache-path",
                str(cache_path),
                "--no-result-cache",
            ]
        )
        == 0
    )

    assert subprocess_calls == [(selection.command, module.REPO_ROOT, False)]


def test_result_cache_eviction_uses_stored_timestamp(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    selection = _selection(module, files)
    cache_path = tmp_path / "bugfix-cache.json"
    module._write_result_cache(
        cache_path,
        {
            "schema": module.RESULT_CACHE_SCHEMA,
            "entries": {
                "newer": {"status": "passed", "stored_at": 20.0},
                "older": {"status": "passed", "stored_at": 10.0},
            },
        },
    )
    monkeypatch.setattr(module, "RESULT_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(module.time, "time", lambda: 30.0)

    module._record_cached_success(cache_path, "fresh", files, selection)

    entries = module._load_result_cache(cache_path)["entries"]
    assert sorted(entries) == ["fresh", "newer"]


def test_build_selection_for_args_passes_impact_report(monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    captured = {}
    args = SimpleNamespace(
        timings=[],
        budget_seconds=5.0,
        population=12,
        generations=4,
        seed=9,
        max_candidates=20,
        cache_path="/tmp/bugfix-cache.json",
        no_cache=True,
    )

    monkeypatch.setattr(module.ga_regression_selector, "load_timings", lambda _paths: {})

    def _build_selection(input_files, **kwargs):
        captured.update({"files": tuple(input_files), **kwargs})
        return _selection(module, files)

    monkeypatch.setattr(module.ga_regression_selector, "build_selection", _build_selection)

    module.build_selection_for_args(files, args, impact_report=report)

    assert captured["files"] == tuple(files)
    assert captured["impact_report"] is report
    assert captured["budget_seconds"] == 5.0
    assert captured["use_cache"] is False
