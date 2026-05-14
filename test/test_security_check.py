from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECURITY_CHECK_PATH = ROOT / "src" / "agilab" / "security_check.py"
SPEC = importlib.util.spec_from_file_location("agilab.security_check", SECURITY_CHECK_PATH)
assert SPEC and SPEC.loader
security_check = importlib.util.module_from_spec(SPEC)
sys.modules["agilab.security_check"] = security_check
SPEC.loader.exec_module(security_check)


def _touch_now(path: Path) -> None:
    path.write_text("{}", encoding="utf-8")


def test_env_file_parser_path_resolution_and_secret_placeholders(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# ignored",
                "not-an-assignment",
                "export APPS_REPOSITORY='relative-apps'",
                "=missing_key",
                "OPENAI_API_KEY=your-api-key",
                "CI_TOKEN=sk-test-placeholder",
                "REAL_PASSWORD=not-a-placeholder",
            ]
        ),
        encoding="utf-8",
    )

    values = security_check._parse_env_file(env_file)

    assert values["APPS_REPOSITORY"] == "relative-apps"
    assert "" not in values
    assert security_check._resolve_path(values["APPS_REPOSITORY"], cwd=tmp_path) == (
        tmp_path / "relative-apps"
    )
    assert security_check._looks_like_secret_value(values["OPENAI_API_KEY"]) is False
    assert security_check._looks_like_secret_value(values["CI_TOKEN"]) is False
    assert security_check._looks_like_secret_value(values["REAL_PASSWORD"]) is True


def test_git_state_supports_gitdir_files_detached_heads_and_unknown_heads(tmp_path: Path):
    worktree = tmp_path / "worktree"
    real_git_dir = tmp_path / "real-git"
    worktree.mkdir()
    real_git_dir.mkdir()
    (worktree / ".git").write_text("gitdir: ../real-git\n", encoding="utf-8")
    detached = "0123456789abcdef0123456789abcdef01234567"
    (real_git_dir / "HEAD").write_text(detached + "\n", encoding="utf-8")

    detached_state = security_check._git_head_state(worktree)

    assert detached_state["head_state"] == "detached"
    assert detached_state["commit"] == detached

    (real_git_dir / "HEAD").write_text("not-a-known-head-state\n", encoding="utf-8")

    unknown_state = security_check._git_head_state(worktree)

    assert unknown_state["head_state"] == "unknown"
    assert unknown_state["head"] == "not-a-known-head-state"


