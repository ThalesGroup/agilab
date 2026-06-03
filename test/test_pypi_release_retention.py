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


def test_resolve_protect_versions_accepts_disaligned_package_versions() -> None:
    module = _load_module()

    package_versions = module.resolve_protect_versions(
        packages=["agilab", "agi-core"],
        protect_package_versions=[
            "agilab=2026.05.18",
            "agi-core=2026.05.17",
        ],
    )

    assert package_versions == {
        "agilab": "2026.5.18",
        "agi-core": "2026.5.17",
    }


def test_resolve_protect_versions_reads_selected_project_versions(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "selected_public_versions",
        lambda repo_root, package_names: {
            "agilab": "2026.05.18",
            "agi-core": "2026.05.17",
        },
    )

    package_versions = module.resolve_protect_versions(
        packages=["agilab", "agi-core"],
        protect_versions_from_projects=True,
        repo_root=tmp_path,
    )

    assert package_versions == {
        "agilab": "2026.5.18",
        "agi-core": "2026.5.17",
    }


def test_resolve_protect_versions_rejects_missing_package_version() -> None:
    module = _load_module()

    with pytest.raises(SystemExit, match="missing protected versions for: agi-core"):
        module.resolve_protect_versions(
            packages=["agilab", "agi-core"],
            protect_package_versions=["agilab=2026.05.18"],
        )


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
            "totp_secret": None,
            "confirm_login_url_provider": None,
        }
    ]
    assert "direct PyPI web fallback" in capsys.readouterr().err


def test_delete_release_can_use_direct_web_only(monkeypatch, capsys) -> None:
    module = _load_module()
    fallback_calls = []

    def fail_run(*args, **kwargs):
        raise AssertionError("pypi-cleanup should not run in direct-web-only mode")

    def fake_fallback(**kwargs):
        fallback_calls.append(kwargs)

    monkeypatch.setattr(module.subprocess, "run", fail_run)
    monkeypatch.setattr(module, "delete_release_via_pypi_web", fake_fallback)

    module.delete_release(
        package="agilab",
        version="2026.05.17",
        repo="pypi",
        username="maintainer",
        password="secret",
        auth_code="123456",
        direct_web_only=True,
    )

    assert fallback_calls == [
        {
            "package": "agilab",
            "version": "2026.05.17",
            "repo": "pypi",
            "username": "maintainer",
            "password": "secret",
            "auth_code": "123456",
            "totp_secret": None,
            "confirm_login_url_provider": None,
        }
    ]
    assert "direct PyPI web deletion" in capsys.readouterr().err


def test_direct_pypi_delete_treats_missing_manage_release_as_already_deleted(
    monkeypatch,
    capsys,
) -> None:
    module = _load_module()

    class NotFoundError(Exception):
        def __init__(self) -> None:
            self.response = type("Response", (), {"status_code": 404})()

    class FakeResponse:
        def __init__(self, *, text: str, url: str, not_found: bool = False) -> None:
            self.text = text
            self.url = url
            self.not_found = not_found

        def raise_for_status(self) -> None:
            if self.not_found:
                raise NotFoundError()

    class FakeSession:
        def __init__(self) -> None:
            self.headers = {}
            self.posts = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            if url == "https://pypi.org/account/login/":
                return FakeResponse(
                    url=url,
                    text="""
                    <form method="post" action="/account/login/">
                      <input name="csrf_token" value="login-csrf">
                    </form>
                    """,
                )
            return FakeResponse(url=url, text="<html>missing</html>", not_found=True)

        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            return FakeResponse(
                url="https://pypi.org/manage/projects/",
                text="<html></html>",
            )

    monkeypatch.setattr(module, "fetch_releases", lambda package, repo: ["2026.5.26"])
    session = FakeSession()

    module.delete_release_via_pypi_web(
        package="agilab",
        version="2026.5.25",
        repo="pypi",
        username="maintainer",
        password="secret",
        session_factory=lambda: session,
    )

    assert session.posts[0][1]["data"]["username"] == "maintainer"
    assert "release already absent" in capsys.readouterr().err


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


def test_direct_pypi_delete_consumes_confirm_login_url_after_runner_login_redirect() -> None:
    module = _load_module()
    confirm_url = "https://pypi.org/account/confirm-login/?token=token"
    cleanup_calls = []

    class ConfirmProvider:
        def __call__(self) -> str:
            return confirm_url

        def cleanup(self) -> None:
            cleanup_calls.append("cleanup")

    class FakeResponse:
        def __init__(self, *, text: str, url: str) -> None:
            self.text = text
            self.url = url

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.headers = {}
            self.get_urls = []
            self.posts = []
            self.delete_attempts = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            self.get_urls.append(url)
            if url == "https://pypi.org/account/login/":
                return FakeResponse(
                    url=url,
                    text="""
                    <form method="post" action="/account/login/">
                      <input name="csrf_token" value="login-csrf">
                    </form>
                    """,
                )
            if url == confirm_url:
                return FakeResponse(url=url, text="<html>confirmed</html>")
            self.delete_attempts += 1
            if self.delete_attempts == 1:
                return FakeResponse(
                    url="https://pypi.org/account/login/",
                    text="<html>login required</html>",
                )
            return FakeResponse(
                url=url,
                text="""
                <form method="post" action="/manage/project/agilab/release/2026.5.17/">
                  <input name="csrf_token" value="delete-csrf">
                  <input name="confirm_delete_version" value="">
                </form>
                """,
            )

        def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            if url == "https://pypi.org/account/login/":
                return FakeResponse(
                    url="https://pypi.org/manage/projects/",
                    text="<html></html>",
                )
            return FakeResponse(
                url="https://pypi.org/manage/project/agilab/releases/",
                text="<html></html>",
            )

    session = FakeSession()

    module.delete_release_via_pypi_web(
        package="agilab",
        version="2026.5.17",
        repo="pypi",
        username="maintainer",
        password="secret",
        confirm_login_url_provider=ConfirmProvider(),
        session_factory=lambda: session,
    )

    assert confirm_url in session.get_urls
    assert cleanup_calls == ["cleanup"]
    assert session.delete_attempts == 2
    assert session.posts[-1][1]["data"] == {
        "csrf_token": "delete-csrf",
        "confirm_delete_version": "2026.5.17",
    }


