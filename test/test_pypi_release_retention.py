from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "pypi_release_retention.py"


def _load_module(*, stub_network: bool = True):
    spec = importlib.util.spec_from_file_location("pypi_release_retention_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if stub_network:
        module.fetch_exact_release_version = (
            lambda package, repo, version: module.normalize_version(version)
        )
        module.probe_exact_release_version = lambda package, repo, version: (
            module.EXACT_RELEASE_PRESENT,
            module.normalize_version(version),
        )
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


def test_exact_release_probe_uses_distinct_cache_busted_requests(monkeypatch) -> None:
    module = _load_module(stub_network=False)
    requests = []
    nonces = iter([101, 102])

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"info": {"version": "2026.7.17"}}).encode()

    def fake_urlopen(request, *, timeout):
        requests.append((request, timeout))
        return _Response()

    monkeypatch.setattr(module.time, "time_ns", lambda: next(nonces))
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    assert module.fetch_exact_release_version("agi-web", "pypi", "2026.07.17") == "2026.7.17"
    assert module.fetch_exact_release_version("agi-web", "pypi", "2026.07.17") == "2026.7.17"
    assert [request.full_url for request, _timeout in requests] == [
        "https://pypi.org/pypi/agi-web/2026.7.17/json?agilab_cache_bust=101",
        "https://pypi.org/pypi/agi-web/2026.7.17/json?agilab_cache_bust=102",
    ]
    headers = dict(requests[0][0].header_items())
    assert headers["Accept"] == "application/json"
    assert headers["Cache-control"] == "no-cache, no-store, max-age=0"
    assert headers["Pragma"] == "no-cache"
    assert headers["User-agent"] == "agilab-pypi-retention/1.0"
    assert [timeout for _request, timeout in requests] == [15, 15]


def test_retention_plan_accepts_matching_exact_release_when_project_json_is_stale(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "fetch_releases", lambda package, repo: ["2026.7.4"])
    monkeypatch.setattr(
        module,
        "fetch_exact_release_version",
        lambda package, repo, version: "2026.7.17",
    )

    plan = module.build_plan(
        "agi-web",
        "pypi",
        "2026.7.17",
        min_published_releases=2,
    )

    assert plan.published_versions == ["2026.7.4", "2026.7.17"]
    assert plan.delete_versions == ["2026.7.4"]
    assert plan.missing_protected_version is False


def test_retention_plan_stays_fail_closed_when_exact_release_is_missing(monkeypatch) -> None:
    module = _load_module(stub_network=False)
    monkeypatch.setattr(module, "fetch_releases", lambda package, repo: ["2026.7.4"])

    def missing_exact_release(request, *, timeout):
        raise module.urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(module.urllib.request, "urlopen", missing_exact_release)

    plan = module.build_plan("agi-web", "pypi", "2026.7.17")

    assert plan.published_versions == ["2026.7.4"]
    assert plan.delete_versions == []
    assert plan.retained_versions == ["2026.7.4"]
    assert plan.missing_protected_version is True


def test_retention_plan_refuses_deletion_when_only_aggregate_confirms_protected_release(
    monkeypatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.7.4", "2026.7.17"],
    )
    monkeypatch.setattr(module, "fetch_exact_release_version", lambda package, repo, version: None)

    plan = module.build_plan("agi-web", "pypi", "2026.7.17")

    assert plan.delete_versions == []
    assert plan.retained_versions == ["2026.7.4"]
    assert plan.missing_protected_version is True


def test_post_delete_verification_accepts_exact_404_with_stale_aggregate(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.7.4", "2026.7.17"],
    )
    monkeypatch.setattr(
        module,
        "probe_exact_release_version",
        lambda package, repo, version: (
            (module.EXACT_RELEASE_PRESENT, "2026.7.17")
            if version == "2026.7.17"
            else (module.EXACT_RELEASE_ABSENT, None)
        ),
    )

    plans = module.verify_package_retention(
        package_versions={"agi-web": "2026.7.17"},
        repo="pypi",
        attempts=1,
        retry_delay=60,
    )

    assert plans[0].published_versions == ["2026.7.17"]
    assert plans[0].delete_versions == []


