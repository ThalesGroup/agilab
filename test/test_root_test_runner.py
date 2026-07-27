from __future__ import annotations

import importlib.util
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
) -> None:
    module = _load_module()
    groups = (
        module.RootTestGroup("first", ("test/test_first.py",), ("test/test_first.py",)),
        module.RootTestGroup("second", ("test/test_second.py",), ("test/test_second.py",)),
    )
    calls: list[tuple[tuple[str, ...], Path, bool]] = []
    returncodes = iter((3, 0))

    def runner(command, *, cwd, check):
        calls.append((tuple(command), cwd, check))
        return SimpleNamespace(returncode=next(returncodes))

    assert module.run_root_test_groups(groups, runner=runner) == 3
    assert len(calls) == 2
    assert all(call[0][:3] == (sys.executable, "-m", "pytest") for call in calls)
    assert all(call[1:] == (REPO_ROOT, False) for call in calls)
    captured = capsys.readouterr().err
    assert "[root-test] first: failed exit=3" in captured
    assert "[root-test] second: passed" in captured


def test_root_test_runner_list_mode_is_side_effect_free(capsys) -> None:
    module = _load_module()

    assert module.main(["--list"]) == 0

    output = capsys.readouterr().out
    assert "general:test_agenticweb_manifest\t1" in output
    assert "views\t" in output
