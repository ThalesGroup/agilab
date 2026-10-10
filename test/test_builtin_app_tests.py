from __future__ import annotations

import importlib.util
import importlib.metadata
import json
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "builtin_app_tests.py"

spec = importlib.util.spec_from_file_location("builtin_app_tests", MODULE_PATH)
assert spec is not None and spec.loader is not None
builtin_app_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builtin_app_tests)


def test_discover_builtin_app_tests_returns_sorted_projects_with_tests(tmp_path):
    root = tmp_path / "builtin"
    (root / "z_project" / "test").mkdir(parents=True)
    (root / "z_project" / "test" / "test_z.py").write_text("def test_z(): pass\n")
    (root / "a_project" / "test").mkdir(parents=True)
    (root / "a_project" / "test" / "test_a.py").write_text("def test_a(): pass\n")
    (root / "empty_project" / "test").mkdir(parents=True)
    (root / "not_a_builtin_app" / "test").mkdir(parents=True)
    (root / "not_a_builtin_app" / "test" / "test_skip.py").write_text("def test_skip(): pass\n")

    targets = builtin_app_tests.discover_builtin_app_tests(root)

    assert [target.name for target in targets] == ["a_project", "z_project"]


def test_build_pytest_command_uses_app_local_project_and_importlib_mode():
    command = builtin_app_tests.build_pytest_command()

    assert command[:10] == [
        "uv",
        "--no-cache",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        ".",
        "--with",
        "pytest",
        "--with",
    ]
    assert "pytest-asyncio" in command
    assert "--import-mode=importlib" in command
    assert command[-1] == "test"


def test_build_pytest_command_keeps_forwarded_args_after_separator():
    command = builtin_app_tests.build_pytest_command(["--", "-k", "weather"])

    assert command[-2:] == ["-k", "weather"]


