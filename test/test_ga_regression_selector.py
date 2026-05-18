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


def test_orchestrate_gui_change_stays_in_gui_regression_slice() -> None:
    module = _load_module()

    result = module.build_selection(
        [
            "src/agilab/orchestrate_page_state.py",
            "src/agilab/lib/agi-gui/src/agi_gui/orchestrate_execute.py",
        ],
        timings={
            "test/test_orchestrate_execute.py": 0.4,
            "test/test_orchestrate_page_state.py": 0.2,
            "test/test_orchestrate_page_helpers.py": 3.5,
        },
        budget_seconds=45,
        population=16,
        generations=8,
        seed=13,
    )

    assert "test/test_orchestrate_execute.py" in result.required_tests
    assert "test/test_orchestrate_page_state.py" in result.required_tests
    assert all(not path.startswith("src/agilab/core/") for path in result.selected_tests)
    assert all("global_pipeline" not in path for path in result.selected_tests)
    assert len(result.selected_tests) <= 10


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


def test_build_selection_reuses_precomputed_impact_report(monkeypatch) -> None:
    module = _load_module()
    report = module.impact_validate.ImpactReport(
        files=["src/agilab/pipeline_mistral.py"],
        overall_risk="low",
        risk_zones=[],
        push_gates=[],
        artifact_actions=[],
        required_validations=[],
        guessed_tests=["test/test_pipeline_mistral.py"],
    )

    monkeypatch.setattr(
        module.impact_validate,
        "analyze_paths",
        lambda _paths: (_ for _ in ()).throw(
            AssertionError("impact report should be reused")
        ),
    )

    result = module.build_selection(
        ["src/agilab/pipeline_mistral.py"],
        timings={"test/test_pipeline_mistral.py": 0.5},
        budget_seconds=4,
        population=16,
        generations=8,
        seed=11,
        impact_report=report,
    )

    assert "test/test_pipeline_mistral.py" in result.selected_tests


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


def test_load_timings_ignores_unreadable_files(tmp_path: Path, capsys) -> None:
    module = _load_module()
    json_path = tmp_path / "timings.json"
    bad_junit_path = tmp_path / "bad-junit.xml"
    json_path.write_text(json.dumps({"test/test_pipeline_ai.py": 1.5}), encoding="utf-8")
    bad_junit_path.write_text("<testsuites></testsuites><junk>", encoding="utf-8")

    timings = module.load_timings([str(json_path), str(bad_junit_path)])

    assert timings == {"test/test_pipeline_ai.py": 1.5}
    assert "ignoring unreadable timings" in capsys.readouterr().err


def test_discover_test_files_uses_git_and_caches_result(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    cache_path = tmp_path / "selector-cache.json"
    calls: list[list[str]] = []

    def _fake_git_lines(args):
        calls.append(list(args))
        return [
            "test/test_alpha.py",
            "test/helper.py",
            "src/agilab/core/test/test_core.py",
            "src/agilab/core/test/fixture.py",
            "docs/test_docs.py",
        ]

    monkeypatch.setattr(module, "_git_lines", _fake_git_lines)

    files = module._discover_test_files(cache_path=cache_path)

    assert files == ["src/agilab/core/test/test_core.py", "test/test_alpha.py"]
    assert calls == [
        [
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *module.DEFAULT_TEST_ROOTS,
        ]
    ]
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["test_files"]["roots"] == list(module.DEFAULT_TEST_ROOTS)
    assert cache["test_files"]["files"] == files


def test_discover_test_files_uses_cached_list_when_git_fails(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    cache_path = tmp_path / "selector-cache.json"
    files = ["test/test_cached.py"]
    cache_path.write_text(
        json.dumps(
            {
                "schema": module.TEST_INDEX_CACHE_SCHEMA,
                "entries": {},
                "test_files": {
                    "roots": list(module.DEFAULT_TEST_ROOTS),
                    "files": files,
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "_git_lines",
        lambda _args: (_ for _ in ()).throw(RuntimeError("git unavailable")),
    )
    monkeypatch.setattr(
        module,
        "_discover_test_files_with_rglob",
        lambda _roots: (_ for _ in ()).throw(
            AssertionError("cached discovery should avoid rglob fallback")
        ),
    )

    assert module._discover_test_files(cache_path=cache_path) == files


def test_discover_test_files_falls_back_to_rglob_without_git_or_cache(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test_alpha.py").write_text("def test_alpha():\n    pass\n")
    (tmp_path / "test" / "helper.py").write_text("HELPER = True\n")
    (tmp_path / "src" / "agilab" / "core" / "test").mkdir(parents=True)
    (tmp_path / "src" / "agilab" / "core" / "test" / "test_core.py").write_text(
        "def test_core():\n    pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "_git_lines",
        lambda _args: (_ for _ in ()).throw(RuntimeError("git unavailable")),
    )

    files = module._discover_test_files(cache_path=tmp_path / "missing-cache.json")

    assert files == ["test/test_alpha.py", "src/agilab/core/test/test_core.py"]


def test_cached_default_estimates_reuses_unchanged_file_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    test_file = tmp_path / "test" / "test_cached.py"
    test_file.parent.mkdir()
    test_file.write_text(
        "def test_one():\n    assert True\n"
        "async def test_two():\n    assert True\n",
        encoding="utf-8",
    )
    cache_path = tmp_path / "selector-cache.json"

    first = module._cached_default_estimates(
        ["test/test_cached.py"], cache_path=cache_path
    )

    def _unexpected_estimate(_path: str) -> float:
        raise AssertionError("unchanged cached test file should not be reread")

    monkeypatch.setattr(module, "_default_estimate", _unexpected_estimate)
    second = module._cached_default_estimates(
        ["test/test_cached.py"], cache_path=cache_path
    )

    assert second == first


def test_cached_default_estimates_invalidates_changed_file(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    test_file = tmp_path / "test" / "test_cached.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_one():\n    assert True\n", encoding="utf-8")
    cache_path = tmp_path / "selector-cache.json"

    module._cached_default_estimates(["test/test_cached.py"], cache_path=cache_path)
    test_file.write_text(
        "def test_one():\n    assert True\n"
        "def test_two():\n    assert True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_default_estimate", lambda _path: 9.5)

    estimates = module._cached_default_estimates(
        ["test/test_cached.py"], cache_path=cache_path
    )

    assert estimates == {"test/test_cached.py": 9.5}


def test_main_json_output_for_explicit_files(capsys, tmp_path: Path) -> None:
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
            "--cache-path",
            str(tmp_path / "selector-cache.json"),
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
    monkeypatch.setattr(module, "_discover_test_files", lambda **_kwargs: [])

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
