from __future__ import annotations

from dataclasses import replace
import importlib.util
import os
import shutil
import venv
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
    requires_python: str = ">=3.12",
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
        directory_identity=venv_linker._venv_directory_identity(project / ".venv"),
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

    bad_project = tmp_path / "bad_project_table"
    bad_project.mkdir()
    (bad_project / ".venv").mkdir()
    (bad_project / "pyproject.toml").write_text('project = "bad"\n', encoding="utf-8")
    assert venv_linker.load_project_requirements(bad_project).dependencies == ()


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
    assert (
        "project declares dynamic dependencies or Python requirements"
        in skipped[0]["details"]
    )


def test_invalid_target_dependency_blocks_link(tmp_path: Path) -> None:
    target = tmp_path / "invalid_project"
    candidate = tmp_path / "candidate_project"
    _write_project(target, ["not["])
    _write_project(candidate, ["requests>=2"])

    target_state = _state(target, [])
    candidate_state = _state(candidate, [_dist("requests", "2.32.0")])

    actions, skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert actions == ()
    assert "invalid metadata in target project: project.dependencies[0] must be a valid requirement string" in skipped[0]["details"]


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


def test_marker_evaluation_errors_refuse_compatibility() -> None:
    class BadMarker:
        def evaluate(self, _environment):
            raise TypeError("bad marker")

    class BadRequirement:
        marker = BadMarker()

    with pytest.raises(ValueError, match="marker cannot be evaluated"):
        venv_linker._marker_applies(BadRequirement(), default_environment())


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
    assert "invalid installed dependency for demo" in skipped[0]["details"]


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
    target_state = _state(target, [])
    (target / ".venv").rmdir()
    (target / ".venv").symlink_to(candidate / ".venv", target_is_directory=True)

    candidate_state = _state(candidate, [_dist("requests", "2.32.0")])

    actions, skipped = venv_linker.build_link_plan([target_state, candidate_state])

    assert actions == ()
    assert skipped[0]["reason"] == "target venv is already a symlink"


def test_inspect_venv_reads_python_and_installed_distributions(tmp_path: Path) -> None:
    project = tmp_path / "actual_project"
    _write_project(project, [])
    venv.EnvBuilder(with_pip=False).create(project / ".venv")

    state = venv_linker.inspect_venv(project / ".venv")

    assert state.project.project_path == project
    assert state.python.major == sys.version_info.major
    assert state.python.minor == sys.version_info.minor
    assert state.distributions == {}
    assert state.directory_identity


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


def test_legacy_registration_dry_run_requires_separate_operation(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="registration.*separate"):
        venv_linker.apply_link_actions([], {}, install_projects=True)


def test_legacy_registration_apply_requires_separate_operation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="registration.*separate"):
        venv_linker.apply_link_actions([], {}, dry_run=False, install_projects=True)


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


def test_apply_dry_run_leaves_target_venv_unchanged(
    monkeypatch, tmp_path: Path
) -> None:
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
    states = {
        small / ".venv": _state(small, [_dist("requests", "2.32.0")]),
        large / ".venv": _state(
            large, [_dist("requests", "2.32.0"), _dist("pandas", "2.3.0")]
        ),
    }
    calls = []
    monkeypatch.setattr(
        venv_linker.subprocess, "run", lambda *args, **kwargs: calls.append(kwargs)
    )

    venv_linker.apply_link_actions([action], states, dry_run=True)

    assert calls == []
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
    states = {
        small / ".venv": _state(small, [_dist("requests", "2.32.0")]),
        large / ".venv": _state(
            large, [_dist("requests", "2.32.0"), _dist("pandas", "2.3.0")]
        ),
    }

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
            inspect_venv_fn=states.__getitem__,
        )

    assert (small / ".venv").is_dir()
    assert (small / ".venv" / "old.txt").read_text(encoding="utf-8") == "old env\n"
    assert not list(small.glob(".venv.agilab-linking*"))


