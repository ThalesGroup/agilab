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


def test_print_command_outputs_selected_pytest_command(capsys, monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))

    _patch_validation(monkeypatch, module, files, report, selection)

    assert module.main(["--files", "src/agilab/demo.py", "--print-command"]) == 0
    assert capsys.readouterr().out == "pytest test/test_demo.py\n"


def test_collect_changed_files_delegates_to_ga_selector(monkeypatch) -> None:
    module = _load_module()
    captured = {}

    def _fake_collect(selector_args):
        captured.update(vars(selector_args))
        return ["src/agilab/demo.py"]

    monkeypatch.setattr(
        module.ga_regression_selector,
        "collect_changed_files",
        _fake_collect,
    )
    args = SimpleNamespace(files=["demo.py"], staged=False, base="HEAD~1")

    assert module._collect_changed_files(args) == ["src/agilab/demo.py"]
    assert captured == {"files": ["demo.py"], "staged": False, "base": "HEAD~1"}


def test_result_cache_helpers_reject_invalid_shapes(tmp_path: Path) -> None:
    module = _load_module()
    cache_path = tmp_path / "bugfix-cache.json"

    cache_path.write_text("[]", encoding="utf-8")
    assert module._load_result_cache(cache_path) == {
        "schema": module.RESULT_CACHE_SCHEMA,
        "entries": {},
    }

    cache_path.write_text(
        json.dumps({"schema": "old", "entries": []}),
        encoding="utf-8",
    )
    assert module._load_result_cache(cache_path) == {
        "schema": module.RESULT_CACHE_SCHEMA,
        "entries": {},
    }

    module._write_result_cache(
        cache_path,
        {"schema": module.RESULT_CACHE_SCHEMA, "entries": []},
    )
    assert module._has_cached_success(cache_path, "anything") is False
    assert module._cached_frontdoor_success(cache_path, "anything") is None


def test_result_cache_lookup_helpers_reject_non_dict_entries(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_load_result_cache",
        lambda _path: {"schema": module.RESULT_CACHE_SCHEMA, "entries": []},
    )

    assert module._has_cached_success(Path("cache.json"), "anything") is False
    assert module._cached_frontdoor_success(Path("cache.json"), "anything") is None


def test_repo_file_hash_and_git_head_edge_cases(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    directory = tmp_path / "src"
    directory.mkdir()
    external = tmp_path.parent / "external.txt"
    external.write_text("external\n", encoding="utf-8")
    updates: list[bytes] = []

    class _Hasher:
        @staticmethod
        def update(data: bytes) -> None:
            updates.append(data)

    label, resolved = module._repo_file(str(external))
    assert label == external.as_posix()
    assert resolved == external

    module._hash_file(_Hasher(), "src")
    assert b"not-file\n" in updates

    original_open = Path.open

    def _blocked_open(self, *args, **kwargs):
        if self.name == "blocked.py":
            raise OSError("denied")
        return original_open(self, *args, **kwargs)

    (tmp_path / "blocked.py").write_text("blocked\n", encoding="utf-8")
    monkeypatch.setattr(Path, "open", _blocked_open)
    module._hash_file(_Hasher(), "blocked.py")
    assert any(chunk.startswith(b"unreadable:OSError") for chunk in updates)

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    assert module._git_head() == "unknown"
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="\n"),
    )
    assert module._git_head() == "unknown"


