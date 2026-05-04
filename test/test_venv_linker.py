from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import sysconfig

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "src/agilab/venv_linker.py"
SPEC = importlib.util.spec_from_file_location("venv_linker_test_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
venv_linker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = venv_linker
SPEC.loader.exec_module(venv_linker)


def _write_project(
    project: Path,
    dependencies: list[str],
    *,
    requires_python: str = ">=3.11",
    dynamic_dependencies: bool = False,
) -> None:
    project.mkdir(parents=True)
    (project / ".venv").mkdir()
    dependency_lines = "\n".join(f'  "{dependency}",' for dependency in dependencies)
    dynamic_line = 'dynamic = ["dependencies"]\n' if dynamic_dependencies else ""
    dependencies_block = f"dependencies = [\n{dependency_lines}\n]\n" if dependencies else "dependencies = []\n"
    (project / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "' + project.name.replace("_", "-") + '"',
                'version = "0.0.0"',
                f'requires-python = "{requires_python}"',
                dynamic_line + dependencies_block,
            ]
        ),
        encoding="utf-8",
    )


def _python_info(project: Path, *, version: str = "3.13.7") -> venv_linker.PythonInfo:
    major_text, minor_text, *_ = version.split(".")
    environment = default_environment()
    environment.update(
        {
            "python_full_version": version,
            "python_version": f"{major_text}.{minor_text}",
            "sys_platform": sys.platform,
        }
    )
    return venv_linker.PythonInfo(
        executable=project / ".venv" / "bin" / "python",
        version=version,
        major=int(major_text),
        minor=int(minor_text),
        abiflags="",
        platform=sysconfig.get_platform(),
        marker_environment=environment,
    )


def _dist(
    name: str,
    version: str = "1.0.0",
    *,
    requires: tuple[str, ...] = (),
) -> venv_linker.DistributionInfo:
    return venv_linker.DistributionInfo(name=name, version=version, requires=requires)


def _state(
    project: Path,
    distributions: list[venv_linker.DistributionInfo],
    *,
    python_version: str = "3.13.7",
) -> venv_linker.VenvState:
    return venv_linker.VenvState(
        project=venv_linker.load_project_requirements(project),
        python=_python_info(project, version=python_version),
        distributions={canonicalize_name(dist.name): dist for dist in distributions},
    )


def test_larger_installed_environment_can_satisfy_smaller_project(tmp_path: Path) -> None:
    small = tmp_path / "small_project"
    large = tmp_path / "large_project"
    _write_project(small, ["requests>=2"])
    _write_project(large, ["requests>=2", "pandas>=2"])

    small_state = _state(small, [_dist("requests", "2.32.0")])
    large_state = _state(large, [_dist("requests", "2.32.0"), _dist("pandas", "2.3.0")])

    actions, skipped = venv_linker.build_link_plan([small_state, large_state])

    assert len(actions) == 1
    assert actions[0].target_project == small
    assert actions[0].canonical_project == large
    assert actions[0].target_package_count < actions[0].canonical_package_count
    assert skipped == (
        {
            "project": str(large),
            "reason": "environment selected as canonical for another project",
        },
    )


def test_discover_projects_filters_unusable_candidates(tmp_path: Path) -> None:
    root = tmp_path / "root"
    valid = root / "valid_project"
    excluded = root / ".venv" / "ignored_project"
    linked = root / "linked_project"
    _write_project(valid, [])
    _write_project(excluded, [])
    _write_project(linked, [])
    (linked / ".venv").rmdir()
    (linked / ".venv").symlink_to(valid / ".venv", target_is_directory=True)

    projects = venv_linker.discover_projects([tmp_path / "missing", root, root])

    assert [project.project_path for project in projects] == [valid]


def test_requirement_metadata_edge_cases(tmp_path: Path) -> None:
    no_project = tmp_path / "no_project_table"
    no_project.mkdir()
    (no_project / ".venv").mkdir()
    (no_project / "pyproject.toml").write_text("[tool.demo]\nname = 'demo'\n", encoding="utf-8")
    python = _python_info(no_project)

    requirements = venv_linker.load_project_requirements(no_project)

    assert requirements.dependencies == ()
    assert venv_linker._requires_python_ok("", python)
    assert not venv_linker._requires_python_ok("not a specifier", python)
    assert venv_linker._version_ok(Requirement("demo"), _dist("demo", "not-a-version"))
    assert not venv_linker._version_ok(Requirement("demo>=1"), _dist("demo", "not-a-version"))


