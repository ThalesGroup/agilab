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


def test_delete_release_falls_back_when_pypi_cleanup_cannot_parse_delete_form(monkeypatch, capsys) -> None:
    module = _load_module()
    fallback_calls = []

    def fake_run(cmd, **kwargs):
        return module.subprocess.CompletedProcess(
            cmd,
            1,
            stdout="ValueError: No CSFR found in /manage/project/agilab/release/2026.5.17/\n",
        )

    def fake_fallback(**kwargs):
        fallback_calls.append(kwargs)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "delete_release_via_pypi_web", fake_fallback)

    module.delete_release(
        package="agilab",
        version="2026.05.17",
        repo="pypi",
        username="maintainer",
        password="secret",
        auth_code="123456",
    )

    assert fallback_calls == [
        {
            "package": "agilab",
            "version": "2026.05.17",
            "repo": "pypi",
            "username": "maintainer",
            "password": "secret",
            "auth_code": "123456",
        }
    ]
    assert "direct PyPI web fallback" in capsys.readouterr().err


def test_delete_form_parser_accepts_empty_action_and_fills_confirmation_fields() -> None:
    module = _load_module()

    form = module._find_form(
        """
        <form method="POST">
          <input type="hidden" name="csrf_token" value="token">
          <input name="confirm_delete_version" value="">
        </form>
        """,
        target_path="/manage/project/agilab/release/2026.5.17/",
        required_input="confirm_delete_version",
    )

    assert module._prepare_delete_form_data(
        form,
        package="agilab",
        version="2026.5.17",
    ) == {"csrf_token": "token", "confirm_delete_version": "2026.5.17"}


def test_direct_pypi_delete_submits_reauth_before_delete_form() -> None:
    module = _load_module()

    class FakeResponse:
        def __init__(self, *, text: str, url: str) -> None:
            self.text = text
            self.url = url

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.headers = {}
            self.posts = []
            self.gets = [
                FakeResponse(
                    url="https://pypi.org/account/login/",
                    text="""
                    <form method="post" action="/account/login/">
                      <input name="csrf_token" value="login-csrf">
                    </form>
                    """,
                ),
                FakeResponse(
                    url="https://pypi.org/manage/project/agilab/release/2026.5.17/",
                    text="""
                    <form method="post" action="/account/reauthenticate/">
                      <input name="csrf_token" value="reauth-csrf">
                      <input name="username" value="maintainer">
                      <input name="next_route" value="manage.project.release">
                      <input name="next_route_matchdict" value="{}">
                      <input name="next_route_query" value="{}">
                      <input name="password" type="password">
                    </form>
                    """,
                ),
            ]
            self.post_responses = [
                FakeResponse(
                    url="https://pypi.org/manage/projects/",
                    text="<html></html>",
                ),
                FakeResponse(
                    url="https://pypi.org/manage/project/agilab/release/2026.5.17/",
                    text="""
                    <form method="post" action="/manage/project/agilab/release/2026.5.17/">
                      <input name="csrf_token" value="delete-csrf">
                      <input name="confirm_delete_version" value="">
                    </form>
                    """,
                ),
                FakeResponse(
                    url="https://pypi.org/manage/project/agilab/releases/",
                    text="<html></html>",
                ),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            response = self.gets.pop(0)
            response.url = url
            return response

        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return self.post_responses.pop(0)

    session = FakeSession()

    module.delete_release_via_pypi_web(
        package="agilab",
        version="2026.5.17",
        repo="pypi",
        username="maintainer",
        password="secret",
        session_factory=lambda: session,
    )

    assert session.posts[0][1]["data"] == {
        "csrf_token": "login-csrf",
        "username": "maintainer",
        "password": "secret",
    }
    assert session.posts[1][0] == "https://pypi.org/account/reauthenticate/"
    assert session.posts[1][1]["data"]["password"] == "secret"
    assert session.posts[1][1]["data"]["username"] == "maintainer"
    assert session.posts[2][1]["data"] == {
        "csrf_token": "delete-csrf",
        "confirm_delete_version": "2026.5.17",
    }


def test_fresh_totp_code_waits_until_reused_code_changes(monkeypatch) -> None:
    module = _load_module()
    codes = iter(["123456", "123456", "654321"])
    sleeps = []

    monkeypatch.setenv("PYPI_RELEASE_PRUNE_TOTP_SECRET", "seed")
    monkeypatch.setattr(module, "generate_totp", lambda secret: next(codes))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(module.time, "time", lambda: 0)

    assert module._fresh_totp_code("123456") == "654321"
    assert sleeps == [1, 1]


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


def test_main_can_warn_when_cleanup_requires_interactive_pypi(monkeypatch, capsys) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.04.16", "2026.05.17"],
    )

    def fail_delete_release(**kwargs):
        raise SystemExit("PyPI redirected back to login")

    monkeypatch.setattr(module, "delete_release", fail_delete_release)

    status = module.main(
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
            "--allow-delete-failure-warning",
            "--json",
            "--retry-delay",
            "0",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert "::warning title=PyPI release retention::" in captured.err
    assert '"success": false' in captured.out
    assert '"delete_versions": [\n        "2026.04.16"\n      ]' in captured.out


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
