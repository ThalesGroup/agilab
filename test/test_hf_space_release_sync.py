from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "hf_space_release_sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("hf_space_release_sync_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_url_matches_hf_space_subdomain() -> None:
    module = _load_module()

    assert module.runtime_url_for_space("jpmorard/agilab") == "https://jpmorard-agilab.hf.space"
    assert module.runtime_url_for_space("team-name/agilab-demo") == "https://team-name-agilab-demo.hf.space"


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


def test_generated_space_readme_uses_valid_hf_emoji_metadata() -> None:
    module = _load_module()

    assert "emoji: 🧪" in module.README_TEMPLATE
    assert "emoji: lab_coat" not in module.README_TEMPLATE


def test_first_proof_profile_uses_public_weather_demo() -> None:
    module = _load_module()

    apps, pages = module.profile_entries("first-proof")

    assert apps == ("flight_telemetry_project", "weather_forecast_project")
    assert pages == ("view_maps", "view_forecast_analysis", "view_release_decision")


def test_stage_space_tree_prunes_private_app_entries_before_validation(tmp_path: Path) -> None:
    module = _load_module()
    repo = tmp_path / "repo"
    stage = tmp_path / "stage"
    stage.mkdir()

    (repo / "src/agilab/apps/builtin/flight_telemetry_project").mkdir(parents=True)
    (repo / "src/agilab/apps/builtin/weather_forecast_project").mkdir(parents=True)
    (repo / "src/agilab/apps/private_project").mkdir(parents=True)
    for page in ("view_maps", "view_forecast_analysis", "view_release_decision"):
        (repo / "src/agilab/apps-pages" / page).mkdir(parents=True)
    (repo / "src/agilab").mkdir(parents=True, exist_ok=True)
    (repo / "docker").mkdir()
    (repo / "src/agilab/main_page.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "src/agilab/apps/private_project/secret.txt").write_text("private\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='agilab'\n", encoding="utf-8")
    (repo / "uv_config.toml").write_text("", encoding="utf-8")
    (repo / "docker/install.sh").write_text("#!/usr/bin/env sh\n", encoding="utf-8")

    summary = module.stage_space_tree(repo, stage, profile="first-proof")

    assert summary["apps"] == ["flight_telemetry_project", "weather_forecast_project"]
    assert not (stage / "src/agilab/apps/private_project").exists()
    assert (stage / "src/agilab/apps/builtin/flight_telemetry_project").is_dir()
    assert (stage / "src/agilab/apps/builtin/weather_forecast_project").is_dir()


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