def test_post_delete_verification_retries_exact_endpoint_errors(monkeypatch) -> None:
    module = _load_module()
    attempts = 0
    sleeps: list[float] = []
    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.7.4", "2026.7.17"],
    )

    def probe(package, repo, version):
        nonlocal attempts
        if version == "2026.7.17":
            return module.EXACT_RELEASE_PRESENT, "2026.7.17"
        attempts += 1
        if attempts == 1:
            return module.EXACT_RELEASE_ERROR, None
        return module.EXACT_RELEASE_ABSENT, None

    monkeypatch.setattr(module, "probe_exact_release_version", probe)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    plans = module.verify_package_retention(
        package_versions={"agi-web": "2026.7.17"},
        repo="pypi",
        attempts=2,
        retry_delay=60,
    )

    assert attempts == 2
    assert sleeps == [60]
    assert plans[0].delete_versions == []


def test_protected_release_wait_allows_full_pypi_cache_window(monkeypatch) -> None:
    module = _load_module()
    calls = 0
    sleeps: list[float] = []

    def fake_build_plan(package, repo, protect_version, *, min_published_releases):
        nonlocal calls
        calls += 1
        missing = calls < 17
        return module.ReleasePlan(
            package=package,
            protect_version=protect_version,
            published_versions=[] if missing else [protect_version],
            delete_versions=[],
            retained_versions=[],
            missing_protected_version=missing,
        )

    monkeypatch.setattr(module, "build_plan", fake_build_plan)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    plans = module.wait_for_package_protected_releases(
        package_versions={"agi-web": "2026.7.17"},
        repo="pypi",
        attempts=17,
        retry_delay=60,
    )

    assert calls == 17
    assert sleeps == [60] * 16
    assert plans[0].missing_protected_version is False


def test_retention_plan_retains_old_versions_below_publish_threshold(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "fetch_releases",
        lambda package, repo: ["2026.04.16", "2026.04.17", "2026.05.17"],
    )

    plan = module.build_plan(
        "agilab",
        "pypi",
        "v2026.05.17",
        min_published_releases=11,
    )

    assert plan.delete_versions == []
    assert plan.retained_versions == ["2026.04.16", "2026.04.17"]
    assert plan.retention_skipped_reason == (
        "published release count 3 is below cleanup threshold 11"
    )
    assert plan.missing_protected_version is False


def test_retention_plan_deletes_old_versions_when_publish_threshold_is_reached(monkeypatch) -> None:
    module = _load_module()
    releases = [f"2026.05.{day:02d}" for day in range(1, 12)]

    monkeypatch.setattr(module, "fetch_releases", lambda package, repo: releases)

    plan = module.build_plan(
        "agilab",
        "pypi",
        "2026.05.11",
        min_published_releases=11,
    )

    assert plan.delete_versions == releases[:-1]
    assert plan.retained_versions == []
    assert plan.retention_skipped_reason is None
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