def test_candidate_requirements_are_checked_from_installed_packages(tmp_path: Path) -> None:
    target = tmp_path / "target_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, ["requests>=3"])
    _write_project(candidate, ["requests>=2", "pandas>=2"])

    target_state = _state(target, [_dist("requests", "3.0.0")])
    candidate_state = _state(candidate, [_dist("requests", "2.32.0"), _dist("pandas", "2.3.0")])

    actions, skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert actions == ()
    assert skipped[0]["project"] == str(target)
    assert "requests>=3 installed=2.32.0" in skipped[0]["details"]


def test_extra_dependencies_must_be_present_in_candidate(tmp_path: Path) -> None:
    target = tmp_path / "target_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, ["demo[plot]>=1"])
    _write_project(candidate, ["demo>=1", "other>=1"])

    target_state = _state(target, [_dist("demo", "1.0.0")])
    candidate_state = _state(
        candidate,
        [
            _dist("demo", "1.0.0", requires=('matplotlib>=3; extra == "plot"',)),
            _dist("matplotlib", "3.10.0"),
            _dist("other", "1.0.0"),
        ],
    )

    actions, _skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert len(actions) == 1
    assert actions[0].target_project == target
    assert actions[0].canonical_project == candidate


def test_missing_extra_dependency_blocks_link(tmp_path: Path) -> None:
    target = tmp_path / "target_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, ["demo[plot]>=1"])
    _write_project(candidate, ["demo>=1", "other>=1"])

    target_state = _state(target, [_dist("demo", "1.0.0")])
    candidate_state = _state(
        candidate,
        [
            _dist("demo", "1.0.0", requires=('matplotlib>=3; extra == "plot"',)),
            _dist("other", "1.0.0"),
        ],
    )

    actions, skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert actions == ()
    assert any("matplotlib>=3" in detail for detail in skipped[0]["details"])


def test_dynamic_dependencies_are_not_linked(tmp_path: Path) -> None:
    target = tmp_path / "dynamic_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, [], dynamic_dependencies=True)
    _write_project(candidate, ["requests>=2"])

    target_state = _state(target, [])
    candidate_state = _state(candidate, [_dist("requests", "2.32.0")])

    actions, skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert actions == ()
    assert "project declares dynamic dependencies" in skipped[0]["details"]