def test_frontdoor_cache_helpers_cover_timing_and_enablement(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    timing_root = tmp_path / "test-results"
    timing_root.mkdir()
    (timing_root / "junit-b.xml").write_text("<testsuites />", encoding="utf-8")
    (timing_root / "junit-a.xml").write_text("<testsuites />", encoding="utf-8")
    args = module._build_parser().parse_args(["--files", "demo.py", "--run"])

    assert module._timing_inputs(args) == [
        "test-results/junit-a.xml",
        "test-results/junit-b.xml",
    ]
    assert module._frontdoor_cache_enabled(args) is True
    assert (
        module._frontdoor_cache_enabled(
            module._build_parser().parse_args(["--files", "demo.py", "--run", "--json"])
        )
        is False
    )
    explicit = module._build_parser().parse_args(
        ["--files", "demo.py", "--run", "--timings", "custom.json"]
    )
    assert module._timing_inputs(explicit) == ["custom.json"]


def test_run_returns_selected_command_status(monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))
    subprocess_calls = []

    class Completed:
        returncode = 7

    monkeypatch.setattr(module, "_git_head", lambda: "test-head")
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

    monkeypatch.setattr(module, "_git_head", lambda: "test-head")
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

    monkeypatch.setattr(module, "_git_head", lambda: "test-head")
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
    args = module._build_parser().parse_args(
        [
            "--files",
            "src/agilab/demo.py",
            "--run",
            "--result-cache-path",
            str(cache_path),
        ]
    )
    frontdoor_key = module._frontdoor_cache_key(files, args)
    assert module._cached_frontdoor_success(cache_path, frontdoor_key) is not None


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


def test_run_records_frontdoor_cache_after_success(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))
    cache_path = tmp_path / "bugfix-cache.json"

    class Completed:
        returncode = 0

    monkeypatch.setattr(module, "_git_head", lambda: "test-head")
    _patch_validation(monkeypatch, module, files, report, selection)
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: Completed())

    argv = [
        "--files",
        "src/agilab/demo.py",
        "--run",
        "--result-cache-path",
        str(cache_path),
    ]
    assert module.main(argv) == 0

    args = module._build_parser().parse_args(argv)
    key = module._frontdoor_cache_key(files, args)
    entry = module._cached_frontdoor_success(cache_path, key)
    assert entry is not None
    assert entry["selected_tests"] == ["test/test_demo.py"]
    assert "GA regression selection" in entry["stdout"]


def test_frontdoor_cache_skips_impact_selection_and_pytest(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))
    cache_path = tmp_path / "bugfix-cache.json"
    argv = [
        "--files",
        "src/agilab/demo.py",
        "--run",
        "--result-cache-path",
        str(cache_path),
    ]
    args = module._build_parser().parse_args(argv)
    monkeypatch.setattr(module, "_git_head", lambda: "test-head")
    key = module._frontdoor_cache_key(files, args)
    module._record_frontdoor_success(
        cache_path,
        key,
        files,
        selection,
        "cached human output",
    )
    monkeypatch.setattr(module, "_collect_changed_files", lambda _args: files)
    monkeypatch.setattr(
        module.impact_validate,
        "analyze_paths",
        lambda _paths: (_ for _ in ()).throw(
            AssertionError("front-door hit should skip impact analysis")
        ),
    )
    monkeypatch.setattr(
        module,
        "build_selection_for_args",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("front-door hit should skip GA selection")
        ),
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("front-door hit should skip pytest subprocess")
        ),
    )

    assert module.main(argv) == 0

    captured = capsys.readouterr()
    assert captured.out == "cached human output\n"
    assert "front-door cached pass" in captured.err


def test_run_records_frontdoor_cache_for_empty_selection(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    files = ["README.md"]
    report = _impact_report(module, files)
    selection = module.ga_regression_selector.SelectionResult(
        files=tuple(files),
        selected_tests=(),
        required_tests=(),
        estimated_seconds=0.0,
        score=0.0,
        budget_seconds=45.0,
        command=(),
        reasons={},
    )
    cache_path = tmp_path / "bugfix-cache.json"

    monkeypatch.setattr(module, "_git_head", lambda: "test-head")
    _patch_validation(monkeypatch, module, files, report, selection)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("empty selection should not invoke pytest")
        ),
    )

    argv = [
        "--files",
        "README.md",
        "--run",
        "--result-cache-path",
        str(cache_path),
    ]
    assert module.main(argv) == 0

    args = module._build_parser().parse_args(argv)
    entry = module._cached_frontdoor_success(
        cache_path,
        module._frontdoor_cache_key(files, args),
    )
    assert entry is not None
    assert entry["selected_tests"] == []


