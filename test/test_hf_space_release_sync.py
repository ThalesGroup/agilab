from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import subprocess
import sys
import types
import os
from pathlib import Path

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
    expected = set(exporter.SOURCE_FILES) | set(exporter.GENERATED_FILES) | {"PUBLIC_HASHES.json"}
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
from streamlit.testing.v1 import AppTest
from agilab.agent_runtime import notebook_showcase
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
                "**/.venv/**",
                "**/__pycache__/**",
                "**/*.pyc",
            ],
        }
    ]
    assert str(calls[0]["commit_message"]).startswith("chore: deploy AGILAB release Space (")
    assert visibility == [("jpmorard/agilab", "hf-token", False)]


def test_generated_space_readme_uses_valid_hf_emoji_metadata() -> None:
    module = _load_module()

    assert "emoji: 🧪" in module.README_TEMPLATE
    assert "emoji: lab_coat" not in module.README_TEMPLATE


def test_generated_dockerfile_refreshes_first_proof_helpers_on_boot() -> None:
    module = _load_module()

    assert "src/agilab/apps/install.py" in module.DOCKERFILE_TEMPLATE
    assert "flight_telemetry_project --verbose 0" in module.DOCKERFILE_TEMPLATE
    assert "streamlit run /app/hf_app.py" in module.DOCKERFILE_TEMPLATE


def test_generated_dockerfile_verifies_demo_before_starting_server() -> None:
    module = _load_module()
    dockerfile = module.DOCKERFILE_TEMPLATE
    verification = "uv run --project /app --no-sync python /app/src/agilab/agent_runtime/notebook_verifier.py"

    assert "RUN cd /app/src/agilab/resources/notebook_agent_demo &&" in dockerfile
    assert dockerfile.index("--extra notebook-agent") < dockerfile.index(verification)
    assert dockerfile.index(verification) < dockerfile.index('CMD [')


def test_free_threaded_benchmark_is_isolated_and_verified_before_serving() -> None:
    dockerfile = _load_module().DOCKERFILE_TEMPLATE
    assert 'ENV AGI_PYTHON_FREE_THREADED="0"' in dockerfile
    assert 'ENV AGILAB_FREE_THREADING_PYTHON="/home/user/python3.14t"' in dockerfile
    assert "uv python install 3.14.6t" in dockerfile
    assert "assert not sys._is_gil_enabled()" in dockerfile
    check = "python /app/src/agilab/agent_runtime/notebook_execution_verifier.py"
    assert "RUN cd /app/src/agilab/resources/free_threading_demo &&" in dockerfile
    assert dockerfile.index("uv python install 3.14.6t") < dockerfile.index(check)
    assert dockerfile.index(check) < dockerfile.index('CMD [')


def test_space_entrypoint_avoids_legacy_pages_router(tmp_path) -> None:
    from streamlit.runtime.pages_manager import PagesManager

    module = _load_module()
    apps, pages = module.profile_entries("first-proof")
    module.write_profile_assets(tmp_path, "first-proof", apps, pages)
    entrypoint = tmp_path / "hf_app.py"
    assert 'runpy.run_module("agilab.main_page", run_name="__main__")' in entrypoint.read_text()
    previous = PagesManager.uses_pages_directory
    try:
        PagesManager.uses_pages_directory = None
        manager = PagesManager(str(entrypoint))
        assert manager.uses_pages_directory is False
    finally:
        PagesManager.uses_pages_directory = previous


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
