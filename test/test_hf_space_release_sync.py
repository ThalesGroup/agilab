from __future__ import annotations

import importlib.util
import fnmatch
import io
import hashlib
import json
import shutil
import subprocess
import sys
import types
import os
from pathlib import Path
import tomllib
from zipfile import ZipFile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "hf_space_release_sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("hf_space_release_sync_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_stage_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for app in (
        "flight_telemetry_project",
        "weather_forecast_project",
        "pytorch_playground_project",
    ):
        (repo / "src/agilab/apps/builtin" / app).mkdir(parents=True)
    (repo / "src/agilab/apps/private_project").mkdir(parents=True)
    for page in ("view_maps", "view_forecast_analysis", "view_release_decision"):
        (repo / "src/agilab/apps-pages" / page).mkdir(parents=True)
    (repo / "docker").mkdir()
    (repo / "src/agilab/main_page.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "src/agilab/apps/private_project/secret.txt").write_text(
        "private\n", encoding="utf-8"
    )
    (repo / "pyproject.toml").write_text("[project]\nname='agilab'\n", encoding="utf-8")
    (repo / "uv_config.toml").write_text("", encoding="utf-8")
    (repo / "docker/install.sh").write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    return repo


def test_runtime_url_matches_hf_space_subdomain() -> None:
    module = _load_module()

    assert module.runtime_url_for_space("jpmorard/agilab") == "https://jpmorard-agilab.hf.space"
    assert module.runtime_url_for_space("team-name/agilab-demo") == "https://team-name-agilab-demo.hf.space"


def _load_notebook_exporter():
    spec = importlib.util.spec_from_file_location("hf_notebook_demo_export", REPO_ROOT / "tools/demos/hf_notebook_demo_export.py")
    assert spec and spec.loader
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    return exporter


def test_notebook_demo_export_is_allowlisted_and_hash_verified(tmp_path: Path) -> None:
    exporter = _load_notebook_exporter()
    destination = tmp_path / "space"
    report = exporter.export(destination)
    expected = set(exporter.PUBLIC_SOURCE_FILES) | set(exporter.GENERATED_FILES) | {"PUBLIC_HASHES.json"}
    assert set(report["files"]) == expected == set(report["sha256"])
    assert {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()} == expected
    for name, digest in report["sha256"].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
    assert (destination / "LICENSE").read_bytes() == (REPO_ROOT / "LICENSE").read_bytes()
    assert "sdk: docker" in (destination / "README.md").read_text()
    dockerfile = (destination / "Dockerfile").read_text()
    assert "PYTHONPATH=/app/src" in dockerfile
    assert f"cd /app/{exporter.RESOURCE_PATH} && python /app/src/agilab/agent_runtime/notebook_verifier.py" in dockerfile