@pytest.mark.parametrize("dangling", [False, True])
def test_apply_preserves_existing_symlink(tmp_path: Path, dangling: bool) -> None:
    target, donor, states, actions = _prepared_link(tmp_path)
    (target / ".venv").rename(target / "owned-original")
    other = tmp_path / "other-env"
    if not dangling:
        other.mkdir()
    (target / ".venv").symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink or file"):
        venv_linker.apply_link_actions(
            actions,
            states,
            dry_run=False,
            install_projects=False,
            inspect_venv_fn=states.__getitem__,
        )
    assert (target / ".venv").is_symlink()
    assert (target / ".venv").readlink() == other
    assert (target / "owned-original/original.txt").read_text() == "original\n"
    assert not list(target.glob(".venv.agilab-linking*"))


def test_failed_link_preserves_occupied_target_and_original_then_retry(
    monkeypatch, tmp_path: Path
) -> None:
    target, donor, states, actions = _prepared_link(tmp_path)
    original = Path.symlink_to

    def occupy_then_fail(path, *args, **kwargs):
        if path == target / ".venv":
            path.mkdir()
            (path / "occupant.txt").write_text("preserve occupant\n")
            raise OSError("injected final link failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "symlink_to", occupy_then_fail)
    with pytest.raises(OSError, match="preserved original"):
        venv_linker.apply_link_actions(
            actions,
            states,
            dry_run=False,
            install_projects=False,
            inspect_venv_fn=states.__getitem__,
        )
    stages = sorted(target.glob(".venv.agilab-linking*"))
    assert len(stages) == 1
    assert (stages[0] / "original/original.txt").read_text() == "original\n"
    assert (target / ".venv/occupant.txt").read_text() == "preserve occupant\n"
    # Resolve only this test-owned occupant, restore the retained original, replan.
    (target / ".venv").rename(target / "owned-occupant")
    (stages[0] / "original").rename(target / ".venv")
    shutil.rmtree(stages[0])
    monkeypatch.setattr(Path, "symlink_to", original)
    fresh_actions, _ = venv_linker.build_link_plan(list(states.values()))
    venv_linker.apply_link_actions(
        fresh_actions,
        states,
        dry_run=False,
        install_projects=False,
        inspect_venv_fn=states.__getitem__,
    )
    assert (target / ".venv").resolve() == (donor / ".venv").resolve()
    assert (target / "owned-occupant/occupant.txt").read_text() == "preserve occupant\n"


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


def _prepared_link(tmp_path: Path):
    target = tmp_path / "small_project"
    donor = tmp_path / "large_project"
    _write_project(target, ["demo>=1"])
    _write_project(donor, ["demo>=1", "padding>=1"])
    (target / ".venv" / "original.txt").write_text("original\n")
    states = {
        target / ".venv": _state(target, [_dist("demo")]),
        donor / ".venv": _state(donor, [_dist("demo"), _dist("padding")]),
    }
    actions, _ = venv_linker.build_link_plan(list(states.values()))
    assert len(actions) == 1
    assert actions[0].target_project == target
    return target, donor, states, actions


@pytest.mark.parametrize("leaf", [None, _dist("leaf", "0.1")])
def test_ordinary_transitive_dependency_must_be_satisfied(leaf) -> None:
    distributions = {"demo": _dist("demo", requires=("leaf>=1",))}
    if leaf is not None:
        distributions["leaf"] = leaf
    result = venv_linker.requirement_satisfied(
        Requirement("demo"), distributions, default_environment()
    )
    assert not result.ok
    assert result.missing or result.conflicts


def test_dependency_closure_handles_cycles_and_environment_markers() -> None:
    distributions = {
        "demo": _dist("demo", requires=("leaf>=1", 'absent; python_version < "2"')),
        "leaf": _dist("leaf", requires=("demo>=1",)),
    }
    assert venv_linker.requirement_satisfied(
        Requirement("demo"), distributions, default_environment()
    ).ok


def test_unverified_direct_url_is_not_satisfied_by_name_alone() -> None:
    result = venv_linker.requirement_satisfied(
        Requirement("demo @ https://invalid.example/unverified.whl"),
        {"demo": _dist("demo")},
        default_environment(),
    )
    assert not result.ok
    assert "direct URL identity" in result.conflicts[0]


def test_inspect_refuses_python_that_is_not_in_selected_venv(tmp_path: Path) -> None:
    _write_project(tmp_path / "fake", [])
    python = tmp_path / "fake/.venv/bin/python"
    python.parent.mkdir()
    python.symlink_to(sys.executable)
    with pytest.raises(ValueError, match="not running in the selected"):
        venv_linker.inspect_venv(python.parent.parent)


@pytest.mark.parametrize("changed_project", ["small_project", "large_project"])
@pytest.mark.parametrize("filename", ["pyproject.toml", "uv.lock"])
def test_stale_manifest_bytes_refuse_apply(
    tmp_path: Path, changed_project: str, filename: str
) -> None:
    target, _donor, states, actions = _prepared_link(tmp_path)
    path = tmp_path / changed_project / filename
    before = path.stat() if path.exists() else None
    path.write_text(
        path.read_text().replace('version = "0.0.0"', 'version = "0.0.1"')
        if before
        else "version = 1\nrevision = 2\n"
    )
    if before:
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match="changed"):
        venv_linker.apply_link_actions(
            actions,
            states,
            dry_run=False,
            install_projects=False,
            inspect_venv_fn=states.__getitem__,
        )
    assert not (target / ".venv").is_symlink()
    assert (target / ".venv/original.txt").read_text() == "original\n"