def test_package_file_rejects_wrapped_line(tmp_path: Path) -> None:
    module = _load_module()

    packages_file = tmp_path / "packages.txt"
    packages_file.write_text("agilab agi-core\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="one non-wrapped package per line"):
        module.read_packages_file(packages_file)
















def test_require_credentials_reads_pypirc_cleanup_section(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PYPI_RELEASE_PRUNE_USERNAME", raising=False)
    monkeypatch.delenv("PYPI_RELEASE_PRUNE_PASSWORD", raising=False)
    monkeypatch.delenv("PYPI_CLEANUP_PASSWORD", raising=False)
    monkeypatch.delenv("PYPI_PASSWORD", raising=False)
    (tmp_path / ".pypirc").write_text(
        "[distutils]\n"
        "index-servers = pypi\n"
        "\n"
        "[pypi_cleanup]\n"
        "username = maintainer\n"
        "password = web-secret\n",
        encoding="utf-8",
    )

    assert module.require_credentials(None, None, repo_name="pypi") == (
        "maintainer",
        "web-secret",
    )


def test_require_credentials_rejects_pypirc_api_token(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PYPI_RELEASE_PRUNE_USERNAME", raising=False)
    monkeypatch.delenv("PYPI_RELEASE_PRUNE_PASSWORD", raising=False)
    monkeypatch.delenv("PYPI_CLEANUP_PASSWORD", raising=False)
    monkeypatch.delenv("PYPI_PASSWORD", raising=False)
    (tmp_path / ".pypirc").write_text(
        "[pypi_cleanup]\nusername = __token__\npassword = pypi-token\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="API token"):
        module.require_credentials(None, None, repo_name="pypi")


def test_totp_generation_matches_rfc_vector() -> None:
    module = _load_module()

    assert module.generate_totp(
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
        for_time=59,
    ) == "287082"










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

    monkeypatch.setattr(
        module,
        "probe_exact_release_version",
        lambda package, repo, version: (module.EXACT_RELEASE_ABSENT, None),
    )
    session = FakeSession()

    module.delete_release_via_pypi_web(
        package="agilab",
        version="2026.5.25",
        repo="pypi",
        username="maintainer",
        password="secret",
        session_factory=lambda: session,
        before_delete=lambda: None,
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
        before_delete=lambda: None,
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
        before_delete=lambda: None,
    )

    assert confirm_url in session.get_urls
    assert cleanup_calls == ["cleanup"]
    assert session.delete_attempts == 2
    login_posts = [
        url
        for url, _kwargs in session.posts
        if url == "https://pypi.org/account/login/"
    ]
    assert len(login_posts) == 2
    assert session.posts[-1][1]["data"] == {
        "csrf_token": "delete-csrf",
        "confirm_delete_version": "2026.5.17",
    }


def test_direct_pypi_delete_reuses_confirmed_session_when_login_form_disappears() -> None:
    module = _load_module()
    confirm_url = "https://pypi.org/account/confirm-login/?token=token"

    class ConfirmProvider:
        def __call__(self) -> str:
            return confirm_url

        def cleanup(self) -> None:
            return None

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
            self.login_gets = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            self.get_urls.append(url)
            if url == "https://pypi.org/account/login/":
                self.login_gets += 1
                if self.login_gets == 1:
                    return FakeResponse(
                        url=url,
                        text="""
                        <form method="post" action="/account/login/">
                          <input name="csrf_token" value="login-csrf">
                        </form>
                        """,
                    )
                return FakeResponse(
                    url=url,
                    text="<html><p>Login already confirmed.</p></html>",
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
        before_delete=lambda: None,
    )

    assert confirm_url in session.get_urls
    assert session.login_gets == 2
    login_posts = [
        url
        for url, _kwargs in session.posts
        if url == "https://pypi.org/account/login/"
    ]
    assert len(login_posts) == 1
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


def _explicit_module(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "current_project_protections", lambda root: {"agi-gui": {"2026.10.12"}, "agi-web": {"2026.10.12"}})
    monkeypatch.setattr(module, "fetch_releases", lambda package, repo: ["2026.6.19", "2026.6.20", "2026.10.12"])
    monkeypatch.setattr(module, "fresh_release_metadata", lambda package, repo, version: {
        "info": {"name": package, "version": version},
        "urls": [{"filename": "archive.whl", "url": "https://files.pythonhosted.org/archive.whl",
                  "digests": {"sha256": module.hashlib.sha256(b"wheel").hexdigest()}, "size": 5}],
    })
    return module


@pytest.mark.parametrize("spec", ["agi-gui", "agi-gui=2026.6.19", "*==2026.6.19", "agi-gui==*", "agi-gui==2026.*", "agi-gui== 2026.6.19", "agi-gui==2026.6.19,agi-web==2026.6.19"])
def test_explicit_selection_rejects_nonliteral_specs(spec):
    module = _load_module()
    with pytest.raises(SystemExit):
        module.parse_delete_releases([spec])


def test_explicit_selection_canonicalizes_names_and_versions_and_rejects_alias_duplicates():
    module = _load_module()
    assert module.parse_delete_releases(["AGI_gui==2026.06.19"]) == {"agi-gui": ("2026.6.19",)}
    with pytest.raises(SystemExit, match="duplicate"):
        module.parse_delete_releases(["agi-gui==2026.6.19", "AGI_gui==2026.06.19"])


def test_main_refuses_broad_cleanup_before_network_or_authentication(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(module, "build_explicit_plans", lambda *a, **k: pytest.fail("must reject before network"))
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: pytest.fail("must not authenticate"))
    with pytest.raises(SystemExit, match="explicit --delete-release"):
        module.main(["--confirm-delete"])


def test_main_plans_one_exact_version_by_default_without_credentials(monkeypatch, capsys):
    module = _explicit_module(monkeypatch)
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: pytest.fail("plan must not authenticate"))
    monkeypatch.setattr(module, "delete_release", lambda **k: pytest.fail("plan must not delete"))
    assert module.main(["--delete-release", "AGI_gui==2026.06.19", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["success"] is True
    assert summary["dry_run"] is True
    assert summary["packages"][0]["delete_versions"] == ["2026.6.19"]
    assert summary["packages"][0]["retained_versions"] == ["2026.6.20", "2026.10.12"]


@pytest.mark.parametrize(("spec", "message"), [
    ("unknown==2026.6.19", "unknown first-party"),
    ("agi-gui==2025.1.1", "unknown published"),
    ("agi-gui==2026.10.12", "current, latest or pinned"),
])
def test_explicit_plan_rejects_unknown_and_protected_targets(monkeypatch, spec, message):
    module = _explicit_module(monkeypatch)
    with pytest.raises(SystemExit, match=message):
        module.main(["--delete-release", spec])


def test_explicit_plan_keeps_future_latest_and_extra_protected_version(monkeypatch):
    module = _explicit_module(monkeypatch)
    monkeypatch.setattr(module, "fetch_releases", lambda *a: ["2026.6.19", "2026.10.12", "2026.10.13"])
    for spec, extra in [("agi-gui==2026.10.13", []), ("agi-gui==2026.6.19", ["agi-gui=2026.6.19"])]:
        with pytest.raises(SystemExit, match="current, latest or pinned"):
            module.build_explicit_plans(module.parse_delete_releases([spec]), repo="pypi", repo_root=REPO_ROOT, extra_protections=extra)


def test_current_project_protections_keep_exact_first_party_dependency_pins(monkeypatch, tmp_path):
    module = _load_module()
    (tmp_path / "pyproject.toml").write_text('[project]\nname="agilab"\nversion="2026.10.12"\ndependencies=["agi-gui==2026.6.19"]\n[project.optional-dependencies]\nui=["agi-web==2026.6.20"]\n', encoding="utf-8")
    monkeypatch.setattr(module, "selected_public_versions", lambda root: {"agilab": "2026.10.12", "agi-gui": "2026.10.12", "agi-web": "2026.10.12"})
    monkeypatch.setattr(module, "public_package_entries", lambda **k: [{"project": "."}])
    protections = module.current_project_protections(tmp_path)
    assert protections["agi-gui"] == {"2026.6.19", "2026.10.12"}
    assert protections["agi-web"] == {"2026.6.20", "2026.10.12"}


def _saved_explicit_backup(module, tmp_path, monkeypatch):
    import io
    directory = tmp_path / "saved_release"
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"wheel"))
    plans = module.build_explicit_plans({"agi-gui": ("2026.6.19",)}, repo="pypi", repo_root=REPO_ROOT)
    module.prepare_release_backups(plans, repo="pypi", directory=directory)
    return directory, plans


def test_backups_bind_complete_file_set_and_fresh_official_hashes(monkeypatch, tmp_path):
    module = _explicit_module(monkeypatch)
    directory, plans = _saved_explicit_backup(module, tmp_path, monkeypatch)
    module.verify_release_backups(plans, repo="pypi", directory=directory)
    (directory / "agi-gui" / "2026.6.19" / "archive.whl").write_bytes(b"WRONG")
    with pytest.raises(SystemExit, match="missing or changed"):
        module.verify_release_backups(plans, repo="pypi", directory=directory)


def test_backup_manifest_cannot_substitute_another_target_or_file_set(monkeypatch, tmp_path):
    module = _explicit_module(monkeypatch)
    directory, plans = _saved_explicit_backup(module, tmp_path, monkeypatch)
    manifest_path = directory / module.BACKUP_MANIFEST
    original = json.loads(manifest_path.read_text())
    changed = json.loads(json.dumps(original))
    changed["releases"][0]["version"] = "2026.6.20"
    manifest_path.write_text(json.dumps(changed))
    with pytest.raises(SystemExit, match="exact deletion selection"):
        module.verify_release_backups(plans, repo="pypi", directory=directory)
    changed = json.loads(json.dumps(original))
    changed["releases"][0]["files"] = []
    manifest_path.write_text(json.dumps(changed))
    with pytest.raises(SystemExit, match="every official release archive"):
        module.verify_release_backups(plans, repo="pypi", directory=directory)


def test_confirmed_deletion_requires_backup_before_authentication(monkeypatch):
    module = _explicit_module(monkeypatch)
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: pytest.fail("backup guard must run first"))
    with pytest.raises(SystemExit, match="requires --backup-dir"):
        module.main(["--delete-release", "agi-gui==2026.6.19", "--confirm-delete"])


def test_failed_authentication_is_fail_closed_without_delete_or_success(monkeypatch, tmp_path):
    module = _explicit_module(monkeypatch)
    directory, _ = _saved_explicit_backup(module, tmp_path, monkeypatch)
    def no_auth(*args, **kwargs):
        raise SystemExit("authentication failed")
    monkeypatch.setattr(module, "require_credentials", no_auth)
    monkeypatch.setattr(module, "delete_release", lambda **k: pytest.fail("must not delete after failed authentication"))
    with pytest.raises(SystemExit, match="authentication failed"):
        module.main(["--delete-release", "agi-gui==2026.6.19", "--confirm-delete", "--backup-dir", str(directory)])


def test_confirmed_cleanup_deletes_only_allowed_target_and_retains_other_old_versions(monkeypatch, tmp_path, capsys):
    module = _explicit_module(monkeypatch)
    directory, _ = _saved_explicit_backup(module, tmp_path, monkeypatch)
    deleted = []
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: ("user", "password"))
    monkeypatch.setattr(module, "resolve_auth_code", lambda *a: None)
    def guarded_delete(**kwargs):
        kwargs["before_delete"]()
        deleted.append((kwargs["package"], kwargs["version"]))
    monkeypatch.setattr(module, "delete_release", guarded_delete)
    monkeypatch.setattr(module, "probe_exact_release_version", lambda package, repo, version: (
        module.EXACT_RELEASE_ABSENT if (package, version) in deleted else module.EXACT_RELEASE_PRESENT, version
    ))
    assert module.main(["--delete-release", "agi-gui==2026.6.19", "--confirm-delete", "--backup-dir", str(directory), "--json"]) == 0
    assert deleted == [("agi-gui", "2026.6.19")]
    assert json.loads(capsys.readouterr().out)["dry_run"] is False


def test_failed_device_confirmation_stops_before_next_selected_delete(monkeypatch, tmp_path):
    module = _explicit_module(monkeypatch)
    selected = {"agi-gui": ("2026.6.19", "2026.6.20")}
    plans = module.build_explicit_plans(selected, repo="pypi", repo_root=REPO_ROOT)
    import io
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"wheel"))
    directory = tmp_path / "two_release_backup"
    module.prepare_release_backups(plans, repo="pypi", directory=directory)
    calls = []
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: ("user", "password"))
    monkeypatch.setattr(module, "resolve_auth_code", lambda *a: None)
    def blocked(**kwargs):
        calls.append((kwargs["package"], kwargs["version"]))
        raise SystemExit("device confirmation required")
    monkeypatch.setattr(module, "delete_release", blocked)
    with pytest.raises(SystemExit, match="device confirmation required"):
        module.main(["--delete-release", "agi-gui==2026.6.19", "--delete-release", "agi-gui==2026.6.20", "--confirm-delete", "--backup-dir", str(directory)])
    assert calls == [("agi-gui", "2026.6.19")]


