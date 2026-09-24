from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
MODULE_PATH = TOOLS_ROOT / "testing" / "root_test_runner.py"


def _load_module():
    sys.path.insert(0, str(TOOLS_ROOT))
    try:
        spec = importlib.util.spec_from_file_location(
            "agilab_root_test_runner_tests", MODULE_PATH
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(TOOLS_ROOT))


def test_root_test_plan_covers_every_root_file_in_stable_groups() -> None:
    module = _load_module()

    groups = module.build_root_test_groups()
    discovered = {
        path.resolve().relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "test").glob("test_*.py")
    }
    planned = {path for group in groups for path in group.test_files}
    by_name = {group.name: group for group in groups}
    general_groups = [
        group for group in groups if group.name.startswith("general:")
    ]

    assert discovered <= planned
    assert len(general_groups) > 100
    assert all(len(group.test_files) == 1 for group in general_groups)
    assert [group.name for group in groups[-7:]] == [
        "support",
        "pipeline",
        "robots",
        "pages-flow",
        "pages-rest",
        "views",
        "reports",
    ]
    assert "test/test_view_training_analysis.py" in by_name["views"].test_files
    assert not any(
        "test/test_view_training_analysis.py" in group.test_files
        for group in general_groups
    )
    assert by_name["general:test_execution_playground_forms"].test_files == (
        "test/test_execution_playground_forms.py",
    )
    assert by_name["pages-flow"].pytest_args[-2:] == (
        "-k",
        "execute_page or experiment_page or pipeline_page_project_selectbox",
    )


def test_root_test_runner_continues_after_failure_and_aggregates_exit(
    capsys,
    monkeypatch,
) -> None:
    module = _load_module()
    groups = (
        module.RootTestGroup("first", ("test/test_first.py",), ("test/test_first.py",)),
        module.RootTestGroup("second", ("test/test_second.py",), ("test/test_second.py",)),
    )
    calls: list[tuple[tuple[str, ...], Path, bool, dict[str, str]]] = []
    returncodes = iter((3, 0))

    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/unsafe/shared-venv")
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("VIRTUAL_ENV", "/unsafe/active-venv")
    monkeypatch.setenv("AGILAB_TEST_SENTINEL", "preserved")

    def runner(command, *, cwd, check, env):
        calls.append((tuple(command), cwd, check, env))
        return SimpleNamespace(returncode=next(returncodes))

    assert module.run_root_test_groups(groups, runner=runner) == 3
    assert len(calls) == 2
    assert all(
        call[0][:3]
        == (sys.executable, "-m", "tools.testing.pytest_entrypoint")
        for call in calls
    )
    assert all(call[1:3] == (REPO_ROOT, False) for call in calls)
    for _, _, _, env in calls:
        assert "UV_PROJECT_ENVIRONMENT" not in env
        assert "UV_RUN_RECURSION_DEPTH" not in env
        assert "VIRTUAL_ENV" not in env
        assert env["AGILAB_TEST_SENTINEL"] == "preserved"
    captured = capsys.readouterr().err
    assert "[root-test] first: failed exit=3" in captured
    assert "[root-test] second: passed" in captured


def test_root_test_runner_list_mode_is_side_effect_free(capsys) -> None:
    module = _load_module()

    assert module.main(["--list"]) == 0

    output = capsys.readouterr().out
    assert "general:test_agenticweb_manifest\t1" in output
    assert "views\t" in output