def test_delete_github_actions_variable_handles_success_and_missing(monkeypatch) -> None:
    module = _load_module()
    requests = []
    responses = iter([object(), module.urllib.error.HTTPError("url", 404, "missing", {}, None)])

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b""

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    assert (
        module._delete_github_actions_variable(
            repository="owner/repo",
            variable="PYPI_CONFIRM_LOGIN_URL",
            token="token",
        )
        is True
    )
    assert (
        module._delete_github_actions_variable(
            repository="owner/repo",
            variable="PYPI_CONFIRM_LOGIN_URL",
            token="token",
        )
        is False
    )
    assert requests[0][0].get_method() == "DELETE"
    assert requests[0][1] == 15


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

    def fake_delete_release(
        *,
        package,
        version,
        repo,
        username,
        password,
        auth_code=None,
        totp_secret=None,
        confirm_login_url_provider=None,
        direct_web_only=False,
        verbose=False,
    ):
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


def test_main_deletes_old_versions_with_disaligned_protected_versions(monkeypatch, capsys) -> None:
    module = _load_module()
    releases = {
        "agilab": ["2026.04.16", "2026.05.18"],
        "agi-core": ["2026.04.16", "2026.05.17"],
    }
    deletes: list[tuple[str, str]] = []

    def fake_delete_release(
        *,
        package,
        version,
        repo,
        username,
        password,
        auth_code=None,
        totp_secret=None,
        confirm_login_url_provider=None,
        direct_web_only=False,
        verbose=False,
    ):
        deletes.append((package, version))
        releases[package] = [item for item in releases[package] if item != version]

    monkeypatch.setattr(module, "fetch_releases", lambda package, repo: releases[package])
    monkeypatch.setattr(module, "delete_release", fake_delete_release)

    status = module.main(
        [
            "--package",
            "agilab",
            "--package",
            "agi-core",
            "--protect-package-version",
            "agilab=2026.05.18",
            "--protect-package-version",
            "agi-core=2026.05.17",
            "--username",
            "maintainer",
            "--password",
            "secret",
            "--confirm-delete",
            "--json",
            "--retry-delay",
            "0",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert deletes == [("agilab", "2026.04.16"), ("agi-core", "2026.04.16")]
    assert '"package": "agilab"' in captured.out
    assert '"protect_version": "2026.5.18"' in captured.out
    assert '"package": "agi-core"' in captured.out
    assert '"protect_version": "2026.5.17"' in captured.out


def test_main_rotates_totp_between_package_deletions(monkeypatch) -> None:
    module = _load_module()
    releases = {
        "agilab": ["2026.04.16", "2026.05.17"],
        "agi-core": ["2026.04.16", "2026.05.17"],
    }
    generated_codes = iter(["111111", "111111", "111111", "222222", "222222"])
    deletes: list[tuple[str, str | None, str | None]] = []
    sleeps = []

    def fake_delete_release(
        *,
        package,
        version,
        repo,
        username,
        password,
        auth_code=None,
        totp_secret=None,
        confirm_login_url_provider=None,
        direct_web_only=False,
        verbose=False,
    ):
        deletes.append((package, auth_code, totp_secret))
        releases[package] = [item for item in releases[package] if item != version]

    monkeypatch.setenv("PYPI_RELEASE_PRUNE_TOTP_SECRET", "seed")
    monkeypatch.setattr(module, "generate_totp", lambda secret: next(generated_codes))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
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
            "--confirm-delete",
            "--retry-delay",
            "0",
        ]
    )

    assert status == 0
    assert deletes == [("agilab", "111111", "seed"), ("agi-core", "222222", "seed")]
    assert sleeps == [1]


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


def test_main_fails_closed_when_cleanup_requires_interactive_pypi_by_default(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.04.16", "2026.05.17"],
    )

    def fail_delete_release(**kwargs):
        raise SystemExit("PyPI redirected back to login")

    monkeypatch.setattr(module, "delete_release", fail_delete_release)

    with pytest.raises(SystemExit, match="PyPI redirected back to login"):
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
                "--retry-delay",
                "0",
            ]
        )


def test_main_rejects_missing_protected_release(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(module, "fetch_releases", lambda package, repo: ["2026.04.16"])

    with pytest.raises(SystemExit, match="agilab=2026.5.17"):
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