def test_subprocess_env_uses_isolated_app_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("VIRTUAL_ENV", "/repo/.venv")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/repo/.venv-dev")
    monkeypatch.setenv("UV_PYTHON", "/polluted/project/.venv/bin/python")
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")
    monkeypatch.setenv("AGILAB_BUILTIN_APP_TEST_ENV_ROOT", str(tmp_path / "app-envs"))
    target = builtin_app_tests.BuiltinAppTestTarget(
        name="execution_pandas_project",
        path=tmp_path / "execution_pandas_project",
    )

    env = builtin_app_tests.subprocess_env(target)

    assert "VIRTUAL_ENV" not in env
    assert "UV_RUN_RECURSION_DEPTH" not in env
    assert env["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / "app-envs" / target.name)
    assert env["UV_PYTHON"] == sys.executable


def test_app_test_env_root_uses_temporary_directory_by_default(monkeypatch):
    monkeypatch.delenv("AGILAB_BUILTIN_APP_TEST_ENV_ROOT", raising=False)

    with builtin_app_tests.app_test_env_root() as env_root:
        assert env_root.name.startswith("agilab-builtin-app-tests-")
        assert env_root.exists()

    assert not env_root.exists()

def test_coverage_command_keeps_app_isolation_and_collects_parallel_data(tmp_path):
    module = builtin_app_tests
    data = tmp_path / "coverage.db"
    junit = tmp_path / "junit.xml"
    command = module.build_pytest_command(coverage_data_file=data, junit_path=junit)
    assert command[:2] == ["uv", "--no-cache"]
    assert command[command.index("--project") + 1] == "."
    assert "coverage" in command
    assert f"--source={module.REPO_ROOT / 'src/agilab'}" in command
    assert f"--data-file={data}" in command
    assert "--parallel-mode" in command
    assert f"--junitxml={junit}" in command
    assert command[command.index("python") + 1:command.index("python") + 4] == ["-m", "coverage", "run"]


@pytest.fixture
def sdk_sources(monkeypatch, tmp_path):
    root = tmp_path / "sdk-projects"
    versions = {
        "agi-env": "2026.10.04", "agi-node": "2026.10.05",
        "agi-cluster": "2026.10.10.1", "agi-core": "2026.10.10.1",
    }
    for name, version in versions.items():
        source = root / name
        source.mkdir(parents=True)
        (source / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "{version}"\n')
        (source / ".venv").mkdir()
        (source / ".venv" / "do-not-copy").write_text("ambient environment")
    monkeypatch.setattr(builtin_app_tests, "SDK_PROJECTS_ROOT", root)
    return root, versions


def _write_sdk_wheel(output, name, version, metadata=None):
    version = ".".join(str(int(part)) for part in version.split("."))
    stem = f'{name.replace("-", "_")}-{version}'
    wheel = output / f"{stem}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"{stem}.dist-info/METADATA",
            metadata if metadata is not None else f"Name: {name}\nVersion: {version}\n",
        )
    return wheel


@pytest.mark.parametrize("explicit_online_environment", [False, True])
def test_candidate_sdk_builds_are_owned_and_do_not_mutate_source(
    monkeypatch, tmp_path, sdk_sources, explicit_online_environment,
):
    sources, versions = sdk_sources
    originals = {path: path.read_bytes() for path in sources.glob("*/pyproject.toml")}
    calls = []
    monkeypatch.setenv("UV_FIND_LINKS", "/unrelated/wheels")
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_NO_INDEX", "1")
    build_environment = {"UV_INDEX_URL": "https://pypi.org/simple"}

    def build(command, *, check, env):
        assert check is True
        assert "UV_FIND_LINKS" not in env
        if explicit_online_environment:
            assert env == build_environment
        else:
            assert env["UV_OFFLINE"] == env["UV_NO_INDEX"] == "1"
        copied_source = Path(command[command.index("--wheel") + 1])
        assert copied_source.is_relative_to(tmp_path / "candidate")
        assert not (copied_source / ".venv").exists()
        assert copied_source != sources / copied_source.name
        (copied_source / "pyproject.toml").write_text("build backend writes stay in the copy")
        _write_sdk_wheel(Path(command[command.index("--out-dir") + 1]), copied_source.name, versions[copied_source.name])
        calls.append(command)

    monkeypatch.setattr(builtin_app_tests.subprocess, "run", build)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    if explicit_online_environment:
        wheels, actual_versions = builtin_app_tests.prepare_project_wheels(
            candidate, {name: sources / name for name in versions},
            build_environment=build_environment,
        )
    else:
        wheels, actual_versions = builtin_app_tests.prepare_sdk_wheels(candidate)

    assert actual_versions == versions
    assert len(calls) == len(list(wheels.glob("*.whl"))) == 4
    assert all(path.read_bytes() == original for path, original in originals.items())
    assert builtin_app_tests.os.environ["UV_FIND_LINKS"] == "/unrelated/wheels"


@pytest.mark.parametrize("default_source", ["missing", "decoy"])
def test_candidate_sdk_build_uses_explicit_source_root(monkeypatch, tmp_path, sdk_sources, default_source):
    sources, versions = sdk_sources
    originals = {path: path.read_bytes() for path in sources.glob("*/pyproject.toml")}
    unused_default = tmp_path / "unused-default-sdk"
    if default_source == "decoy":
        for name in versions:
            project = unused_default / name
            project.mkdir(parents=True)
            (project / "pyproject.toml").write_text(
                f'[project]\nname = "{name}"\nversion = "2000.1.1"\n'
            )
    monkeypatch.setattr(builtin_app_tests, "SDK_PROJECTS_ROOT", unused_default)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    built = []

    def build(command, *, check, env):
        assert check is True
        copied_source = Path(command[command.index("--wheel") + 1])
        assert copied_source.is_relative_to(candidate / "sources")
        assert (copied_source / "pyproject.toml").read_bytes() == originals[
            sources / copied_source.name / "pyproject.toml"
        ]
        (copied_source / "pyproject.toml").write_text("backend changes stay in the copy")
        _write_sdk_wheel(
            Path(command[command.index("--out-dir") + 1]),
            copied_source.name,
            versions[copied_source.name],
        )
        built.append(copied_source.name)

    monkeypatch.setattr(builtin_app_tests.subprocess, "run", build)
    wheels, actual_versions = builtin_app_tests.prepare_sdk_wheels(
        candidate, sdk_projects_root=sources
    )

    assert actual_versions == versions
    assert set(built) == set(versions)
    assert len(list(wheels.glob("*.whl"))) == 4
    assert all(path.read_bytes() == original for path, original in originals.items())


@pytest.mark.parametrize("bad_output", ["missing", "wrong-name", "wrong-version", "missing-version", "corrupt"])
def test_candidate_sdk_build_rejects_missing_or_bad_wheels(monkeypatch, tmp_path, sdk_sources, bad_output):
    _, versions = sdk_sources

    def build(command, **kwargs):
        output = Path(command[command.index("--out-dir") + 1])
        if bad_output == "missing":
            return
        if bad_output == "corrupt":
            (output / "agi_env-2026.10.4-py3-none-any.whl").write_bytes(b"invalid ZIP")
            return
        metadata = {
            "wrong-name": "Name: wrong-package\nVersion: 2026.10.4\n",
            "wrong-version": "Name: agi-env\nVersion: 2026.9.1\n",
            "missing-version": "Name: agi-env\n",
        }[bad_output]
        _write_sdk_wheel(output, "agi-env", versions["agi-env"], metadata)

    monkeypatch.setattr(builtin_app_tests.subprocess, "run", build)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        builtin_app_tests.prepare_sdk_wheels(candidate)


@pytest.mark.parametrize("actual", ["2026.10.5", "2026.10.11"])
def test_resolved_sdk_guard_rejects_older_or_newer_core_before_pytest(monkeypatch, actual):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: actual)
    monkeypatch.setattr(sys, "argv", ["-c", json.dumps({"agi-core": "2026.10.10.1"}), "-m", "pytest", "test"])
    monkeypatch.setattr(runpy, "run_module", lambda *args, **kwargs: pytest.fail("pytest must not start on the wrong SDK"))
    with pytest.raises(SystemExit, match="SDK candidate version mismatch"):
        exec(builtin_app_tests.SDK_VERSION_GUARD, {})