def test_defensive_parsers_handle_malformed_git_secret_and_streamlit_config(tmp_path: Path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("not-a-gitdir-file\n", encoding="utf-8")

    assert security_check._resolve_git_dir(worktree) is None

    git_dir = tmp_path / "real-git"
    git_dir.mkdir()
    (worktree / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")

    assert security_check._git_head_state(worktree) == {
        "is_git_checkout": True,
        "head_state": "unknown",
    }
    assert security_check._looks_like_secret_value("") is False

    streamlit_config = tmp_path / ".streamlit" / "config.toml"
    streamlit_config.parent.mkdir()
    streamlit_config.write_text("[server\n", encoding="utf-8")
    assert security_check._streamlit_config_address(tmp_path) is None

    streamlit_config.write_text("server = 'not-a-table'\n", encoding="utf-8")
    assert security_check._streamlit_config_address(tmp_path) is None


def test_apps_repository_check_reports_missing_file_nongit_and_pinned_checkout(tmp_path: Path):
    missing = security_check._check_apps_repository(
        {"APPS_REPOSITORY": "missing-apps"},
        cwd=tmp_path,
    )
    assert missing.status == "warn"
    assert "missing path" in missing.summary

    app_file = tmp_path / "apps-file"
    app_file.write_text("", encoding="utf-8")
    file_check = security_check._check_apps_repository(
        {"APPS_REPOSITORY": str(app_file)},
        cwd=tmp_path,
    )
    assert file_check.status == "warn"
    assert "not a directory" in file_check.summary

    app_dir = tmp_path / "apps"
    app_dir.mkdir()
    nongit_check = security_check._check_apps_repository(
        {"APPS_REPOSITORY": str(app_dir)},
        cwd=tmp_path,
    )
    assert nongit_check.status == "warn"
    assert "not a Git checkout" in nongit_check.summary

    git_dir = app_dir / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    pinned_check = security_check._check_apps_repository(
        {"APPS_REPOSITORY": str(app_dir)},
        cwd=tmp_path,
    )
    assert pinned_check.status == "pass"
    assert pinned_check.details["head_state"] == "detached"


def test_shared_profile_requires_apps_repository_origin_allowlist(tmp_path: Path):
    apps = tmp_path / "apps"
    git_dir = apps / ".git"
    git_dir.mkdir(parents=True)
    origin = "https://github.com/ThalesGroup/agilab-apps"
    (git_dir / "HEAD").write_text("0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    (git_dir / "config").write_text(
        f'[remote "origin"]\n    url = {origin}\n',
        encoding="utf-8",
    )

    missing_allowlist = security_check._check_apps_repository(
        {"APPS_REPOSITORY": str(apps)},
        cwd=tmp_path,
        profile="shared",
    )
    assert missing_allowlist.status == "fail"
    assert "allowlist" in missing_allowlist.summary

    allowlisted = security_check._check_apps_repository(
        {
            "APPS_REPOSITORY": str(apps),
            "AGILAB_APPS_REPOSITORY_ALLOWLIST": origin,
        },
        cwd=tmp_path,
        profile="shared",
    )
    assert allowlisted.status == "pass"
    assert allowlisted.details["allowlist_configured"] is True


def test_cluster_share_and_ui_exposure_pass_boundaries(tmp_path: Path):
    cluster_share = tmp_path / "clustershare"
    local_share = tmp_path / "localshare"
    cluster_share.mkdir()
    local_share.mkdir()
    cluster_check = security_check._check_cluster_share(
        {
            "AGI_CLUSTER_SHARE": str(cluster_share),
            "AGI_LOCAL_SHARE": str(local_share),
            "AGI_SCHEDULER_IP": "192.168.20.111",
            "AGI_WORKERS": "192.168.20.15",
        },
        cwd=tmp_path,
    )

    assert cluster_check.status == "pass"
    assert cluster_check.details["cluster_share"] == str(cluster_share)

    streamlit_config = tmp_path / ".streamlit" / "config.toml"
    streamlit_config.parent.mkdir()
    streamlit_config.write_text("[server]\naddress = '0.0.0.0'\n", encoding="utf-8")

    exposure_check = security_check._check_ui_exposure(
        {"AGILAB_PUBLIC_BIND_OK": "1", "AGILAB_AUTH_REQUIRED": "yes"},
        home=tmp_path,
    )

    assert exposure_check.status == "pass"
    assert exposure_check.details["host"] == "0.0.0.0"
    assert exposure_check.details["auth_or_tls_indicator"] is True


def test_optional_profiles_ignore_nonlocal_provider_and_print_text_skips_bad_checks(capsys):
    ignored = security_check._check_optional_profiles({"LAB_LLM_PROVIDER": "openai"})
    assert ignored.status == "pass"

    local = security_check._check_optional_profiles({"LAB_LLM_PROVIDER": "local-ollama"})
    assert local.status == "warn"
    assert local.details["enabled_keys"] == ["LAB_LLM_PROVIDER"]

    security_check._print_text(
        {
            "status": "warn",
            "summary": {"warnings": 1},
            "checks": [
                "not-a-check",
                {
                    "status": "warn",
                    "label": "Synthetic warning",
                    "summary": "needs attention",
                    "remediation": "fix it",
                },
            ],
        }
    )

    output = capsys.readouterr().out
    assert "AGILAB security-check: WARN (1 warning(s), 0 failure(s), profile=local)" in output
    assert "Synthetic warning" in output
    assert "not-a-check" not in output


def test_build_report_passes_for_clean_local_profile(tmp_path: Path):
    cwd = tmp_path / "repo"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    pip_audit = cwd / "pip-audit.json"
    sbom = cwd / "sbom-cyclonedx.json"
    _touch_now(pip_audit)
    _touch_now(sbom)

    report = security_check.build_report(
        environ={},
        cwd=cwd,
        home=home,
        now=datetime.now(timezone.utc),
    )

    assert report["schema"] == security_check.SCHEMA
    assert report["schema_version"] == security_check.SCHEMA_VERSION
    assert report["kind"] == "agilab.security_check"
    assert report["status"] == "pass"
    assert report["summary"]["warnings"] == 0
    assert {check["status"] for check in report["checks"]} == {"pass"}


def test_build_report_warns_on_adoption_risks_without_leaking_secret_values(tmp_path: Path):
    cwd = tmp_path / "repo"
    home = tmp_path / "home"
    apps = tmp_path / "apps"
    cluster_share = tmp_path / "clustershare"
    env_file = home / ".agilab" / ".env"
    cwd.mkdir()
    home.mkdir()
    apps.mkdir()
    cluster_share.mkdir()
    (apps / ".git").mkdir()
    (apps / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        "\n".join(
            [
                f"APPS_REPOSITORY={apps}",
                "OPENAI_API_KEY=sk-real-secret-should-not-print",
                f"AGI_CLUSTER_SHARE={cluster_share}",
                f"AGI_LOCAL_SHARE={cluster_share}",
                "AGI_SCHEDULER_IP=192.0.2.10",
                "STREAMLIT_SERVER_ADDRESS=0.0.0.0",
                "INSTALL_LOCAL_MODELS=gpt-oss",
            ]
        ),
        encoding="utf-8",
    )

    report = security_check.build_report(
        env_file=env_file,
        environ={},
        cwd=cwd,
        home=home,
        now=datetime.now(timezone.utc),
    )

    warning_ids = {
        check["id"]
        for check in report["checks"]
        if check["status"] == "warn"
    }
    assert report["status"] == "warn"
    assert warning_ids == {
        "apps_repository_pin",
        "persisted_plaintext_secrets",
        "cluster_share_isolation",
        "ui_network_exposure",
        "optional_runtime_profiles",
        "supply_chain_artifacts",
    }
    serialized = json.dumps(report, sort_keys=True)
    assert "OPENAI_API_KEY" in serialized
    assert "sk-real-secret-should-not-print" not in serialized


def test_build_report_respects_explicit_empty_environ(tmp_path: Path, monkeypatch):
    cwd = tmp_path / "repo"
    home = tmp_path / "home"
    cluster_share = tmp_path / "clustershare"
    polluted_local_share = tmp_path / "polluted-localshare"
    env_file = home / ".agilab" / ".env"
    cwd.mkdir()
    home.mkdir()
    cluster_share.mkdir()
    polluted_local_share.mkdir()
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        "\n".join(
            [
                f"AGI_CLUSTER_SHARE={cluster_share}",
                f"AGI_LOCAL_SHARE={cluster_share}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGI_LOCAL_SHARE", str(polluted_local_share))

    report = security_check.build_report(
        env_file=env_file,
        environ={},
        cwd=cwd,
        home=home,
        now=datetime.now(timezone.utc),
    )

    cluster_check = next(
        check for check in report["checks"] if check["id"] == "cluster_share_isolation"
    )
    assert cluster_check["status"] == "warn"
    assert cluster_check["details"]["local_share"] == str(cluster_share)
    assert cluster_check["details"]["same_as_local_share"] is True


def test_cli_json_strict_returns_nonzero_on_warnings(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("STREAMLIT_SERVER_ADDRESS=0.0.0.0\n", encoding="utf-8")

    rc = security_check.main(["--json", "--strict", "--env-file", str(env_file)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 1
    assert payload["schema"] == security_check.SCHEMA
    assert payload["status"] == "warn"


def test_cli_default_is_advisory_even_when_warnings_exist(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("STREAMLIT_SERVER_ADDRESS=0.0.0.0\n", encoding="utf-8")

    rc = security_check.main(["--env-file", str(env_file)])

    captured = capsys.readouterr()
    assert rc == 0
    assert "AGILAB security-check: WARN" in captured.out
    assert "UI network exposure" in captured.out


def test_build_report_warns_when_generated_code_autorun_has_no_sandbox(tmp_path: Path):
    cwd = tmp_path / "repo"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _touch_now(cwd / "pip-audit.json")
    _touch_now(cwd / "sbom-cyclonedx.json")

    report = security_check.build_report(
        environ={"UOAIC_AUTOFIX": "1"},
        cwd=cwd,
        home=home,
        now=datetime.now(timezone.utc),
    )

    check = next(item for item in report["checks"] if item["id"] == "generated_code_execution_boundary")
    assert check["status"] == "warn"
    assert "AGILAB_GENERATED_CODE_SANDBOX" in check["remediation"]


def test_build_report_accepts_generated_code_sandbox_indicator(tmp_path: Path):
    cwd = tmp_path / "repo"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _touch_now(cwd / "pip-audit.json")
    _touch_now(cwd / "sbom-cyclonedx.json")

    report = security_check.build_report(
        environ={"UOAIC_AUTOFIX": "1", "AGILAB_GENERATED_CODE_SANDBOX": "container"},
        cwd=cwd,
        home=home,
        now=datetime.now(timezone.utc),
    )

    check = next(item for item in report["checks"] if item["id"] == "generated_code_execution_boundary")
    assert check["status"] == "pass"
    assert check["details"]["sandbox"] == "container"


def test_shared_profile_rejects_process_sandbox_without_limits(tmp_path: Path):
    cwd = tmp_path / "repo"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _touch_now(cwd / "pip-audit.json")
    _touch_now(cwd / "sbom-cyclonedx.json")

    report = security_check.build_report(
        profile="shared",
        environ={"UOAIC_AUTOFIX": "1", "AGILAB_GENERATED_CODE_SANDBOX": "process"},
        cwd=cwd,
        home=home,
        now=datetime.now(timezone.utc),
    )

    check = next(item for item in report["checks"] if item["id"] == "generated_code_execution_boundary")
    assert report["status"] == "fail"
    assert check["status"] == "fail"
    assert "AGILAB_GENERATED_CODE_PROCESS_LIMITS" in check["remediation"]


def test_script_entrypoint_exits_with_main_status(tmp_path: Path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    _touch_now(tmp_path / "pip-audit.json")
    _touch_now(tmp_path / "sbom-cyclonedx.json")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "argv", [str(SECURITY_CHECK_PATH), "--json"])

    try:
        runpy.run_path(str(SECURITY_CHECK_PATH), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover - the script contract is to raise SystemExit.
        raise AssertionError("security_check script did not exit")

    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "agilab.security_check"
    assert payload["status"] == "pass"
