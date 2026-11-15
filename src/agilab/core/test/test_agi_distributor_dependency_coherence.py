"""Real offline resolver regressions for SDK overlays in app environments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import zipfile
from importlib.metadata import distributions
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from agi_cluster.agi_distributor import deployment_local_support as deployment


def _wheel(
    directory: Path, name: str, version: str, requirements=(), *, pth=None
) -> Path:
    normalized = name.replace("-", "_")
    wheel_name = f"{normalized}-{version}-py3-none-any.whl"
    info = f"{normalized}-{version}.dist-info"
    metadata = (
        f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n"
        + "".join(f"Requires-Dist: {requirement}\n" for requirement in requirements)
        + "\n"
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / wheel_name
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr(f"{info}/METADATA", metadata)
        wheel.writestr(
            f"{info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: coherence-test\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n",
        )
        entries = [f"{info}/METADATA", f"{info}/WHEEL", f"{info}/RECORD"]
        if pth is not None:
            wheel.writestr(f"{normalized}.pth", str(pth) + "\n")
            entries.append(f"{normalized}.pth")
        wheel.writestr(f"{info}/RECORD", "".join(f"{entry},,\n" for entry in entries))
    return path


def _editable_project(path: Path, name: str, requirements: list[str]) -> Path:
    path.mkdir(parents=True)
    (path / "src").mkdir()
    (path / "src" / f"{name.replace('-', '_')}.py").write_text(
        "VALUE = 'authored source'\n", encoding="utf-8"
    )
    (path / "pyproject.toml").write_text(
        '[build-system]\nrequires = []\nbuild-backend = "coherence_backend"\n'
        'backend-path = ["."]\n[project]\n'
        f"name = {json.dumps(name)}\nversion = '2.0'\n"
        f"dependencies = {json.dumps(requirements)}\n"
        'description = "Dépendances du projet"\n',
        encoding="utf-8",
    )
    wheel = _wheel(path / "wheel", name, "2.0", requirements, pth=path / "src")
    (path / "coherence_backend.py").write_text(
        "import shutil\nfrom pathlib import Path\n"
        f"WHEEL = Path({str(wheel)!r})\n"
        "def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):\n"
        "    shutil.copyfile(WHEEL, Path(wheel_directory) / WHEEL.name)\n"
        "    return WHEEL.name\n"
        "build_editable = build_wheel\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def resolver_fixture(tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("real resolver regression requires uv")
    wheels = tmp_path / "local wheels"
    for name in ("polars", "pydantic"):
        for version in ("1.0", "2.0"):
            _wheel(wheels, name, version)
    _wheel(wheels, "legacy-cgi", "2.6.4")
    _wheel(wheels, "standard-imghdr", "3.13.0")
    root_requirements = [
        "legacy-cgi>=2.6.4,<3; python_version >= '3.13'",
        "standard-imghdr>=3.13,<4; python_version >= '3.13'",
    ]
    sdk_requirements = {
        "agilab": root_requirements,
        "agi-env": ["pydantic>=1,<3"],
        "agi-node": ["polars>=1,<3", "agi-env==2.0"],
    }
    refs = [
        _wheel(wheels, name, "2.0", requirements)
        for name, requirements in sdk_requirements.items()
    ]
    app = _editable_project(
        tmp_path / "authored app é",
        "coherence-app",
        ["polars>=1,<2", "pydantic>=1,<2"],
    )
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("UV_", "PIP_")) and key != "VIRTUAL_ENV"
    }
    clean_env.update(
        UV_CACHE_DIR=str(tmp_path / "resolver-cache"),
        UV_PYTHON_DOWNLOADS="never",
        UV_NO_INDEX="1",
        UV_FIND_LINKS=str(wheels),
        PYTHONDONTWRITEBYTECODE="1",
    )
    commands: list[str] = []

    def run(argv, *, check=True, cwd=tmp_path):
        argv = [str(arg) for arg in argv]
        # Index environment variables differ between pip and uv. Make isolation
        # explicit on every real invocation, including helper-generated commands.
        is_install = argv[1:3] == ["pip", "install"]
        argv = [
            argv[0],
            "--offline",
            "--no-config",
            "--cache-dir",
            str(tmp_path / "resolver-cache"),
            *argv[1:],
        ]
        if is_install:
            argv.extend(["--no-index", "--find-links", str(wheels)])
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=clean_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        with (tmp_path / "agilab-sdk-resolver-command-evidence.jsonl").open(
            "a", encoding="utf-8"
        ) as evidence:
            evidence.write(
                json.dumps(
                    {
                        "command": argv,
                        "cwd": str(cwd),
                        "returncode": result.returncode,
                        "output": result.stdout,
                    }
                )
                + "\n"
            )
        if check and result.returncode:
            raise RuntimeError(result.stdout)
        return result

    async def run_fn(command, project):
        commands.append(command)
        run(shlex.split(command), cwd=project)

    return {
        "uv": uv,
        "env": clean_env,
        "wheels": wheels,
        "refs": refs,
        "app": app,
        "root": tmp_path,
        "sdk_requirements": sdk_requirements,
        "run": run,
        "run_fn": run_fn,
        "commands": commands,
        "wheel_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in refs
        },
    }


def _role(fixture, role: str, python_version: str) -> Path:
    if f"{sys.version_info.major}.{sys.version_info.minor}" == python_version:
        python = sys.executable
    else:
        result = fixture["run"](
            [fixture["uv"], "python", "find", "--no-python-downloads", python_version],
            check=False,
        )
        if result.returncode:
            pytest.skip(
                f"target Python {python_version} is not installed; downloads disabled"
            )
        python = result.stdout.strip()
    role_path = fixture["root"] / f"role {role} {python_version}"
    role_path.mkdir()
    (role_path / "pyproject.toml").write_text(
        "[project]\nname = 'coherence-role'\nversion = '1.0'\n"
        "dependencies = ['polars>=1,<2', 'pydantic>=1,<2']\n"
        "# Authored UTF-8: rôle de calcul\n",
        encoding="utf-8",
    )
    fixture["run"]([fixture["uv"], "venv", "--python", python, role_path / ".venv"])
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "install",
            "--python",
            deployment._project_venv_python(role_path),
            "-e",
            fixture["app"],
        ]
    )
    return role_path


def _installed(role):
    python = deployment._project_venv_python(role)
    result = subprocess.run(
        [
            str(python),
            "-B",
            "-c",
            "import json,sysconfig;print(json.dumps(sysconfig.get_paths()))",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    site = json.loads(result.stdout)["purelib"]
    return {
        dist.metadata["Name"].lower().replace("_", "-"): dist
        for dist in distributions(path=[site])
    }


def _refresh(
    fixture,
    role_path,
    *,
    refs=None,
    editable=False,
    requirements_options="",
    requirements_file=None,
):
    asyncio.run(
        deployment._install_many_into_project_venv(
            shlex.quote(fixture["uv"]),
            role_path,
            fixture["refs"] if refs is None else refs,
            run_fn=fixture["run_fn"],
            no_deps=False,
            editable=editable,
            requirements_file=requirements_file or role_path / "pyproject.toml",
            requirements_options=requirements_options,
            editable_refs=(fixture["app"],),
        )
    )


@pytest.mark.parametrize("role", ["manager", "worker"])
@pytest.mark.parametrize("python_version", ["3.12", "3.13"])
def test_sdk_refresh_resolves_app_intersection_and_target_markers(
    resolver_fixture, role, python_version
):
    fixture = resolver_fixture
    role_path = _role(fixture, role, python_version)
    authored = {
        p: p.read_bytes()
        for p in (role_path / "pyproject.toml", fixture["app"] / "pyproject.toml")
    }

    _refresh(fixture, role_path)

    installed = _installed(role_path)
    assert installed["polars"].version == "1.0"
    assert installed["pydantic"].version == "1.0"
    for name in ("agilab", "agi-env", "agi-node"):
        assert installed[name].version == "2.0"
        source = json.loads(installed[name].read_text("direct_url.json"))
        expected = next(
            p
            for p in fixture["refs"]
            if p.name.startswith(name.replace("-", "_") + "-")
        )
        assert source["url"] == expected.as_uri()
        assert (
            hashlib.sha256(expected.read_bytes()).hexdigest()
            == fixture["wheel_hashes"][expected.name]
        )
    for name in ("legacy-cgi", "standard-imghdr"):
        assert (name in installed) == (python_version == "3.13")
    source = json.loads(installed["coherence-app"].read_text("direct_url.json"))
    assert source["dir_info"]["editable"] is True
    assert source["url"] == fixture["app"].as_uri()
    assert all(p.read_bytes() == content for p, content in authored.items())
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(role_path),
        ]
    )


@pytest.mark.parametrize("role", ["manager", "worker"])
def test_contradictory_app_and_sdk_fail_without_installing_incoherent_versions(
    resolver_fixture, role
):
    fixture = resolver_fixture
    role_path = _role(fixture, role, "3.13")
    bad = _wheel(fixture["wheels"], "agi-node", "3.0", ["polars>=2,<3", "agi-env==2.0"])
    with pytest.raises(
        RuntimeError, match="(?i)(dependenc|requirements|unsatisfiable)"
    ):
        _refresh(fixture, role_path, refs=[*fixture["refs"][:-1], bad])
    installed = _installed(role_path)
    assert installed["polars"].version == "1.0"
    assert installed["pydantic"].version == "1.0"
    assert "agi-node" not in installed
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(role_path),
        ]
    )


def test_source_editables_keep_identity_and_changed_app_requirements_are_resolved(
    resolver_fixture,
):
    fixture = resolver_fixture
    role_path = _role(fixture, "worker", "3.13")
    projects = [
        _editable_project(fixture["root"] / name, name, requirements)
        for name, requirements in fixture["sdk_requirements"].items()
    ]
    authored = {
        p / "pyproject.toml": (p / "pyproject.toml").read_bytes() for p in projects
    }

    _refresh(fixture, role_path, refs=projects, editable=True)
    installed = _installed(role_path)
    for project in projects:
        source = json.loads(installed[project.name].read_text("direct_url.json"))
        assert source["dir_info"]["editable"] is True
        assert source["url"] == project.as_uri()
    assert all(p.read_bytes() == content for p, content in authored.items())
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(role_path),
        ]
    )
    manifest = role_path / "pyproject.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("polars>=1,<2", "polars>=3,<4"),
        encoding="utf-8",
    )
    with pytest.raises(
        RuntimeError, match="(?i)(dependenc|requirements|unsatisfiable)"
    ):
        _refresh(fixture, role_path, refs=projects, editable=True)


def test_dependency_requirements_cannot_be_silently_ignored(tmp_path):
    async def unexpected_run(*_):
        pytest.fail("an incoherent no-deps resolver request must fail before mutation")

    with pytest.raises(ValueError, match="dependenc"):
        asyncio.run(
            deployment._install_many_into_project_venv(
                "uv",
                tmp_path,
                ["agi-env"],
                run_fn=unexpected_run,
                requirements_file=tmp_path / "pyproject.toml",
            )
        )


def test_authored_uv_source_and_marker_are_resolved_without_rewriting(resolver_fixture):
    fixture = resolver_fixture
    project = _role(fixture, "worker", "3.13")
    local = _editable_project(
        fixture["root"] / "local dependency é", "coherence-local", []
    )
    manifest = project / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8").replace(
        "'pydantic>=1,<2']",
        "'pydantic>=1,<2', 'coherence-local==2.0; python_version >= \"3.13\"']",
    )
    text += (
        "\n[tool.uv.sources]\ncoherence-local = {path = "
        + json.dumps(os.path.relpath(local, project))
        + ", editable = true}\n"
    )
    manifest.write_text(text, encoding="utf-8")

    _refresh(fixture, project)

    source = json.loads(
        _installed(project)["coherence-local"].read_text("direct_url.json")
    )
    assert source["url"] == local.as_uri()
    assert source["dir_info"]["editable"] is True
    assert manifest.read_text(encoding="utf-8") == text
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(project),
        ]
    )


@pytest.mark.parametrize(
    ("options", "expected_version"),
    [
        ("--extra tight", "1.0"),
        ("--extra=tight", "1.0"),
        ("--all-extras", "1.0"),
        ("--all-extras --no-extra=tight", "1.5"),
    ],
)
def test_selected_role_extras_are_part_of_sdk_resolution(
    resolver_fixture, options, expected_version
):
    fixture = resolver_fixture
    _wheel(fixture["wheels"], "pydantic", "1.5")
    project = _role(fixture, "worker", "3.13")
    manifest = project / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8")
    text += "\n[project.optional-dependencies]\ntight = ['pydantic<1.5']\n"
    manifest.write_text(text, encoding="utf-8")

    _refresh(fixture, project, requirements_options=options)

    assert _installed(project)["pydantic"].version == expected_version
    assert manifest.read_text(encoding="utf-8") == text
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(project),
        ]
    )


@pytest.mark.parametrize(
    ("defaults", "options", "expected_version"),
    [
        (None, "", "1.0"),
        (None, "--no-dev", "1.5"),
        (None, "--no-default-groups", "1.5"),
        (None, "--no-default-groups --group tight-group", "1.0"),
        (None, "--no-default-groups --group=tight-group", "1.0"),
        (None, "--all-groups --no-group dev --no-group tight-group", "1.5"),
        (None, "--all-groups --no-group dev", "1.0"),
        (None, "--only-group tight-group", "1.0"),
        (None, "--only-group wide", "1.5"),
        (["wide"], "", "1.5"),
        (["tight-group"], "", "1.0"),
        ("all", "--no-group dev --no-group tight-group", "1.5"),
    ],
)
def test_effective_group_selection_survives_sdk_refresh(
    resolver_fixture, defaults, options, expected_version
):
    fixture = resolver_fixture
    _wheel(fixture["wheels"], "pydantic", "1.5")
    project = _role(fixture, "worker", "3.13")
    manifest = project / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8")
    text += (
        "\n[dependency-groups]\ndev = ['pydantic<1.5']\n"
        "Tight_Group = ['pydantic<1.5']\nwide = []\n"
    )
    if defaults is not None:
        text += "\n[tool.uv]\ndefault-groups = " + json.dumps(defaults) + "\n"
    manifest.write_text(text, encoding="utf-8")
    fixture["run"](
        [
            fixture["uv"],
            "sync",
            "--project",
            project,
            "--no-install-project",
            "--no-index",
            "--find-links",
            fixture["wheels"],
            *shlex.split(options),
        ]
    )
    if expected_version == "1.0":
        assert _installed(project)["pydantic"].version == "1.0"

    _refresh(fixture, project, requirements_options=options)

    assert _installed(project)["pydantic"].version == expected_version
    assert manifest.read_text(encoding="utf-8") == text
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(project),
        ]
    )


def test_selected_group_selection_conflict_fails_closed(resolver_fixture):
    fixture = resolver_fixture
    _wheel(fixture["wheels"], "pydantic", "1.5")
    project = _role(fixture, "worker", "3.13")
    manifest = project / "pyproject.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "\n[dependency-groups]\ntight = ['pydantic<1.5']\n",
        encoding="utf-8",
    )
    fixture["run"](
        [
            fixture["uv"],
            "sync",
            "--project",
            project,
            "--group",
            "tight",
            "--no-install-project",
            "--no-index",
            "--find-links",
            fixture["wheels"],
        ]
    )
    bad = _wheel(fixture["wheels"], "agi-env", "2.1", ["pydantic>=1.5,<2"])
    with pytest.raises(
        RuntimeError, match="(?i)(dependenc|requirements|unsatisfiable)"
    ):
        _refresh(fixture, project, refs=[bad], requirements_options="--group tight")
    assert _installed(project)["pydantic"].version == "1.0"
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(project),
        ]
    )


def test_canonical_extra_exclusion_matches_real_uv(resolver_fixture):
    fixture = resolver_fixture
    _wheel(fixture["wheels"], "pydantic", "1.5")
    _wheel(fixture["wheels"], "coherence-extra-token", "1.0")
    project = _role(fixture, "worker", "3.13")
    manifest = project / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8")
    text += "\n[project.optional-dependencies]\nTight_Feature = ['pydantic<1.5', 'coherence-extra-token']\n"
    manifest.write_text(text, encoding="utf-8")
    options = "--all-extras --no-extra tight-feature"
    fixture["run"](
        [
            fixture["uv"],
            "sync",
            "--project",
            project,
            "--no-install-project",
            "--no-index",
            "--find-links",
            fixture["wheels"],
            *shlex.split(options),
        ]
    )
    # uv locks all extras together, so the cap can constrain the lock even
    # when excluded. The marker package proves the selected install behavior.
    assert "coherence-extra-token" not in _installed(project)

    _refresh(fixture, project, requirements_options=options)

    assert _installed(project)["pydantic"].version == "1.5"
    assert "coherence-extra-token" not in _installed(project)
    assert manifest.read_text(encoding="utf-8") == text
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(project),
        ]
    )


@pytest.mark.parametrize("kind", ["nested", "legacy"])
def test_nested_and_legacy_group_selection_uses_uv(resolver_fixture, kind):
    fixture = resolver_fixture
    _wheel(fixture["wheels"], "pydantic", "1.5")
    project = _role(fixture, "worker", "3.13")
    manifest = project / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8")
    if kind == "legacy":
        text += "\n[tool.uv]\ndev-dependencies = ['pydantic<1.5']\n"
        options = ""
    else:
        text += (
            "\n[dependency-groups]\ncap = ['pydantic<1.5']\n"
            "tight = [{include-group = 'cap'}]\n"
        )
        options = "--no-default-groups --group tight"
    manifest.write_text(text, encoding="utf-8")
    fixture["run"](
        [
            fixture["uv"],
            "sync",
            "--project",
            project,
            "--no-install-project",
            "--no-index",
            "--find-links",
            fixture["wheels"],
            *shlex.split(options),
        ]
    )
    assert _installed(project)["pydantic"].version == "1.0"

    _refresh(fixture, project, requirements_options=options)

    assert _installed(project)["pydantic"].version == "1.0"
    assert manifest.read_text(encoding="utf-8") == text
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(project),
        ]
    )


@pytest.mark.parametrize(
    "options",
    [
        "--all-extras --no-extra tight-feature",
        "--all-extras --no-extra=TIGHT.FEATURE",
        "--extra Tight_Feature --no-extra=tight-feature",
        "--extra=TIGHT...FEATURE --no-extra tight_feature",
    ],
)
def test_extra_selection_normalizes_both_sides(tmp_path, options):
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text(
        "[project.optional-dependencies]\nTight_Feature = ['pydantic<1.5']\n",
        encoding="utf-8",
    )
    assert shlex.split(deployment._requirements_selection_args(manifest, options)) == []


@pytest.mark.parametrize(
    "options", ["--extra", "--extra=", "--group", "--no-group --dev"]
)
def test_selection_requires_a_name_before_resolving(tmp_path, options):
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text("[project]\nname='selection-test'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="requires a dependency"):
        deployment._requirements_selection_args(manifest, options)


def test_manager_effective_overlay_keeps_sdk_and_unrelated_sources(resolver_fixture):
    fixture = resolver_fixture
    project = _role(fixture, "manager", "3.13")
    sdk_projects = {
        name: _editable_project(
            fixture["root"] / f"selected {name}",
            name,
            fixture["sdk_requirements"][name],
        )
        for name in ("agi-env", "agi-node")
    }
    local = _editable_project(
        fixture["root"] / "authored local é", "coherence-local", []
    )
    manifest = project / "pyproject.toml"
    text = manifest.read_text(encoding="utf-8").replace(
        "'pydantic>=1,<2']",
        "'pydantic>=1,<2', 'agi-env==2.0', 'agi-node==2.0', 'coherence-local==2.0']",
    )
    text += (
        "\n[tool.uv.sources]\n"
        "agi-env = {git = 'https://unavailable.invalid/sdk.git'}\n"
        "agi-node = {url = 'https://unavailable.invalid/agi_node-2.0-py3-none-any.whl'}\n"
        "coherence-local = {path = "
        + json.dumps(os.path.relpath(local, project))
        + ", editable = true}\n"
    )
    manifest.write_text(text, encoding="utf-8")
    refs = [fixture["refs"][0], *sdk_projects.values()]
    fixture["env"]["UV_PROJECT_ENVIRONMENT"] = str(project / ".venv")
    authored = {
        path: path.read_bytes()
        for path in [
            manifest,
            local / "pyproject.toml",
            *(p / "pyproject.toml" for p in sdk_projects.values()),
        ]
    }
    with TemporaryDirectory(
        dir=fixture["root"], prefix="effective-manager-"
    ) as staging:
        overlay = deployment._write_manager_sync_overlay(
            manifest,
            Path(staging),
            local_core_sources=deployment._manager_overlay_core_sources(
                manifest, sdk_projects
            ),
        )
        fixture["run"](
            [
                fixture["uv"],
                "sync",
                "--project",
                overlay,
                "--no-install-project",
                "--no-index",
                "--find-links",
                fixture["wheels"],
            ]
        )
        with pytest.raises(RuntimeError) as negative:
            _refresh(fixture, project, refs=refs)
        (
            fixture["root"] / "agilab-sdk-original-manager-source-negative.log"
        ).write_text(
            str(negative.value) + "\n" + str(negative.value.__cause__), encoding="utf-8"
        )

        _refresh(
            fixture, project, refs=refs, requirements_file=overlay / "pyproject.toml"
        )

        installed = _installed(project)
        for name, source_path in {**sdk_projects, "coherence-local": local}.items():
            source = json.loads(installed[name].read_text("direct_url.json"))
            assert source["url"] == source_path.as_uri()
            assert installed[name].version == "2.0"
        assert (
            json.loads(installed["coherence-local"].read_text("direct_url.json"))[
                "dir_info"
            ]["editable"]
            is True
        )
        fixture["run"](
            [
                fixture["uv"],
                "pip",
                "check",
                "--python",
                deployment._project_venv_python(project),
            ]
        )
    assert not overlay.exists()
    assert all(path.read_bytes() == content for path, content in authored.items())


@pytest.mark.parametrize("options", ["--dev", "--only-dev"])
@pytest.mark.parametrize("custom_default", [False, True])
def test_missing_dev_group_matches_project_sync(
    resolver_fixture, options, custom_default
):
    fixture = resolver_fixture
    _wheel(fixture["wheels"], "pydantic", "1.5")
    project = _role(fixture, "worker", "3.13")
    manifest = project / "pyproject.toml"
    if custom_default:
        manifest.write_text(
            manifest.read_text(encoding="utf-8")
            + "\n[dependency-groups]\ntight=['pydantic<1.5']\n[tool.uv]\ndefault-groups=['tight']\n",
            encoding="utf-8",
        )
    fixture["run"](
        [
            fixture["uv"],
            "sync",
            "--project",
            project,
            "--no-install-project",
            "--no-index",
            "--find-links",
            fixture["wheels"],
            options,
        ]
    )

    _refresh(fixture, project, requirements_options=options)

    expected = "1.0" if custom_default and options == "--dev" else "1.5"
    assert _installed(project)["pydantic"].version == expected
    fixture["run"](
        [
            fixture["uv"],
            "pip",
            "check",
            "--python",
            deployment._project_venv_python(project),
        ]
    )


def test_remote_prefix_selects_reviewed_sdk_index_and_private_cache(resolver_fixture):
    from agi_cluster.agi_distributor import deployment_remote_support as remote
    fixture = resolver_fixture
    project = _role(fixture, "worker", "3.13")
    manifest = project / "pyproject.toml"
    authored = manifest.read_text(encoding="utf-8").replace(
        "'pydantic>=1,<2']",
        "'pydantic>=1,<2', 'agilab==2.0', 'agi-env==2.0', 'agi-node==2.0']",
    )
    manifest.write_text(authored, encoding="utf-8")
    index = fixture["root"] / "reviewed SDK index"
    for wheel in sorted(fixture["wheels"].glob("*.whl")):
        name = wheel.name.split("-", 1)[0].replace("_", "-")
        page = index / name / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        with page.open("a", encoding="utf-8") as handle:
            handle.write(f'<a href="{wheel.as_uri()}#sha256={digest}">{wheel.name}</a>\n')
    cache = fixture["root"] / "selected remote cache"
    selected = {"UV_DEFAULT_INDEX": index.as_uri(), "UV_CACHE_DIR": str(cache)}
    prefix = shlex.join(["env", *(f"{key}={value}" for key, value in selected.items())])
    tool = remote._remote_tool(prefix, shlex.join([fixture["uv"], "--offline", "--no-config"]))
    command = remote._remote_command(tool, "sync", "--project", project, "--no-install-project")
    environment = dict(fixture["env"])
    environment.pop("UV_NO_INDEX", None)
    environment.pop("UV_FIND_LINKS", None)
    argv = shlex.split(command)
    if os.name == "nt":
        # This local harness has no POSIX env executable; the remote command
        # contract remains POSIX, and its selected values are applied directly.
        environment.update(selected)
        argv = argv[1 + len(selected):]
    result = subprocess.run(argv, cwd=project, env=environment, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (fixture["root"] / "agilab-sdk-reviewed-index-command.log").write_text(
        command + "\n" + result.stdout, encoding="utf-8"
    )
    assert result.returncode == 0, result.stdout
    assert cache.is_dir() and any(cache.iterdir())
    installed = _installed(project)
    lock = (project / "uv.lock").read_text(encoding="utf-8")
    for wheel in fixture["refs"]:
        name = wheel.name.split("-", 1)[0].replace("_", "-")
        assert installed[name].version == "2.0"
        assert "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest() in lock
    assert installed["pydantic"].version == "1.0"
    assert installed["polars"].version == "1.0"
    assert manifest.read_text(encoding="utf-8") == authored
    fixture["run"](
        [fixture["uv"], "pip", "check", "--python", deployment._project_venv_python(project)]
    )