def test_invalid_target_dependency_blocks_link(tmp_path: Path) -> None:
    target = tmp_path / "invalid_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, ["not["])
    _write_project(candidate, ["requests>=2"])

    target_state = _state(target, [])
    candidate_state = _state(candidate, [_dist("requests", "2.32.0")])

    actions, skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert actions == ()
    assert "invalid dependency in target project: not[" in skipped[0]["details"]


def test_python_abi_mismatch_blocks_link(tmp_path: Path) -> None:
    target = tmp_path / "target_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, ["requests>=2"])
    _write_project(candidate, ["requests>=2"])

    target_state = _state(target, [_dist("requests", "2.32.0")], python_version="3.13.7")
    candidate_state = _state(candidate, [_dist("requests", "2.32.0")], python_version="3.12.11")

    check = venv_linker.candidate_satisfies_project(target_state, candidate_state)

    assert not check.ok
    assert "python ABI mismatch" in check.conflicts[0]


def test_requires_python_conflict_blocks_link(tmp_path: Path) -> None:
    target = tmp_path / "target_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, [], requires_python=">=3.99")
    _write_project(candidate, [])

    target_state = _state(target, [])
    candidate_state = _state(candidate, [])

    check = venv_linker.candidate_satisfies_project(target_state, candidate_state)

    assert not check.ok
    assert "does not satisfy >=3.99" in check.conflicts[0]


def test_marker_mismatch_is_reported_as_skip() -> None:
    environment = default_environment()
    environment["python_version"] = "3.13"

    check = venv_linker.requirement_satisfied(
        Requirement('requests>=2; python_version < "3.0"'),
        {},
        environment,
    )

    assert check.ok
    assert check.skipped == ('requests>=2; python_version < "3.0"',)


def test_recursive_requirement_stack_short_circuits_cycle() -> None:
    check = venv_linker.requirement_satisfied(
        Requirement("demo>=1"),
        {canonicalize_name("demo"): _dist("demo", "1.0.0")},
        default_environment(),
        stack=frozenset({canonicalize_name("demo")}),
    )

    assert check.ok


def test_invalid_extra_dependency_blocks_link(tmp_path: Path) -> None:
    target = tmp_path / "target_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, ["demo[plot]>=1"])
    _write_project(candidate, ["demo>=1", "other>=1"])

    target_state = _state(target, [_dist("demo", "1.0.0")])
    candidate_state = _state(
        candidate,
        [_dist("demo", "1.0.0", requires=("not[",)), _dist("other", "1.0.0")],
    )

    actions, skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert actions == ()
    assert "not[" in skipped[0]["details"]


def test_non_matching_extra_dependency_is_ignored(tmp_path: Path) -> None:
    target = tmp_path / "target_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, ["demo[plot]>=1"])
    _write_project(candidate, ["demo>=1", "other>=1"])

    target_state = _state(target, [_dist("demo", "1.0.0")])
    candidate_state = _state(
        candidate,
        [
            _dist("demo", "1.0.0", requires=('colorama>=1; extra == "windows"',)),
            _dist("other", "1.0.0"),
        ],
    )

    actions, _skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert len(actions) == 1


def test_symlink_target_venv_is_skipped(tmp_path: Path) -> None:
    target = tmp_path / "target_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, [])
    _write_project(candidate, ["requests>=2"])
    (target / ".venv").rmdir()
    (target / ".venv").symlink_to(candidate / ".venv", target_is_directory=True)

    target_state = _state(target, [])
    candidate_state = _state(candidate, [_dist("requests", "2.32.0")])

    actions, skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert actions == ()
    assert skipped[0]["reason"] == "target venv is already a symlink"


def test_inspect_venv_reads_python_and_installed_distributions(tmp_path: Path) -> None:
    project = tmp_path / "actual_project"
    _write_project(project, [])
    python_dir = project / ".venv" / "bin"
    python_dir.mkdir()
    (python_dir / "python").symlink_to(Path(sys.executable))

    state = venv_linker.inspect_venv(project / ".venv")

    assert state.project.project_path == project
    assert state.python.major == sys.version_info.major
    assert state.python.minor == sys.version_info.minor
    assert state.distributions


def test_inspect_venv_requires_python_executable(tmp_path: Path) -> None:
    project = tmp_path / "broken_project"
    _write_project(project, [])

    with pytest.raises(FileNotFoundError):
        venv_linker.inspect_venv(project / ".venv")


def test_link_report_records_inspection_errors(tmp_path: Path) -> None:
    project = tmp_path / "broken_project"
    _write_project(project, [])

    def _broken_inspect(_venv_path: Path) -> venv_linker.VenvState:
        raise FileNotFoundError("missing python")

    report = venv_linker.link_compatible_venvs([tmp_path], inspect_venv_fn=_broken_inspect)

    assert report.actions == ()
    assert report.skipped == ({"project": str(project), "reason": "missing python"},)


def test_install_project_no_deps_dry_run_does_not_call_uv(tmp_path: Path) -> None:
    venv_linker._install_project_no_deps(
        uv="uv",
        project_path=tmp_path,
        canonical_python=tmp_path / ".venv" / "bin" / "python",
        dry_run=True,
    )


def test_apply_replaces_target_venv_with_symlink(tmp_path: Path) -> None:
    small = tmp_path / "small_project"
    large = tmp_path / "large_project"
    _write_project(small, ["requests>=2"])
    _write_project(large, ["requests>=2", "pandas>=2"])
    (small / ".venv" / "old.txt").write_text("old env\n", encoding="utf-8")

    states_by_venv = {
        (small / ".venv").resolve(strict=False): _state(small, [_dist("requests", "2.32.0")]),
        (large / ".venv").resolve(strict=False): _state(
            large,
            [_dist("requests", "2.32.0"), _dist("pandas", "2.3.0")],
        ),
    }

    def _fake_inspect(venv_path: Path) -> venv_linker.VenvState:
        return states_by_venv[venv_path.resolve(strict=False)]

    report = venv_linker.link_compatible_venvs(
        [tmp_path],
        apply=True,
        install_projects=False,
        inspect_venv_fn=_fake_inspect,
    )

    assert report.applied is True
    assert report.actions[0].target_project == small
    assert (small / ".venv").is_symlink()
    assert (small / ".venv").resolve() == (large / ".venv").resolve()
    assert not list(small.glob(".venv.agilab-linking*"))


def test_apply_dry_run_leaves_target_venv_unchanged(monkeypatch, tmp_path: Path) -> None:
    small = tmp_path / "small_project"
    large = tmp_path / "large_project"
    _write_project(small, ["requests>=2"])
    _write_project(large, ["requests>=2", "pandas>=2"])
    action = venv_linker.LinkAction(
        target_project=small,
        target_venv=small / ".venv",
        canonical_project=large,
        canonical_venv=large / ".venv",
        reason="test",
        target_package_count=1,
        canonical_package_count=2,
    )
    states = {(large / ".venv"): _state(large, [_dist("requests", "2.32.0"), _dist("pandas", "2.3.0")])}
    calls = []
    monkeypatch.setattr(venv_linker, "_install_project_no_deps", lambda **kwargs: calls.append(kwargs))

    venv_linker.apply_link_actions([action], states, dry_run=True, install_projects=True)

    assert calls[0]["dry_run"] is True
    assert (small / ".venv").is_dir()


def test_apply_rolls_back_target_venv_when_symlink_fails(monkeypatch, tmp_path: Path) -> None:
    small = tmp_path / "small_project"
    large = tmp_path / "large_project"
    _write_project(small, ["requests>=2"])
    _write_project(large, ["requests>=2", "pandas>=2"])
    (small / ".venv" / "old.txt").write_text("old env\n", encoding="utf-8")
    action = venv_linker.LinkAction(
        target_project=small,
        target_venv=small / ".venv",
        canonical_project=large,
        canonical_venv=large / ".venv",
        reason="test",
        target_package_count=1,
        canonical_package_count=2,
    )
    states = {(large / ".venv"): _state(large, [_dist("requests", "2.32.0"), _dist("pandas", "2.3.0")])}

    def _raise_symlink_error(self: Path, *_args, **_kwargs) -> None:
        if self == small / ".venv":
            raise OSError("cannot link")
        return original_symlink_to(self, *_args, **_kwargs)

    original_symlink_to = venv_linker.Path.symlink_to
    monkeypatch.setattr(venv_linker.Path, "symlink_to", _raise_symlink_error)

    with pytest.raises(OSError, match="cannot link"):
        venv_linker.apply_link_actions(
            [action],
            states,
            dry_run=False,
            install_projects=False,
        )

    assert (small / ".venv").is_dir()
    assert (small / ".venv" / "old.txt").read_text(encoding="utf-8") == "old env\n"
    assert not list(small.glob(".venv.agilab-linking*"))


def test_main_writes_report_and_compact_json(monkeypatch, tmp_path: Path, capsys) -> None:
    target = tmp_path / "target_project"
    canonical = tmp_path / "canonical_project"
    action = venv_linker.LinkAction(
        target_project=target,
        target_venv=target / ".venv",
        canonical_project=canonical,
        canonical_venv=canonical / ".venv",
        reason="test",
        target_package_count=1,
        canonical_package_count=2,
    )
    report = venv_linker.LinkReport(
        actions=(action,),
        skipped=({"project": str(tmp_path / "skipped"), "reason": "test"},),
        applied=False,
    )

    monkeypatch.setattr(venv_linker, "link_compatible_venvs", lambda *_args, **_kwargs: report)
    report_path = tmp_path / "report" / "venv_link_report.json"

    exit_code = venv_linker.main(
        [
            "--root",
            str(tmp_path),
            "--report",
            str(report_path),
            "--compact",
            "--no-install-project",
        ]
    )

    assert exit_code == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["linked_count"] == 1
    assert json.loads(capsys.readouterr().out)["actions"][0]["reason"] == "test"


def test_main_prints_pretty_json_without_report(monkeypatch, tmp_path: Path, capsys) -> None:
    report = venv_linker.LinkReport(actions=(), skipped=(), applied=False)

    monkeypatch.setattr(venv_linker, "link_compatible_venvs", lambda *_args, **_kwargs: report)

    exit_code = venv_linker.main(["--root", str(tmp_path)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert json.loads(output)["linked_count"] == 0
    assert "\n  " in output