def test_post_delete_checks_selected_absence_and_preserves_unselected_releases(monkeypatch):
    module = _explicit_module(monkeypatch)
    plans = module.build_explicit_plans({"agi-gui": ("2026.6.19",)}, repo="pypi", repo_root=REPO_ROOT)
    monkeypatch.setattr(module, "fetch_releases", lambda *a: ["2026.10.12"])
    monkeypatch.setattr(module, "probe_exact_release_version", lambda *a: (module.EXACT_RELEASE_ABSENT, None))
    with pytest.raises(SystemExit, match="unselected release"):
        module.verify_explicit_cleanup(plans, repo="pypi", attempts=1, retry_delay=0)


def test_post_delete_never_accepts_endpoint_error_as_absence(monkeypatch):
    module = _explicit_module(monkeypatch)
    plans = module.build_explicit_plans({"agi-gui": ("2026.6.19",)}, repo="pypi", repo_root=REPO_ROOT)
    monkeypatch.setattr(module, "probe_exact_release_version", lambda *a: (module.EXACT_RELEASE_ERROR, None))
    assert module.verify_explicit_cleanup(plans, repo="pypi", attempts=1, retry_delay=0) is False


@pytest.mark.parametrize("filename", ["../escape.whl", r"..\escape.whl"])
def test_backup_rejects_nonportable_or_escaping_filenames(monkeypatch, filename):
    module = _explicit_module(monkeypatch)
    metadata = module.fresh_release_metadata("agi-gui", "pypi", "2026.6.19")
    metadata["urls"][0]["filename"] = filename
    with pytest.raises(SystemExit, match="archive metadata"):
        module.release_archive_entries(metadata, repo="pypi")

