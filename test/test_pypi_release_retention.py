from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "pypi_release_retention.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("pypi_release_retention_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_retention_plan_keeps_only_protected_normalized_version(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.04.16", "2026.04.17", "2026.5.17"],
    )

    plan = module.build_plan("agilab", "pypi", "v2026.05.17")

    assert plan.protect_version == "2026.5.17"
    assert plan.delete_versions == ["2026.04.16", "2026.04.17"]
    assert plan.missing_protected_version is False


def test_main_refuses_to_delete_without_confirmation(monkeypatch, capsys) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.04.16", "2026.05.17"],
    )

    with pytest.raises(SystemExit, match="requires --confirm-delete"):
        module.main(["--package", "agilab", "--protect-version", "2026.05.17"])

    assert capsys.readouterr().out == ""


def test_main_retries_until_protected_release_is_visible(monkeypatch, capsys) -> None:
    module = _load_module()
    calls = 0

    def fake_fetch_releases(package, repo):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ["2026.04.16"]
        return ["2026.04.16", "2026.05.17"]

    monkeypatch.setattr(module, "fetch_releases", fake_fetch_releases)

    status = module.main(
        [
            "--package",
            "agilab",
            "--protect-version",
            "2026.05.17",
            "--dry-run",
            "--json",
            "--retry-delay",
            "0",
        ]
    )

    assert status == 0
    assert calls == 2
    assert '"missing_protected_version": false' in capsys.readouterr().out


def test_main_requires_web_cleanup_credentials_for_deletion(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.04.16", "2026.05.17"],
    )
    monkeypatch.delenv("PYPI_RELEASE_PRUNE_USERNAME", raising=False)
    monkeypatch.delenv("PYPI_RELEASE_PRUNE_PASSWORD", raising=False)

    with pytest.raises(SystemExit, match="PYPI_RELEASE_PRUNE_USERNAME"):
        module.main(["--package", "agilab", "--protect-version", "2026.05.17", "--confirm-delete"])


def test_totp_generation_matches_rfc_vector() -> None:
    module = _load_module()

    assert module.generate_totp(
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
        for_time=59,
    ) == "287082"


def test_delete_release_feeds_and_redacts_non_interactive_otp(monkeypatch, capsys) -> None:
    module = _load_module()
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return module.subprocess.CompletedProcess(
            cmd,
            0,
            stdout="Authentication code 123456 accepted\nDeleted\n",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.delete_release(
        package="agilab",
        version="2026.05.17",
        repo="pypi",
        username="maintainer",
        password="secret",
        auth_code="123456",
    )

    assert calls[0][1]["input"] == "123456\n"
    assert "123456" not in capsys.readouterr().err


def test_delete_release_reports_missing_non_interactive_2fa_secret(monkeypatch) -> None:
    module = _load_module()

    def fake_run(cmd, **kwargs):
        return module.subprocess.CompletedProcess(
            cmd,
            1,
            stdout="Authentication code: Traceback\nEOFError: EOF when reading a line\n",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="PYPI_RELEASE_PRUNE_TOTP_SECRET"):
        module.delete_release(
            package="agilab",
            version="2026.05.17",
            repo="pypi",
            username="maintainer",
            password="secret",
        )


def test_main_deletes_old_versions_and_verifies_retention(monkeypatch, capsys) -> None:
    module = _load_module()
    releases = {
        "agilab": ["2026.04.16", "2026.05.17"],
        "agi-core": ["2026.04.16", "2026.05.17"],
    }
    deletes: list[tuple[str, str, str, str]] = []

    def fake_delete_release(*, package, version, repo, username, password, auth_code=None, verbose=False):
        deletes.append((package, version, username, password, auth_code))
        releases[package] = [item for item in releases[package] if item != version]

    monkeypatch.setattr(module, "fetch_releases", lambda package, repo: releases[package])
    monkeypatch.setattr(module, "delete_release", fake_delete_release)

    status = module.main(
        [
            "--package",
            "agilab",
            "--package",
            "agi-core",
            "--protect-version",
            "2026.05.17",
            "--username",
            "maintainer",
            "--password",
            "secret",
            "--otp-code",
            "123456",
            "--confirm-delete",
            "--json",
            "--retry-delay",
            "0",
        ]
    )

    assert status == 0
    assert deletes == [
        ("agilab", "2026.04.16", "maintainer", "secret", "123456"),
        ("agi-core", "2026.04.16", "maintainer", "secret", "123456"),
    ]
    assert '"success": true' in capsys.readouterr().out


def test_main_blocks_when_cleanup_failure_remains(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.04.16", "2026.05.17"],
    )

    def fail_delete_release(**kwargs):
        raise SystemExit("cleanup failed")

    monkeypatch.setattr(module, "delete_release", fail_delete_release)

    with pytest.raises(SystemExit, match="cleanup failed"):
        module.main(
            [
                "--package",
                "agilab",
                "--protect-version",
                "2026.05.17",
                "--username",
                "maintainer",
                "--password",
                "secret",
                "--confirm-delete",
                "--json",
            ]
        )


def test_main_rejects_missing_protected_release(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(module, "fetch_releases", lambda package, repo: ["2026.04.16"])

    with pytest.raises(SystemExit, match="protected version 2026.5.17 is not visible"):
        module.main(
            [
                "--package",
                "agilab",
                "--protect-version",
                "2026.05.17",
                "--verify-attempts",
                "1",
            ]
        )