@pytest.mark.parametrize("instrumented", [False, True])
def test_resolved_sdk_guard_preserves_module_and_forwarded_arguments(monkeypatch, instrumented):
    forwarded = ["coverage", "run", "--parallel-mode", "-m", "pytest", "-k", "weather"] if instrumented else ["pytest", "-k", "weather"]
    versions = {"agi-env": "2026.10.04", "agi-core": "2026.10.10.1"}
    monkeypatch.setattr(importlib.metadata, "version", lambda name: versions[name].replace(".04", ".4"))
    monkeypatch.setattr(sys, "argv", ["-c", json.dumps(versions), "-m", *forwarded])
    calls = []
    monkeypatch.setattr(runpy, "run_module", lambda *args, **kwargs: calls.append((args, kwargs, sys.argv.copy())))

    exec(builtin_app_tests.SDK_VERSION_GUARD, {})

    assert calls == [((forwarded[0],), {"run_name": "__main__", "alter_sys": True}, forwarded)]


def test_main_prepares_sdk_once_and_scopes_find_links_to_apps(monkeypatch, tmp_path):
    module = builtin_app_tests
    targets = [module.BuiltinAppTestTarget(name, tmp_path / name) for name in ("a_project", "b_project")]
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "discover_builtin_app_tests", lambda: targets)
    preparation = []
    versions = {"agi-core": "2026.10.10.1"}
    calls = []
    monkeypatch.setenv("UV_FIND_LINKS", "/ambient/wheels")

    def prepare(root):
        preparation.append(root)
        return root / "wheels", versions

    def run(command, *, cwd, check, env):
        calls.append((command, cwd, env))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module, "prepare_sdk_wheels", prepare)
    monkeypatch.setattr(module.subprocess, "run", run)

    assert module.main([]) == 0
    assert len(preparation) == 1
    assert len(calls) == 2
    for command, cwd, env in calls:
        assert cwd in [target.path for target in targets]
        assert env["UV_FIND_LINKS"] == str(preparation[0] / "wheels")
        python_index = command.index("python")
        assert command[python_index + 1:python_index + 3] == ["-c", module.SDK_VERSION_GUARD]
        assert json.loads(command[python_index + 3]) == versions
    assert not preparation[0].exists()
    assert module.os.environ["UV_FIND_LINKS"] == "/ambient/wheels"


def test_main_does_not_run_tests_if_sdk_build_fails(monkeypatch, tmp_path):
    module = builtin_app_tests
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "discover_builtin_app_tests", lambda: [module.BuiltinAppTestTarget("a_project", tmp_path / "a_project")])
    monkeypatch.setattr(module, "prepare_sdk_wheels", lambda root: (_ for _ in ()).throw(subprocess.CalledProcessError(1, ["uv", "build"])))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: pytest.fail("pytest must not start after a failed build"))
    assert module.main([]) == 1


@pytest.mark.parametrize("args", [["--list"], ["--dry-run"]])
def test_inspection_does_not_build_sdk_candidates(monkeypatch, tmp_path, args):
    module = builtin_app_tests
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "discover_builtin_app_tests", lambda: [module.BuiltinAppTestTarget("a_project", tmp_path / "a_project")])
    monkeypatch.setattr(module, "prepare_sdk_wheels", lambda root: pytest.fail("inspection must not build SDK wheels"))
    assert module.main(args) == 0