@pytest.mark.parametrize("equivalent", ["2026.6.19.0", "2026.06.19.00"])
def test_explicit_selection_rejects_pep440_equivalent_duplicates(equivalent):
    module = _load_module()
    with pytest.raises(SystemExit, match="duplicate"):
        module.parse_delete_releases(["agi-gui==2026.6.19", f"agi-gui=={equivalent}"])


@pytest.mark.parametrize("protection_source", ["current", "dependency", "extra"])
def test_explicit_plan_blocks_equivalent_current_dependency_and_extra_protections(monkeypatch, protection_source):
    module = _explicit_module(monkeypatch)
    if protection_source in {"current", "dependency"}:
        monkeypatch.setattr(module, "current_project_protections", lambda root: {"agi-gui": {"2026.6.19.0", "2026.10.12"}})
    extra = ["agi-gui=2026.6.19.0"] if protection_source == "extra" else []
    with pytest.raises(SystemExit, match="current, latest or pinned"):
        module.build_explicit_plans({"agi-gui": ("2026.6.19",)}, repo="pypi", repo_root=REPO_ROOT, extra_protections=extra)


def test_exact_selection_uses_published_spelling_and_regex_for_equivalent_input(monkeypatch):
    module = _explicit_module(monkeypatch)
    monkeypatch.setattr(module, "fetch_releases", lambda *a: ["2026.06.19", "2026.10.12.0"])
    plans = module.build_explicit_plans({"agi-gui": ("2026.6.19.0",)}, repo="pypi", repo_root=REPO_ROOT)
    assert plans[0].versions == ("2026.06.19",)
    assert module.exact_release_regex(plans[0].versions[0]) == r"^2026\.06\.19$"
    with pytest.raises(SystemExit, match="current, latest or pinned"):
        module.build_explicit_plans({"agi-gui": ("2026.10.12",)}, repo="pypi", repo_root=REPO_ROOT)


