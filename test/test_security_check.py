from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
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