def test_notebook_demo_export_smoke_verifies_and_runs_staged_app(tmp_path: Path) -> None:
    exporter = _load_notebook_exporter()
    destination = tmp_path / "space"
    exporter.export(destination)
    env = {**os.environ, "PYTHONPATH": str(destination / "src")}
    result = subprocess.run([sys.executable, str(destination / "src/agilab/agent_runtime/notebook_verifier.py")], cwd=destination / exporter.RESOURCE_PATH, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["status"] == "passed"
    code = """
from pathlib import Path
from agi_web.testing import AppTest
from agilab.demos import notebook_showcase
assert Path(notebook_showcase.__file__).resolve().is_relative_to(Path.cwd())
app = AppTest.from_file('hf_app.py', default_timeout=30).run()
assert not app.exception, app.exception
assert any(title.value == 'Iris decision lab' for title in app.title)
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=destination, env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


def test_notebook_demo_export_preserves_nonempty_destination(tmp_path: Path) -> None:
    exporter = _load_notebook_exporter()
    destination = tmp_path / "space"
    destination.mkdir()
    (destination / "keep").write_text("x")
    with pytest.raises(ValueError, match="new or empty"):
        exporter.export(destination)
    assert (destination / "keep").read_text() == "x"


@pytest.mark.parametrize("tamper", ["app", "missing_hashes", "failed_report"])
def test_notebook_demo_export_rejects_unverified_sources(tmp_path: Path, tamper: str) -> None:
    exporter = _load_notebook_exporter()
    source_root = tmp_path / "source"
    for name in exporter.SOURCE_FILES:
        target = source_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / name, target)
    resources = source_root / exporter.RESOURCE_PATH
    if tamper == "app":
        (resources / "app.py").write_text("tampered")
    else:
        report_path = resources / "result.json"
        report = json.loads(report_path.read_text())
        report["files" if tamper == "missing_hashes" else "status"] = {} if tamper == "missing_hashes" else "failed"
        report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Demo artifact changed|complete verified demo report"):
        exporter.export(tmp_path / "space", source_root=source_root)
    assert not (tmp_path / "space").exists()


def test_parse_upload_commit_url() -> None:
    module = _load_module()

    assert module.parse_commit_sha(
        "url=https://huggingface.co/spaces/jpmorard/agilab/commit/"
        "0123456789abcdef0123456789abcdef01234567"
    ) == "0123456789abcdef0123456789abcdef01234567"


def test_run_command_accepts_hf_cli_click_exit_zero(monkeypatch) -> None:
    module = _load_module()
    output = (
        "✓ Uploaded\n"
        "  url: https://huggingface.co/spaces/jpmorard/agilab/commit/"
        "0123456789abcdef0123456789abcdef01234567\n"
        "click.exceptions.Exit: 0\n"
    )

    def _run(*_args, **_kwargs):
        return subprocess.CompletedProcess(["hf", "upload"], 1, output)

    monkeypatch.setattr(module.subprocess, "run", _run)

    assert module.run_command(["hf", "upload", "jpmorard/agilab"]) == output


def test_run_command_rejects_non_hf_failures(monkeypatch) -> None:
    module = _load_module()

    def _run(*_args, **_kwargs):
        return subprocess.CompletedProcess(["python", "--version"], 1, "click.exceptions.Exit: 0\n")

    monkeypatch.setattr(module.subprocess, "run", _run)

    try:
        module.run_command(["python", "--version"])
    except RuntimeError as exc:
        assert "command failed with exit 1" in str(exc)
    else:
        raise AssertionError("non-HF failures must not be treated as successful")


def test_set_space_visibility_uses_current_hf_api(monkeypatch) -> None:
    module = _load_module()
    calls: list[dict[str, object]] = []

    class _Api:
        def update_repo_settings(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        types.SimpleNamespace(HfApi=lambda: _Api()),
    )

    module.set_space_visibility("jpmorard/agilab", token="hf-token", private=False)

    assert calls == [
        {
            "repo_id": "jpmorard/agilab",
            "private": False,
            "repo_type": "space",
            "token": "hf-token",
        }
    ]


def test_set_space_visibility_falls_back_to_legacy_hf_api(monkeypatch) -> None:
    module = _load_module()
    calls: list[dict[str, object]] = []

    class _Api:
        def update_repo_visibility(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        types.SimpleNamespace(HfApi=lambda: _Api()),
    )

    module.set_space_visibility("jpmorard/agilab", token="hf-token", private=True)

    assert calls == [
        {
            "repo_id": "jpmorard/agilab",
            "private": True,
            "repo_type": "space",
            "token": "hf-token",
        }
    ]


def test_upload_space_updates_existing_repo_without_create(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "current_space_sha", lambda *_args, **_kwargs: "b" * 40)
    calls: list[dict[str, object]] = []
    visibility: list[tuple[str, str, bool]] = []

    class _Commit:
        oid = "0123456789abcdef0123456789abcdef01234567"

    class _Api:
        def upload_folder(self, **kwargs):
            calls.append(kwargs)
            return _Commit()

    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        types.SimpleNamespace(HfApi=lambda: _Api()),
    )
    monkeypatch.setattr(
        module,
        "set_space_visibility",
        lambda space_id, *, token, private: visibility.append((space_id, token, private)),
    )
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO((module.GRAPHVIZ_LFS_RULE + "\n").encode()),
    )

    commit = module.upload_space(
        tmp_path,
        space_id="jpmorard/agilab",
        token="hf-token",
        private=False,
    )

    assert commit == "0123456789abcdef0123456789abcdef01234567"
    assert calls == [
        {
            "repo_id": "jpmorard/agilab",
            "folder_path": tmp_path,
            "repo_type": "space",
            "token": "hf-token",
            "commit_message": calls[0]["commit_message"],
            "delete_patterns": [
                "src/agilab/apps/builtin/**",
                "src/agilab/apps-pages/**",
                "src/agilab/pages/**",
                "src/.DS_Store",
                "src/.coverage*",
                "src/**/.DS_Store",
                "src/**/.coverage*",
            ],
            "ignore_patterns": [
                ".gitattributes",
                "**/.venv/**",
                "**/__pycache__/**",
                "**/*.pyc",
            ],
        }
    ]
    assert str(calls[0]["commit_message"]).startswith("chore: deploy AGILAB release Space (")
    assert visibility == [("jpmorard/agilab", "hf-token", False)]


@pytest.mark.parametrize("existing", [b"", b"*.bin filter=lfs diff=lfs merge=lfs -text\n", b"# Custom rule\r\n*.png binary"])
def test_graphviz_lfs_registration_preserves_existing_attributes(monkeypatch, tmp_path: Path, existing: bytes) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "current_space_sha", lambda *_args, **_kwargs: "b" * 40)
    operations = []

    class _Api:
        def upload_file(self, **kwargs):
            operations.append(("attributes", kwargs))

        def upload_folder(self, **kwargs):
            assert operations[0][0] == "attributes"
            assert (tmp_path / ".gitattributes").read_bytes() == operations[0][1]["path_or_fileobj"]
            operations.append(("folder", kwargs))
            return types.SimpleNamespace(oid="a" * 40)

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(HfApi=lambda: _Api()))
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(existing))
    monkeypatch.setattr(module, "set_space_visibility", lambda *_args, **_kwargs: None)
    assert module.upload_space(tmp_path, space_id="owner/space", token="test-token", private=False) == "a" * 40
    separator = b"\n" if existing and not existing.endswith(b"\n") else b""
    expected = existing + separator + module.GRAPHVIZ_LFS_RULE.encode() + b"\n"
    assert (tmp_path / ".gitattributes").read_bytes() == expected
    assert [name for name, _kwargs in operations] == ["attributes", "folder"]
    assert operations[0][1]["path_in_repo"] == ".gitattributes"
    assert operations[0][1]["parent_commit"] == "b" * 40
    assert ".gitattributes" in operations[1][1]["ignore_patterns"]


def test_graphviz_lfs_registration_does_not_rewrite_an_existing_rule(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "current_space_sha", lambda *_args, **_kwargs: "b" * 40)
    existing = b"# Custom leading rule\r\n" + module.GRAPHVIZ_LFS_RULE.encode() + b"\r\n# Custom trailing rule"
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(existing))
    module.prepare_space_gitattributes(tmp_path, api=object(), space_id="owner/space", token="test-token")
    assert (tmp_path / ".gitattributes").read_bytes() == existing


def test_graphviz_lfs_registration_handles_a_space_without_attributes(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "current_space_sha", lambda *_args, **_kwargs: "b" * 40)
    calls = []

    def missing(*_args, **_kwargs):
        raise module.urllib.error.HTTPError("https://huggingface.co/space", 404, "missing", None, None)

    monkeypatch.setattr(module.urllib.request, "urlopen", missing)
    api = types.SimpleNamespace(upload_file=lambda **kwargs: calls.append(kwargs))
    module.prepare_space_gitattributes(tmp_path, api=api, space_id="owner/space", token="test-token")
    assert calls[0]["path_or_fileobj"] == (module.GRAPHVIZ_LFS_RULE + "\n").encode()
    assert (tmp_path / ".gitattributes").read_bytes() == calls[0]["path_or_fileobj"]


@pytest.mark.parametrize("status", [401, 403, 500])
def test_graphviz_lfs_registration_fails_closed_on_remote_errors(monkeypatch, tmp_path: Path, status: int) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "current_space_sha", lambda *_args, **_kwargs: "b" * 40)

    def fail(*_args, **_kwargs):
        raise module.urllib.error.HTTPError("https://huggingface.co/space", status, "failed", None, None)

    monkeypatch.setattr(module.urllib.request, "urlopen", fail)
    with pytest.raises(module.urllib.error.HTTPError):
        module.prepare_space_gitattributes(tmp_path, api=object(), space_id="owner/space", token="test-token")
    assert not (tmp_path / ".gitattributes").exists()


def test_graphviz_registration_aborts_if_attributes_change_after_the_snapshot(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    remote = {"sha": "b" * 40, "attributes": b"# Original rule\n"}
    monkeypatch.setattr(module, "current_space_sha", lambda *_args, **_kwargs: remote["sha"])

    def read_snapshot(request, **_kwargs):
        assert f"/resolve/{'b' * 40}/.gitattributes" in request.full_url
        original = remote["attributes"]
        remote.update(sha="c" * 40, attributes=original + b"*.custom filter=lfs\n")
        return io.BytesIO(original)

    class _Api:
        def upload_file(self, **kwargs):
            assert kwargs["parent_commit"] == "b" * 40
            assert kwargs["parent_commit"] != remote["sha"]
            raise module.urllib.error.HTTPError("https://huggingface.co/commit", 409, "conflict", None, None)

        def upload_folder(self, **_kwargs):
            pytest.fail("A failed attributes registration must prevent the folder upload")

    monkeypatch.setattr(module.urllib.request, "urlopen", read_snapshot)
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(HfApi=lambda: _Api()))
    with pytest.raises(module.urllib.error.HTTPError, match="409"):
        module.upload_space(tmp_path, space_id="owner/space", token="test-token", private=False)
    assert remote["attributes"] == b"# Original rule\n*.custom filter=lfs\n"


def test_folder_upload_preserves_attributes_edited_after_registration(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    remote = {".gitattributes": b"# Original rule\n"}
    monkeypatch.setattr(module, "current_space_sha", lambda *_args, **_kwargs: "b" * 40)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_args, **_kwargs: io.BytesIO(remote[".gitattributes"]))
    monkeypatch.setattr(module, "set_space_visibility", lambda *_args, **_kwargs: None)
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/.gitattributes").write_bytes(b"# Nested app rule\n")

    class _Api:
        def upload_file(self, **kwargs):
            assert kwargs["parent_commit"] == "b" * 40
            remote[".gitattributes"] = kwargs["path_or_fileobj"]
            remote[".gitattributes"] += b"*.custom filter=lfs\n"

        def upload_folder(self, **kwargs):
            for path in tmp_path.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(tmp_path).as_posix()
                    if not any(fnmatch.fnmatchcase(relative, pattern) for pattern in kwargs["ignore_patterns"]):
                        remote[relative] = path.read_bytes()
            return types.SimpleNamespace(oid="a" * 40)

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(HfApi=lambda: _Api()))
    assert module.upload_space(tmp_path, space_id="owner/space", token="test-token", private=False) == "a" * 40
    assert remote[".gitattributes"] == b"# Original rule\n" + module.GRAPHVIZ_LFS_RULE.encode() + b"\n*.custom filter=lfs\n"
    assert remote["nested/.gitattributes"] == b"# Nested app rule\n"


def test_generated_space_readme_uses_valid_hf_emoji_metadata() -> None:
    module = _load_module()

    assert "emoji: 🧪" in module.README_TEMPLATE
    assert "emoji: lab_coat" not in module.README_TEMPLATE


def test_generated_dockerfile_refreshes_first_proof_helpers_on_boot() -> None:
    module = _load_module()

    assert "src/agilab/apps/install.py" in module.DOCKERFILE_TEMPLATE
    assert "flight_telemetry_project --verbose 0" in module.DOCKERFILE_TEMPLATE
    assert "python -m agi_web.react_python_host /app/hf_app.py" in module.DOCKERFILE_TEMPLATE


def test_public_space_uses_native_host_without_module_file_watching() -> None:
    dockerfile = _load_module().DOCKERFILE_TEMPLATE
    command = dockerfile[dockerfile.index('CMD ['):]
    assert "python -m agi_web.react_python_host /app/hf_app.py" in command
    assert "--address 0.0.0.0" in command
    assert "AGILAB_PUBLIC_BIND_OK=1 AGILAB_TLS_TERMINATED=1" in command
    assert "streamlit" not in command.lower()
    assert "--server.fileWatcherType" not in command


def test_generated_dockerfile_verifies_demo_before_starting_server() -> None:
    module = _load_module()
    dockerfile = module.DOCKERFILE_TEMPLATE
    verification = "uv run --project /app --no-sync python /app/src/agilab/agent_runtime/notebook_verifier.py"

    assert "RUN cd /app/src/agilab/demos/resources/notebook_agent_demo &&" in dockerfile
    assert dockerfile.index("--extra notebook-agent") < dockerfile.index(verification)
    assert dockerfile.index(verification) < dockerfile.index('CMD [')


def test_generated_dockerfile_installs_declared_notebook_app_dependencies() -> None:
    dockerfile = _load_module().DOCKERFILE_TEMPLATE
    dependency_install = dockerfile.index("uv pip install --python /app/.venv/bin/python")
    for demo in ("free_threading_demo", "milp_energy_demo"):
        project = Path("src/agilab/demos/resources") / demo / "pyproject.toml"
        metadata = tomllib.loads((REPO_ROOT / project).read_text())
        assert any(dependency.startswith("altair") for dependency in metadata["project"]["dependencies"])
        requirement = f"--requirements /app/{project.as_posix()}"
        assert requirement in dockerfile
        verification = f"RUN cd /app/src/agilab/demos/resources/{demo} &&"
        assert dependency_install < dockerfile.index(requirement) < dockerfile.index(verification)


def test_free_threaded_benchmark_is_isolated_and_verified_before_serving() -> None:
    dockerfile = _load_module().DOCKERFILE_TEMPLATE
    assert 'ENV AGI_PYTHON_FREE_THREADED="0"' in dockerfile
    assert 'ENV AGILAB_FREE_THREADING_PYTHON="/home/user/python3.14t"' in dockerfile
    assert "uv python install 3.14.6t" in dockerfile
    assert "assert not sys._is_gil_enabled()" in dockerfile
    check = "python /app/src/agilab/agent_runtime/notebook_execution_verifier.py"
    assert "RUN cd /app/src/agilab/demos/resources/free_threading_demo &&" in dockerfile
    assert dockerfile.index("uv python install 3.14.6t") < dockerfile.index(check)
    assert dockerfile.index(check) < dockerfile.index('CMD [')


def test_milp_lab_is_verified_before_serving() -> None:
    dockerfile = _load_module().DOCKERFILE_TEMPLATE
    start = dockerfile.index("RUN cd /app/src/agilab/demos/resources/milp_energy_demo &&")
    check = dockerfile.index("python /app/src/agilab/agent_runtime/notebook_execution_verifier.py", start)
    assert dockerfile.index("--extra notebook-agent") < start < check < dockerfile.index('CMD [')


def test_space_entrypoint_explicitly_runs_agilab_main(tmp_path) -> None:
    module = _load_module()
    apps, pages = module.profile_entries("first-proof")
    module.write_profile_assets(tmp_path, "first-proof", apps, pages)
    entrypoint = tmp_path / "hf_app.py"
    source = entrypoint.read_text()
    assert 'runpy.run_module("agilab.main_page", run_name="__main__")' in source
    assert "streamlit" not in source.lower()


def test_first_proof_profile_uses_public_weather_demo() -> None:
    module = _load_module()

    apps, pages = module.profile_entries("first-proof")

    assert apps == ("flight_telemetry_project", "weather_forecast_project", "pytorch_playground_project")
    assert pages == ("view_maps", "view_forecast_analysis", "view_release_decision")


def test_advanced_profile_excludes_retired_weather_clone() -> None:
    module = _load_module()

    apps, _pages = module.profile_entries("advanced")

    assert "weather_forecast_project" in apps
    assert "weather_forecast_legacy_project" not in apps


def test_staged_profile_resolves_pruned_payloads_from_wheelhouse_without_source_ui_tests(tmp_path: Path) -> None:
    module = _load_module()
    repo = _write_stage_repo(tmp_path)
    for page, name in (
        ("view_maps", "agi-page-geospatial-map"),
        ("view_maps_3d", "agi-page-geospatial-3d"),
        ("view_maps_network", "agi-page-network-map"),
    ):
        directory = repo / "src/agilab/apps-pages" / page
        directory.mkdir(exist_ok=True)
        (directory / "pyproject.toml").write_text(
            f"[project]\nname={name!r}\nversion='1.0.0'\n", encoding="utf-8"
        )
    manifest = repo / "pyproject.toml"
    wrapper = repo / "src/agilab/lib/agi-app-data-quality-gate"
    wrapper.mkdir(parents=True)
    (wrapper.parent / "app_project_build_support.py").write_text(
        "APP_PROJECT_SPECS = ({'distribution': 'agi-app-data-quality-gate', 'project': 'data_quality_gate_project'},)\n",
        encoding="utf-8",
    )
    (wrapper / "pyproject.toml").write_text(
        "[project]\nname='agi-app-data-quality-gate'\nversion='1.0.0'\n"
        "[project.entry-points.'agilab.apps']\ndata_quality_gate_project='provider:project_root'\n"
        "old_quality_project='provider:project_root'\n",
        encoding="utf-8",
    )
    manifest.write_text(
        "[project]\nname='agilab'\nversion='1.0.0'\n"
        "dependencies=['agi-page-geospatial-map']\n"
        "[project.optional-dependencies]\nnetwork=['agi-page-network-map==1.0.0', 'agi-app-data-quality-gate==1.0.0']\n"
        "[dependency-groups]\ndev=[]\n"
        "test-ui=['agi-page-geospatial-3d', 'agi-page-network-map']\n"
        "[tool.uv.sources]\n"
        "agi-page-geospatial-map={path='src/agilab/apps-pages/view_maps'}\n"
        "agi-page-geospatial-3d={path='src/agilab/apps-pages/view_maps_3d'}\n"
        "agi-page-network-map={path='src/agilab/apps-pages/view_maps_network'}\n",
        encoding="utf-8",
    )
    with manifest.open("a", encoding="utf-8") as stream:
        stream.write("agi-app-data-quality-gate={path='src/agilab/lib/agi-app-data-quality-gate'}\n")
    page_manifest = repo / "src/agilab/apps-pages/view_maps/pyproject.toml"
    with page_manifest.open("a", encoding="utf-8") as stream:
        stream.write(
            "dependencies=['agi-app-data-quality-gate==1.0.0']\n"
            "[tool.uv.sources]\n"
            "agi-app-data-quality-gate={path='../../lib/agi-app-data-quality-gate'}\n"
        )
    original = manifest.read_bytes()
    original_page = page_manifest.read_bytes()
    wheelhouse = tmp_path / "release-wheelhouse"
    wheelhouse.mkdir()
    for name in ("agi-page-network-map", "agi-app-data-quality-gate"):
        stem = name.replace("-", "_")
        dist_info = f"{stem}-1.0.0.dist-info"
        with ZipFile(wheelhouse / f"{stem}-1.0.0-py3-none-any.whl", "w") as wheel:
            wheel.writestr(f"{dist_info}/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0.0\n")
            wheel.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
            wheel.writestr(f"{dist_info}/RECORD", "")
    stage = tmp_path / "stage"
    stage.mkdir()
    module.stage_space_tree(repo, stage, profile="first-proof")
    completed = subprocess.run(
        ["uv", "sync", "--project", str(stage), "--dry-run", "--offline", "--extra", "network",
         "--find-links", str(wheelhouse), "--python", sys.executable],
        capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    locked_result = subprocess.run(
        ["uv", "lock", "--project", str(stage), "--offline", "--find-links", str(wheelhouse), "--python", sys.executable],
        capture_output=True, text=True,
    )
    assert locked_result.returncode == 0, locked_result.stderr
    staged = tomllib.loads((stage / "pyproject.toml").read_text())
    assert staged["project"] == tomllib.loads(original.decode())["project"]
    assert staged["dependency-groups"] == {"dev": []}
    assert set(staged["tool"]["uv"]["sources"]) == {"agi-page-geospatial-map"}
    staged_page = tomllib.loads((stage / "src/agilab/apps-pages/view_maps/pyproject.toml").read_text())
    assert staged_page["project"] == tomllib.loads(original_page.decode())["project"]
    assert not staged_page["tool"]["uv"]["sources"]
    locked = tomllib.loads((stage / "uv.lock").read_text())
    app_source = next(package["source"] for package in locked["package"] if package["name"] == "agi-app-data-quality-gate")
    assert "directory" not in app_source and "editable" not in app_source
    assert sorted(path.name for path in (stage / "src/agilab/apps-pages").iterdir()) == sorted(module.FIRST_PROOF_PAGES)
    assert manifest.read_bytes() == original
    assert page_manifest.read_bytes() == original_page


def test_stage_space_tree_prunes_private_app_entries_before_validation(tmp_path: Path) -> None:
    module = _load_module()
    repo = _write_stage_repo(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()

    summary = module.stage_space_tree(repo, stage, profile="first-proof")

    assert summary["apps"] == [
        "flight_telemetry_project",
        "weather_forecast_project",
        "pytorch_playground_project",
    ]
    assert not (stage / "src/agilab/apps/private_project").exists()
    assert (stage / "src/agilab/apps/builtin/flight_telemetry_project").is_dir()
    assert (stage / "src/agilab/apps/builtin/weather_forecast_project").is_dir()
    assert (stage / "src/agilab/apps/builtin/pytorch_playground_project").is_dir()


def test_stage_space_tree_rejects_included_symlink_before_stage_mutation(tmp_path: Path) -> None:
    module = _load_module()
    repo = _write_stage_repo(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    sentinel = stage / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("private payload\n", encoding="utf-8")
    linked = repo / "src/agilab/apps/builtin/flight_telemetry_project/external.txt"
    try:
        linked.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"file symlinks unavailable: {error}")

    with pytest.raises(RuntimeError, match="source tree contains symlinks"):
        module.stage_space_tree(repo, stage, profile="first-proof")

    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert not (stage / "src").exists()


def test_stage_space_tree_ignores_excluded_app_symlink(tmp_path: Path) -> None:
    module = _load_module()
    repo = _write_stage_repo(tmp_path)
    external_app = tmp_path / "external-app"
    external_app.mkdir()
    (external_app / "private.txt").write_text("private\n", encoding="utf-8")
    try:
        (repo / "src/agilab/apps/installed_project").symlink_to(
            external_app, target_is_directory=True
        )
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")
    stage = tmp_path / "stage"
    stage.mkdir()

    module.stage_space_tree(repo, stage, profile="first-proof")

    assert not (stage / "src/agilab/apps/installed_project").exists()


def test_hosted_smoke_receives_profile(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    captured: list[list[str]] = []

    def _run_command(command):
        captured.append(list(command))
        return '{"success": true}'

    monkeypatch.setattr(module, "run_command", _run_command)

    smoke = module.run_hosted_smoke(
        tmp_path,
        space_id="demo/agilab",
        profile="advanced",
        timeout=1.0,
        target_seconds=2.0,
    )

    assert smoke == {"success": True}
    assert "--profile" in captured[0]
    assert captured[0][captured[0].index("--profile") + 1] == "advanced"