def _authenticated_guard_session(module, monkeypatch, *, on_auth=lambda: None, on_delete=lambda version: None):
    import requests
    from urllib.parse import urlparse
    events = []
    class Response:
        def __init__(self, url, text):
            self.url, self.text = url, text
        def raise_for_status(self):
            pass
    def form(action, *fields):
        return '<form method="post" action="' + action + '">' + ''.join(
            '<input name="' + field + '" value="test">' for field in ("csrf_token", *fields)
        ) + '</form>'
    class Session:
        def __init__(self):
            self.headers = {}
            self.version = None
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def get(self, url):
            path = urlparse(url).path
            if path == "/account/login/":
                return Response(url, form(path))
            self.version = path.rstrip("/").split("/")[-1]
            return Response(url, form("/account/reauthenticate/", "password", "next_route", "next_route_matchdict"))
        def post(self, url, **kwargs):
            path = urlparse(url).path
            if path == "/account/login/":
                events.append("password")
                return Response("https://pypi.org/account/two-factor/", form("/account/two-factor/"))
            if path == "/account/two-factor/":
                events.append("mfa")
                return Response("https://pypi.org/manage/projects/", "")
            if path == "/account/reauthenticate/":
                events.append("reauth")
                on_auth()
                delete_path = f"/manage/project/agi-gui/release/{self.version}/"
                return Response("https://pypi.org" + delete_path, form(delete_path, "confirm_delete_version"))
            events.append("delete:" + self.version)
            on_delete(self.version)
            return Response("https://pypi.org/manage/project/agi-gui/releases/", "")
    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(module, "_fresh_totp_code", lambda *a, **k: events.append("totp-wait") or "123456")
    return events


def test_guarded_web_post_runs_callback_after_password_totp_mfa_and_reauth(monkeypatch):
    module = _load_module()
    events = _authenticated_guard_session(module, monkeypatch)
    module.delete_release(package="agi-gui", version="2026.6.19", repo="pypi",
                          username="user", password="password", auth_code="123456",
                          before_delete=lambda: events.append("guard"))
    assert events == ["password", "totp-wait", "mfa", "reauth", "guard", "delete:2026.6.19"]


@pytest.mark.parametrize("entrypoint", ["delete_release", "delete_release_via_pypi_web"])
def test_low_level_deletion_without_callback_cannot_authenticate_or_spawn(monkeypatch, entrypoint):
    module = _load_module()
    import requests
    monkeypatch.setattr(requests, "Session", lambda: pytest.fail("must reject before authentication"))
    assert not hasattr(module, "subprocess")
    with pytest.raises(SystemExit, match="guard immediately before"):
        getattr(module, entrypoint)(package="agi-gui", version="2026.6.19", repo="pypi", username="user", password="password")