def test_root_test_runner_keeps_spawned_tests_importable_in_agilab_checkout(
    tmp_path: Path,
) -> None:
    module = _load_module()
    checkout = tmp_path / "agilab"
    test_dir = checkout / "test"
    test_dir.mkdir(parents=True)
    (checkout / "__init__.py").write_text("", encoding="utf-8")
    (test_dir / "__init__.py").write_text("", encoding="utf-8")
    (test_dir / "test_spawn_case.py").write_text(
        """from multiprocessing import get_context


def _worker(results):
    results.put("ok")


def test_spawn_worker_can_reimport_test_module():
    context = get_context("spawn")
    results = context.Queue()
    process = context.Process(target=_worker, args=(results,))
    process.start()
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join()
    assert process.exitcode == 0
    assert results.get(timeout=2) == "ok"
""",
        encoding="utf-8",
    )
    group = module.RootTestGroup(
        "spawn-case",
        ("test/test_spawn_case.py",),
        ("test/test_spawn_case.py",),
    )
    env = module._pytest_environment()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(REPO_ROOT)
        if not pythonpath
        else f"{REPO_ROOT}{os.pathsep}{pythonpath}"
    )

    completed = subprocess.run(
        module._pytest_command(group),
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr

def test_unclassified_mode_covers_new_root_tests_without_running_named_chunks(monkeypatch):
    module = _load_module()
    general = module.RootTestGroup("general:test_new", ("test/test_new.py",), ("test/test_new.py",))
    named = module.RootTestGroup("support", ("test/test_known.py",), ("test/test_known.py",))
    monkeypatch.setattr(module, "build_root_test_groups", lambda: (general, named))
    captured = []
    monkeypatch.setattr(module, "run_root_test_groups", lambda groups, **kwargs: captured.extend(groups) or 0)
    assert module.main(["--unclassified"]) == 0
    assert captured == [general]


def test_demo_groups_preserve_bundle_working_directories():
    module = _load_module()
    groups = module.build_demo_test_groups()
    expected = set((REPO_ROOT / "src/agilab/demos/resources").glob("*/tests.py"))
    assert expected
    assert {group.working_directory / "tests.py" for group in groups} == expected
    for group in groups:
        command = module._pytest_command(
            group, Path("test-results/coverage-demos.db"), Path("test-results"),
            REPO_ROOT / ".coveragerc.demo-resources",
        )
        assert "pytest" in command
        assert "tools.testing.pytest_entrypoint" not in command
        assert f"--rcfile={REPO_ROOT / '.coveragerc.demo-resources'}" in command
        assert group.pytest_args[-1] == "tests.py"


def test_coverage_groups_keep_process_isolation_and_collect_each_report(tmp_path, monkeypatch):
    from coverage import CoverageData

    module = _load_module()
    checkout = tmp_path / "checkout"
    sources = checkout / "src/agilab"
    sources.mkdir(parents=True)
    (sources / "example.py").write_text("def answer():\n    return 42\n")
    tests = checkout / "test"
    tests.mkdir()
    (tests / "test_first.py").write_text(
        "import sys, example\n"
        "def test_first():\n"
        "    sys.modules['coverage_contract_pollution'] = object()\n"
        "    assert example.answer() == 42\n"
    )
    (tests / "test_second.py").write_text(
        "import sys, example\n"
        "def test_second():\n"
        "    assert 'coverage_contract_pollution' not in sys.modules\n"
        "    assert example.answer() == 42\n"
    )
    (checkout / ".coveragerc.agi-gui").write_text("[run]\nbranch = true\n")
    monkeypatch.setattr(module, "REPO_ROOT", checkout)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(REPO_ROOT), str(sources))))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/not-the-test-environment")
    groups = [
        module.RootTestGroup(f"general:{name}", ("-c", "/dev/null", f"test/test_{name}.py"), (f"test/test_{name}.py",))
        for name in ("first", "second")
    ]
    output = tmp_path / "evidence"
    assert module.run_root_test_groups(
        groups, coverage_data_file=output / "coverage.db", junit_dir=output,
    ) == 0
    databases = list(output.glob("coverage.db.*"))
    assert len(databases) == 2
    assert len(list(output.glob("junit-agi-gui-general-*.xml"))) == 2
    for path in databases:
        data = CoverageData(basename=str(path))
        data.read()
        assert 2 in data.lines(str(sources / "example.py"))