def test_main_reports_changed_file_collection_errors(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_collect_changed_files",
        lambda _args: (_ for _ in ()).throw(RuntimeError("git failed")),
    )

    try:
        module.main([])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser exit for changed-file collection error")


def test_frontdoor_cache_key_changes_when_changed_file_changes(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "_git_head", lambda: "test-head")
    changed = tmp_path / "src" / "agilab" / "demo.py"
    changed.parent.mkdir(parents=True)
    changed.write_text("VALUE = 1\n", encoding="utf-8")
    args = module._build_parser().parse_args(
        ["--files", "src/agilab/demo.py", "--run"]
    )

    first = module._frontdoor_cache_key(["src/agilab/demo.py"], args)
    changed.write_text("VALUE = 2\n", encoding="utf-8")
    second = module._frontdoor_cache_key(["src/agilab/demo.py"], args)

    assert first != second


def test_no_result_cache_bypasses_frontdoor_cache(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    report = _impact_report(module, files)
    selection = _selection(module, files, command=("pytest", "test/test_demo.py"))
    cache_path = tmp_path / "bugfix-cache.json"
    argv = [
        "--files",
        "src/agilab/demo.py",
        "--run",
        "--result-cache-path",
        str(cache_path),
    ]
    monkeypatch.setattr(module, "_git_head", lambda: "test-head")
    args = module._build_parser().parse_args(argv)
    key = module._frontdoor_cache_key(files, args)
    module._record_frontdoor_success(cache_path, key, files, selection, "cached")
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

    assert module.main([*argv, "--no-result-cache"]) == 0

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


def test_record_cache_helpers_repair_non_dict_entries(monkeypatch) -> None:
    module = _load_module()
    files = ["src/agilab/demo.py"]
    selection = _selection(module, files)
    writes = []
    monkeypatch.setattr(
        module,
        "_load_result_cache",
        lambda _path: {"schema": module.RESULT_CACHE_SCHEMA, "entries": []},
    )
    monkeypatch.setattr(
        module,
        "_write_result_cache",
        lambda _path, state: writes.append(state),
    )
    monkeypatch.setattr(module.time, "time", lambda: 12.0)

    module._record_cached_success(Path("cache.json"), "selected", files, selection)
    module._record_frontdoor_success(Path("cache.json"), "frontdoor", files, selection, "ok")

    assert writes[0]["entries"]["selected"]["status"] == "passed"
    assert writes[1]["entries"]["frontdoor"]["kind"] == "frontdoor"


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

    context = module.ga_regression_selector.ValidationContext(
        files=tuple(files),
        impact_report=report,
        timings={},
        test_files=("test/test_demo.py",),
        default_estimates={"test/test_demo.py": 1.0},
    )
    captured_context = {}

    def _build_validation_context(input_files, **kwargs):
        captured_context.update({"files": tuple(input_files), **kwargs})
        return context

    monkeypatch.setattr(
        module.ga_regression_selector,
        "build_validation_context",
        _build_validation_context,
    )

    def _build_selection(input_files, **kwargs):
        captured.update({"files": tuple(input_files), **kwargs})
        return _selection(module, files)

    monkeypatch.setattr(module.ga_regression_selector, "build_selection", _build_selection)

    module.build_selection_for_args(files, args, impact_report=report)

    assert captured_context["files"] == tuple(files)
    assert captured_context["impact_report"] is report
    assert captured_context["use_cache"] is False
    assert captured["files"] == tuple(files)
    assert captured["context"] is context
    assert captured["impact_report"] is report
    assert captured["budget_seconds"] == 5.0
    assert captured["use_cache"] is False