@pytest.mark.parametrize("change", ["new_archive", "changed_backup", "new_protected_pin"])
def test_main_revalidates_current_target_after_authentication_before_post(monkeypatch, tmp_path, change):
    module = _explicit_module(monkeypatch)
    metadata = module.fresh_release_metadata("agi-gui", "pypi", "2026.6.19")
    monkeypatch.setattr(module, "fresh_release_metadata", lambda *a: metadata)
    protections = {"agi-gui": {"2026.10.12"}}
    monkeypatch.setattr(module, "current_project_protections", lambda root: protections)
    directory, _ = _saved_explicit_backup(module, tmp_path, monkeypatch)
    def during_auth():
        if change == "new_archive":
            metadata["urls"].append({"filename": "extra.whl", "url": "https://files.pythonhosted.org/extra.whl", "digests": {"sha256": module.hashlib.sha256(b"more").hexdigest()}, "size": 4})
        elif change == "changed_backup":
            (directory / "agi-gui" / "2026.6.19" / "archive.whl").write_bytes(b"WRONG")
        else:
            protections["agi-gui"].add("2026.6.19.0")
    events = _authenticated_guard_session(module, monkeypatch, on_auth=during_auth)
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: ("user", "password"))
    monkeypatch.setattr(module, "resolve_auth_code", lambda *a: "123456")
    with pytest.raises(SystemExit, match="archive|pinned"):
        module.main(["--delete-release", "agi-gui==2026.6.19", "--confirm-delete", "--backup-dir", str(directory)])
    assert "reauth" in events
    assert not any(event.startswith("delete:") for event in events)


def test_second_target_backup_guard_sees_new_archive_after_first_delete(monkeypatch, tmp_path):
    module = _explicit_module(monkeypatch)
    originals = {version: module.fresh_release_metadata("agi-gui", "pypi", version) for version in ("2026.6.19", "2026.6.20")}
    deleted = []
    def metadata(package, repo, version):
        if version in deleted:
            pytest.fail("must not refetch an already deleted release while guarding another target")
        return originals[version]
    monkeypatch.setattr(module, "fresh_release_metadata", metadata)
    import io
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"wheel"))
    plans = module.build_explicit_plans({"agi-gui": ("2026.6.19", "2026.6.20")}, repo="pypi", repo_root=REPO_ROOT)
    directory = tmp_path / "saved_two_targets"
    module.prepare_release_backups(plans, repo="pypi", directory=directory)
    def first_delete(version):
        deleted.append(version)
        originals["2026.6.20"]["urls"].append({"filename": "extra.whl", "url": "https://files.pythonhosted.org/extra.whl", "digests": {"sha256": module.hashlib.sha256(b"more").hexdigest()}, "size": 4})
    events = _authenticated_guard_session(module, monkeypatch, on_delete=first_delete)
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: ("user", "password"))
    monkeypatch.setattr(module, "resolve_auth_code", lambda *a: "123456")
    with pytest.raises(SystemExit, match="every official release archive"):
        module.main(["--delete-release", "agi-gui==2026.6.19", "--delete-release", "agi-gui==2026.6.20", "--confirm-delete", "--backup-dir", str(directory)])
    assert deleted == ["2026.6.19"]
    assert "delete:2026.6.20" not in events


def test_current_target_backup_guard_keeps_original_manifest_selection(monkeypatch, tmp_path):
    module = _explicit_module(monkeypatch)
    directory, plans = _saved_explicit_backup(module, tmp_path, monkeypatch)
    with pytest.raises(SystemExit, match="outside the original exact selection"):
        module.verify_release_backups(plans, repo="pypi", directory=directory, current_target=("agi-gui", "2026.6.20"))
    manifest_path = directory / module.BACKUP_MANIFEST
    manifest = json.loads(manifest_path.read_text())
    manifest["releases"].append(dict(manifest["releases"][0], version="2026.6.19.0"))
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(SystemExit, match="exact deletion selection"):
        module.verify_release_backups(plans, repo="pypi", directory=directory, current_target=("agi-gui", "2026.6.19"))


def test_exact_endpoint_accepts_equivalent_pep440_response(monkeypatch):
    module = _load_module(stub_network=False)
    import io
    payload = json.dumps({"info": {"version": "2026.6.19.0"}}).encode()
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))
    assert module.probe_exact_release_version("agi-gui", "pypi", "2026.6.19") == (module.EXACT_RELEASE_PRESENT, "2026.6.19")

@pytest.mark.parametrize(("inventory", "message"), [
    (["2026.6.19", "2026.6.19.0", "2026.10.12"], "ambiguous equivalent"),
    ([], "no published releases"),
])
def test_explicit_inventory_rejects_ambiguous_equivalent_or_empty_releases(monkeypatch, inventory, message):
    module = _explicit_module(monkeypatch)
    monkeypatch.setattr(module, "fetch_releases", lambda *a: inventory)
    with pytest.raises(SystemExit, match=message):
        module.build_explicit_plans({"agi-gui": ("2026.6.19",)}, repo="pypi", repo_root=REPO_ROOT)