def test_replaced_directory_refuses_stale_action(tmp_path: Path) -> None:
    target, _donor, states, actions = _prepared_link(tmp_path)
    (target / ".venv").rename(target / "owned-original")
    (target / ".venv").mkdir()
    (target / ".venv/new.txt").write_text("preserve\n")
    with pytest.raises(ValueError, match="changed"):
        venv_linker.apply_link_actions(
            actions,
            states,
            dry_run=False,
            install_projects=False,
            inspect_venv_fn=states.__getitem__,
        )
    assert (target / ".venv/new.txt").read_text() == "preserve\n"
    assert (target / "owned-original/original.txt").read_text() == "original\n"


def test_runtime_distribution_drift_refuses_stale_action(tmp_path: Path) -> None:
    target, donor, states, actions = _prepared_link(tmp_path)
    current = dict(states)
    current[donor / ".venv"] = replace(
        states[donor / ".venv"], distributions={"demo": _dist("demo", "0.1")}
    )
    with pytest.raises(ValueError, match="changed"):
        venv_linker.apply_link_actions(
            actions,
            states,
            dry_run=False,
            install_projects=False,
            inspect_venv_fn=current.__getitem__,
        )
    assert (target / ".venv/original.txt").read_text() == "original\n"


def test_staging_failure_preserves_original_and_retry_succeeds(
    monkeypatch, tmp_path: Path
) -> None:
    target, donor, states, actions = _prepared_link(tmp_path)
    original = Path.symlink_to

    def fail_staging(path, *args, **kwargs):
        if path.name == "link":
            path.mkdir()
            (path / "owned-partial.txt").write_text("partial\n")
            raise OSError("injected staging failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "symlink_to", fail_staging)
    with pytest.raises(OSError, match="injected staging failure"):
        venv_linker.apply_link_actions(
            actions,
            states,
            dry_run=False,
            install_projects=False,
            inspect_venv_fn=states.__getitem__,
        )
    assert (target / ".venv/original.txt").read_text() == "original\n"
    assert not list(target.glob(".venv.agilab-linking*"))
    monkeypatch.setattr(Path, "symlink_to", original)
    venv_linker.apply_link_actions(
        actions,
        states,
        dry_run=False,
        install_projects=False,
        inspect_venv_fn=states.__getitem__,
    )
    assert (target / ".venv").resolve() == (donor / ".venv").resolve()


def test_default_is_dry_run_and_no_install_does_not_write_donor(
    monkeypatch, tmp_path: Path
) -> None:
    target, donor, states, _actions = _prepared_link(tmp_path)
    sentinel = donor / ".venv/donor.txt"
    sentinel.write_bytes(b"donor unchanged")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("donor registration was not authorized")

    monkeypatch.setattr(venv_linker.subprocess, "run", forbidden)
    report = venv_linker.link_compatible_venvs(
        [tmp_path], install_projects=False, inspect_venv_fn=states.__getitem__
    )
    assert not report.applied
    assert not (target / ".venv").is_symlink()
    venv_linker.link_compatible_venvs(
        [tmp_path],
        apply=True,
        install_projects=False,
        inspect_venv_fn=states.__getitem__,
    )
    assert sentinel.read_bytes() == b"donor unchanged"


@pytest.mark.parametrize("role", ["target", "canonical"])
def test_action_path_cannot_substitute_uninspected_environment(
    tmp_path: Path, role: str
) -> None:
    target, donor, states, actions = _prepared_link(tmp_path)
    unknown = tmp_path / "owned-uninspected-environment"
    unknown.mkdir()
    (unknown / "preserve.txt").write_text("preserve uninspected environment\n")
    if role == "target":
        action = replace(actions[0], target_venv=unknown)
        states[unknown] = states[target / ".venv"]
    else:
        action = replace(actions[0], canonical_venv=unknown)
        states[unknown] = states[donor / ".venv"]
    with pytest.raises(ValueError, match="does not match"):
        venv_linker.apply_link_actions(
            [action],
            states,
            dry_run=False,
            install_projects=False,
            inspect_venv_fn=states.__getitem__,
        )
    assert not unknown.is_symlink()
    assert (
        unknown / "preserve.txt"
    ).read_text() == "preserve uninspected environment\n"
    assert not (target / ".venv").is_symlink()



@pytest.mark.parametrize("metadata", [
    'project="invalid"',
    '[tool.fixture]\nname="virtual"',
    '[project]\nname=42',
    '[project]\nname="valid"\ndependencies="demo>=2"',
    '[project]\nname="valid"\ndependencies={demo=">=2"}',
    '[project]\nname="valid"\ndependencies=[false]',
    '[project]\nname="valid"\ndependencies=["not["]',
    '[project]\nname="valid"\noptional-dependencies=[]',
    '[project]\nname="valid"\noptional-dependencies={plot="demo"}',
    '[project]\nname="valid"\noptional-dependencies={plot=[true]}',
    '[project]\nname="valid"\nrequires-python=42',
    '[project]\nname="valid"\nrequires-python="invalid"',
    '[project]\nname="valid"\ndynamic="dependencies"',
    '[project]\nname="valid"\ndynamic=[false]',
])
def test_malformed_metadata_refuses_both_roles_without_mutation(tmp_path: Path, metadata: str) -> None:
    target, donor = tmp_path / "target", tmp_path / "donor"
    _write_project(target, [])
    _write_project(donor, ["demo"])
    (target / "pyproject.toml").write_text(metadata)
    for project in (target, donor):
        (project / ".venv/sentinel").write_bytes(b"keep")
    invalid, valid = _state(target, []), _state(donor, [_dist("demo")])
    assert invalid.project.invalid_dependencies
    assert not venv_linker.candidate_satisfies_project(invalid, valid).ok
    assert not venv_linker.candidate_satisfies_project(valid, invalid).ok
    assert all((project / ".venv/sentinel").read_bytes() == b"keep" for project in (target, donor))


@pytest.mark.parametrize("content", [b"[project", b"\xffcredential-sentinel"])
def test_unreadable_metadata_refusal_is_sanitized(tmp_path: Path, content: bytes) -> None:
    project = tmp_path / "target"
    _write_project(project, [])
    (project / "pyproject.toml").write_bytes(content)
    with pytest.raises(ValueError, match="metadata is unreadable or malformed") as error:
        venv_linker.load_project_requirements(project)
    assert "credential-sentinel" not in str(error.value)


@pytest.mark.parametrize("leaf_version", [None, "0.1", "1.0"])
def test_extra_requested_through_cycle_is_checked_and_terminates(leaf_version) -> None:
    packages = {
        "a": _dist("a", requires=("b", 'leaf>=1; extra == "x"', 'inactive; python_version < "2"')),
        "b": _dist("b", requires=("a[x]",)),
    }
    if leaf_version is not None:
        packages["leaf"] = _dist("leaf", leaf_version)
    result = venv_linker.requirement_satisfied(Requirement("a"), packages, default_environment())
    assert result.ok is (leaf_version == "1.0")
    if not result.ok:
        assert result.missing or result.conflicts


def test_multiple_cycle_extra_contexts_do_not_hide_each_other() -> None:
    packages = {
        "a": _dist("a", requires=("b", 'left; extra == "x"', 'right; extra == "y"')),
        "b": _dist("b", requires=("a[x]", "a[y]")),
        "left": _dist("left"),
    }
    result = venv_linker.requirement_satisfied(Requirement("a"), packages, default_environment())
    assert not result.ok and any("right" in item for item in result.missing)
    packages["right"] = _dist("right")
    assert venv_linker.requirement_satisfied(Requirement("a"), packages, default_environment()).ok


@pytest.mark.parametrize("mutation", [
    {"origin": "different-origin"}, {"content_hash": "different-resource"},
    {"version": "2.0"}, {"identity_error": "invalid identity"}, {"content_hash": None},
])
def test_installed_application_identity_is_required(tmp_path: Path, mutation: dict) -> None:
    target, donor = tmp_path / "target", tmp_path / "donor"
    _write_project(target, [])
    _write_project(donor, [])
    application = replace(_dist("target"), origin="verified-origin", content_hash="verified-files")
    expected = _state(target, [application])
    candidate = _state(donor, [replace(application, **mutation)])
    result = venv_linker.candidate_satisfies_project(expected, candidate)
    assert not result.ok and "application" in result.conflicts[0]


def test_application_absence_and_unexpected_collision_refuse(tmp_path: Path) -> None:
    target, donor = tmp_path / "target", tmp_path / "donor"
    _write_project(target, [])
    _write_project(donor, [])
    application = replace(_dist("target"), origin="origin", content_hash="files")
    empty_target, installed_target = _state(target, []), _state(target, [application])
    empty_donor, installed_donor = _state(donor, []), _state(donor, [application])
    assert not venv_linker.candidate_satisfies_project(installed_target, empty_donor).ok
    assert not venv_linker.candidate_satisfies_project(empty_target, installed_donor).ok


@pytest.mark.parametrize("fragment", [
    'unknown="credential-sentinel"',
    'version=999',
    'revision=999',
    'package="not-an-array"',
    'options="not-a-table"',
])
def test_unsupported_authoritative_lock_shape_is_explicit(tmp_path: Path, fragment: str) -> None:
    payload = {'version': 'version=1', 'revision': 'revision=3', 'package': 'package=[]'}
    key = fragment.split("=", 1)[0]
    payload[key] = fragment
    path = tmp_path / "uv.lock"
    path.write_text("\n".join(payload.values()) + '\nrequires-python=">=3.13"\n')
    with pytest.raises(ValueError, match="authoritative uv.lock shape") as error:
        venv_linker._validate_lock_shape(path)
    assert "credential-sentinel" not in str(error.value)


def test_project_and_direct_url_diagnostics_do_not_echo_credentials(tmp_path: Path) -> None:
    project = tmp_path / "target"
    _write_project(project, ["demo @ https://user:credential-sentinel@example.invalid/not a wheel"])
    state = _state(project, [_dist("demo")])
    result = venv_linker.candidate_satisfies_project(state, state)
    assert not result.ok
    assert "credential-sentinel" not in repr(result)
    result = venv_linker.requirement_satisfied(
        Requirement("demo @ https://user:credential-sentinel@example.invalid/package.whl"),
        {"demo": _dist("demo")}, default_environment(),
    )
    assert not result.ok and "credential-sentinel" not in repr(result)


@pytest.mark.parametrize(
    "metadata",
    [
        '[project]\nname="target"\nversion=42\ndependencies=[]',
        '[project]\nname="target"\nversion="not a version"\ndependencies=[]',
        '[project]\nname="target"\ndynamic=["requires-python"]\ndependencies=[]',
        '[project]\nname="target"\ndependencies=[]\n[tool.uv]\nsources="invalid"',
        '[project]\nname="target"\ndependencies=[]\n[tool.uv.sources]\ndemo={path="source-demo"}',
        'tool="invalid"\n[project]\nname="target"\ndependencies=[]',
    ],
)
def test_unqualified_python_or_source_metadata_refuses_both_roles(
    tmp_path: Path, metadata: str
) -> None:
    target, donor = tmp_path / "target", tmp_path / "donor"
    _write_project(target, [])
    _write_project(donor, ["demo"])
    (target / "pyproject.toml").write_text(metadata)
    for project in (target, donor):
        (project / ".venv/sentinel").write_bytes(b"preserve")
    invalid, valid = _state(target, []), _state(donor, [_dist("demo")])
    for first, second in ((invalid, valid), (valid, invalid)):
        result = venv_linker.candidate_satisfies_project(first, second)
        assert not result.ok
        assert any("metadata" in item or "dynamic" in item for item in result.conflicts)
    assert all(
        (project / ".venv/sentinel").read_bytes() == b"preserve"
        for project in (target, donor)
    )



def _review_tree(root: Path):
    rows = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        rows[str(path.relative_to(root))] = (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            str(path.readlink())
            if path.is_symlink()
            else path.read_bytes()
            if path.is_file()
            else None,
        )
    return rows


@pytest.mark.parametrize(
    "layout",
    [
        "donor-inside",
        "target-inside",
        "alias",
        "equal",
        "input-inside",
        "project-inside",
    ],
)
@pytest.mark.parametrize("entrypoint", ["planner", "apply"])
def test_review_overlapping_paths_refuse_before_mutation(
    monkeypatch, tmp_path, layout, entrypoint
):
    if layout in ("donor-inside", "alias", "project-inside"):
        target = tmp_path / "target"
        donor = target / ".venv/nested"
        _write_project(target, [])
        _write_project(donor, [])
    elif layout == "target-inside":
        donor = tmp_path / "donor"
        target = donor / ".venv/nested"
        _write_project(donor, [])
        _write_project(target, [])
    else:
        target, donor = tmp_path / "target", tmp_path / "donor"
        _write_project(target, [])
        _write_project(donor, [])
    for project in (target, donor):
        (project / ".venv/preserve.txt").write_text(str(project))
    target_state, donor_state = _state(target, []), _state(donor, [_dist("padding")])
    if layout in ("alias", "equal"):
        alias = tmp_path / "owned-alias"
        alias.symlink_to(
            donor if layout == "alias" else target, target_is_directory=True
        )
        donor_state = replace(
            donor_state, project=replace(donor_state.project, venv_path=alias / ".venv")
        )
    elif layout == "input-inside":
        manifest = target / ".venv/donor-input.toml"
        (donor / "pyproject.toml").rename(manifest)
        (donor / "pyproject.toml").symlink_to(manifest)
        donor_state = _state(donor, [_dist("padding")])
    elif layout == "project-inside":
        external = tmp_path / "external-env"
        external.mkdir()
        donor_state = replace(
            donor_state, project=replace(donor_state.project, venv_path=external)
        )
    states = {s.project.venv_path: s for s in (target_state, donor_state)}
    action = venv_linker.LinkAction(
        target_state.project.project_path,
        target_state.project.venv_path,
        donor_state.project.project_path,
        donor_state.project.venv_path,
        "review",
        0,
        1,
    )
    before = _review_tree(tmp_path)

    def mutation(*args, **kwargs):
        raise AssertionError("Mutation attempted before overlap refusal")

    monkeypatch.setattr(venv_linker.tempfile, "mkdtemp", mutation)
    if entrypoint == "planner":
        actions, skipped = venv_linker.build_link_plan(list(states.values()))
        assert not actions
        assert any(
            "overlap" in str(row).lower() or "contains" in str(row).lower()
            for row in skipped
        )
    else:
        with pytest.raises(ValueError, match="overlap|contains"):
            venv_linker.apply_link_actions(
                [action], states, dry_run=False, inspect_venv_fn=states.__getitem__
            )
    assert _review_tree(tmp_path) == before


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("alias", [False, True])
def test_review_explicit_root_discovery_refuses_nested_environments(
    tmp_path, reverse, alias
):
    outer = tmp_path / "outer"
    inner = outer / ".venv/nested"
    _write_project(outer, [])
    _write_project(inner, [])
    roots = [outer, inner]
    if alias:
        alias_path = tmp_path / "owned-root-alias"
        alias_path.symlink_to(inner, target_is_directory=True)
        roots[1] = alias_path
    states = {
        p / ".venv": _state(p, [_dist("padding")] if (p == outer) == reverse else [])
        for p in (outer, inner)
    }
    before = _review_tree(tmp_path)
    report = venv_linker.link_compatible_venvs(
        roots, apply=True, inspect_venv_fn=states.__getitem__
    )
    assert not report.actions
    assert "overlap" in str(report.skipped).lower()
    assert _review_tree(tmp_path) == before


@pytest.mark.parametrize("application", ["absent", "non-package", "wheel", "editable"])
@pytest.mark.parametrize("entrypoint", ["api", "cli"])
def test_review_default_link_preserves_donor(
    monkeypatch, tmp_path, capsys, application, entrypoint
):
    target, donor, states, actions = _prepared_link(tmp_path)
    if application == "non-package":
        with (target / "pyproject.toml").open("a") as handle:
            handle.write("\n[tool.uv]\npackage = false\n")
        states[target / ".venv"] = _state(target, [_dist("demo")])
    elif application in ("wheel", "editable"):
        app = venv_linker.DistributionInfo(
            name=states[target / ".venv"].project.name,
            version="1",
            origin="verified-fixture-origin",
            content_hash="verified-content",
            editable_path=str(target.resolve()) if application == "editable" else None,
        )
        for path, state in list(states.items()):
            states[path] = replace(
                state, distributions={**state.distributions, app.name: app}
            )
    before = _review_tree(donor)

    def install(*args, **kwargs):
        raise AssertionError("Linking must not install into the donor")

    monkeypatch.setattr(venv_linker.subprocess, "run", install)
    if entrypoint == "api":
        venv_linker.apply_link_actions(
            actions, states, dry_run=False, inspect_venv_fn=states.__getitem__
        )
    else:
        original = venv_linker.link_compatible_venvs

        def selected(roots, **kwargs):
            assert kwargs.get("install_projects", False) is False
            return original(roots, **kwargs, inspect_venv_fn=states.__getitem__)

        monkeypatch.setattr(venv_linker, "link_compatible_venvs", selected)
        assert venv_linker.main(["--root", str(tmp_path), "--apply", "--compact"]) == 0
        assert json.loads(capsys.readouterr().out)["linked_count"] == 1
    assert (target / ".venv").resolve() == (donor / ".venv").resolve()
    assert _review_tree(donor) == before


@pytest.mark.parametrize("dry_run", [False, True])
def test_review_registration_request_refuses_and_supported_retry_succeeds(
    monkeypatch, tmp_path, dry_run
):
    target, donor, states, actions = _prepared_link(tmp_path)
    before = _review_tree(tmp_path)

    def install(*args, **kwargs):
        raise AssertionError("Registration must refuse before invoking an installer")

    monkeypatch.setattr(venv_linker.subprocess, "run", install)
    with pytest.raises(
        ValueError, match="registration.*separate|registration.*supported"
    ):
        venv_linker.apply_link_actions(
            actions,
            states,
            dry_run=dry_run,
            install_projects=True,
            inspect_venv_fn=states.__getitem__,
        )
    assert _review_tree(tmp_path) == before
    venv_linker.apply_link_actions(
        actions, states, dry_run=False, inspect_venv_fn=states.__getitem__
    )
    assert (target / ".venv").resolve() == (donor / ".venv").resolve()