def test_unknown_extra_protection_is_rejected_before_mutation(monkeypatch):
    module = _explicit_module(monkeypatch)
    with pytest.raises(SystemExit, match="unknown protected first-party"):
        module.build_explicit_plans({"agi-gui": ("2026.6.19",)}, repo="pypi", repo_root=REPO_ROOT, extra_protections=["unrelated=2026.6.19"])


@pytest.mark.parametrize("manifest", [None, "invalid-json"])
def test_missing_or_invalid_backup_manifest_stops_before_auth(monkeypatch, tmp_path, manifest):
    module = _explicit_module(monkeypatch)
    directory = tmp_path / "missing_backup"
    directory.mkdir()
    if manifest:
        (directory / module.BACKUP_MANIFEST).write_text(manifest)
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: pytest.fail("must not authenticate without a complete manifest"))
    with pytest.raises(SystemExit, match="readable backup manifest"):
        module.main(["--delete-release", "agi-gui==2026.6.19", "--confirm-delete", "--backup-dir", str(directory)])


def test_plan_mode_can_archive_selected_release_without_credentials(monkeypatch, tmp_path, capsys):
    module = _explicit_module(monkeypatch)
    import io
    downloads = []
    def download(url, **kwargs):
        downloads.append(url)
        return io.BytesIO(b"wheel")
    monkeypatch.setattr(module.urllib.request, "urlopen", download)
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: pytest.fail("planning must not authenticate"))
    directory = tmp_path / "planned_backup"
    assert module.main(["--delete-release", "agi-gui==2026.6.19", "--backup-dir", str(directory), "--json"]) == 0
    assert downloads == ["https://files.pythonhosted.org/archive.whl"]
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert (directory / module.BACKUP_MANIFEST).is_file()


def test_confirm_and_dry_run_conflict_before_inventory(monkeypatch):
    module = _explicit_module(monkeypatch)
    monkeypatch.setattr(module, "build_explicit_plans", lambda *a, **k: pytest.fail("conflicting flags must stop before inventory"))
    with pytest.raises(SystemExit, match="mutually exclusive"):
        module.main(["--delete-release", "agi-gui==2026.6.19", "--confirm-delete", "--dry-run"])


def test_changed_server_spelling_during_auth_requires_a_new_plan(monkeypatch, tmp_path):
    module = _explicit_module(monkeypatch)
    directory, _ = _saved_explicit_backup(module, tmp_path, monkeypatch)
    inventory = ["2026.6.19", "2026.6.20", "2026.10.12"]
    monkeypatch.setattr(module, "fetch_releases", lambda *a: inventory)
    def change():
        inventory[0] = "2026.6.19.0"
    events = _authenticated_guard_session(module, monkeypatch, on_auth=change)
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: ("user", "password"))
    monkeypatch.setattr(module, "resolve_auth_code", lambda *a: "123456")
    with pytest.raises(SystemExit, match="published target spelling changed"):
        module.main(["--delete-release", "agi-gui==2026.6.19", "--confirm-delete", "--backup-dir", str(directory)])
    assert not any(event.startswith("delete:") for event in events)


def test_default_web_flow_rejected_mfa_never_runs_guard_or_deletes(monkeypatch):
    module = _load_module()
    import requests
    events = _authenticated_guard_session(module, monkeypatch)
    original = requests.Session
    class RejectedSession(original):
        def post(self, url, **kwargs):
            response = super().post(url, **kwargs)
            if "/account/two-factor/" in url:
                response.url = "https://pypi.org/account/two-factor/"
            return response
    monkeypatch.setattr(requests, "Session", RejectedSession)
    with pytest.raises(SystemExit, match="rejected the generated TOTP"):
        module.delete_release(package="agi-gui", version="2026.6.19", repo="pypi", username="user", password="password", auth_code="123456", before_delete=lambda: pytest.fail("guard must not run after rejected MFA"))
    assert not any(event.startswith("delete:") for event in events)


def test_confirmed_cleanup_unconfirmed_endpoint_never_reports_success(monkeypatch, tmp_path):
    module = _explicit_module(monkeypatch)
    directory, _ = _saved_explicit_backup(module, tmp_path, monkeypatch)
    _authenticated_guard_session(module, monkeypatch)
    monkeypatch.setattr(module, "require_credentials", lambda *a, **k: ("user", "password"))
    monkeypatch.setattr(module, "resolve_auth_code", lambda *a: "123456")
    monkeypatch.setattr(module, "verify_explicit_cleanup", lambda *a, **k: False)
    with pytest.raises(SystemExit, match="not confirmed by its exact endpoint"):
        module.main(["--delete-release", "agi-gui==2026.6.19", "--confirm-delete", "--backup-dir", str(directory)])
