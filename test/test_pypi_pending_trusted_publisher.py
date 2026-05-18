from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "pypi_pending_trusted_publisher.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pypi-pending-trusted-publisher.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "pypi_pending_trusted_publisher_test_module",
        MODULE_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, *, text: str, url: str, preserve_url: bool = False) -> None:
        self.text = text
        self.url = url
        self.preserve_url = preserve_url

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, *, gets: list[FakeResponse], posts: list[FakeResponse]) -> None:
        self.headers: dict[str, str] = {}
        self.get_responses = gets
        self.post_responses = posts
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url):
        self.get_calls.append(url)
        response = self.get_responses.pop(0)
        if not response.preserve_url:
            response.url = url
        return response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)


def _login_form() -> str:
    return """
    <form method="post" action="/account/login/">
      <input name="csrf_token" value="login-csrf">
    </form>
    """


def _reauth_form() -> str:
    return """
    <form method="post" action="/account/reauthenticate/">
      <input name="csrf_token" value="reauth-csrf">
      <input name="username" value="maintainer">
      <input name="next_route" value="manage.account.publishing">
      <input name="next_route_matchdict" value="{}">
      <input name="next_route_query" value="{}">
      <input name="password" type="password">
    </form>
    """


def _publisher_form() -> str:
    return """
    <form method="post" action="/manage/account/publishing/#errors">
      <input name="csrf_token" value="publisher-csrf">
      <input name="project_name" value="">
      <input name="owner" value="">
      <input name="repository" value="">
      <input name="workflow_filename" value="">
      <input name="environment" value="">
    </form>
    """


def test_dry_run_does_not_require_credentials(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.delenv("PYPI_RELEASE_PRUNE_USERNAME", raising=False)
    monkeypatch.delenv("PYPI_RELEASE_PRUNE_PASSWORD", raising=False)

    status = module.main(
        [
            "--project-name",
            "agi-page-scenario-cockpit",
            "--environment",
            "pypi-agi-page-scenario-cockpit",
            "--dry-run",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert '"dry_run": true' in captured.out
    assert "agi-page-scenario-cockpit" in captured.out


def test_register_submits_github_pending_publisher_form_after_login_and_reauth() -> None:
    module = _load_module()
    publisher = module.PendingGitHubPublisher(
        project_name="agi-page-scenario-cockpit",
        owner="ThalesGroup",
        repository="agilab",
        workflow_filename="pypi-publish.yaml",
        environment="pypi-agi-page-scenario-cockpit",
    )
    session = FakeSession(
        gets=[
            FakeResponse(url="https://pypi.org/account/login/", text=_login_form()),
            FakeResponse(
                url="https://pypi.org/manage/account/publishing/",
                text=_reauth_form(),
            ),
        ],
        posts=[
            FakeResponse(url="https://pypi.org/manage/projects/", text="<html></html>"),
            FakeResponse(
                url="https://pypi.org/manage/account/publishing/",
                text=_publisher_form(),
            ),
            FakeResponse(
                url="https://pypi.org/manage/account/publishing/",
                text=(
                    "Registered a new pending publisher to create "
                    "the project 'agi-page-scenario-cockpit'."
                ),
            ),
        ],
    )

    result = module.register_pending_github_publisher(
        publisher=publisher,
        repo="pypi",
        username="maintainer",
        password="secret",
        session_factory=lambda: session,
    )

    assert result.registered is True
    assert session.post_calls[2][0] == "https://pypi.org/manage/account/publishing/#errors"
    assert session.post_calls[2][1]["data"] == {
        "csrf_token": "publisher-csrf",
        "project_name": "agi-page-scenario-cockpit",
        "owner": "ThalesGroup",
        "repository": "agilab",
        "workflow_filename": "pypi-publish.yaml",
        "environment": "pypi-agi-page-scenario-cockpit",
    }


def test_register_handles_totp_when_login_requires_two_factor() -> None:
    module = _load_module()
    publisher = module.PendingGitHubPublisher(
        project_name="agi-page-scenario-cockpit",
        owner="ThalesGroup",
        repository="agilab",
        workflow_filename="pypi-publish.yaml",
        environment="pypi-agi-page-scenario-cockpit",
    )
    session = FakeSession(
        gets=[
            FakeResponse(url="https://pypi.org/account/login/", text=_login_form()),
            FakeResponse(
                url="https://pypi.org/manage/account/publishing/",
                text=_publisher_form(),
            ),
        ],
        posts=[
            FakeResponse(
                url="https://pypi.org/account/two-factor/",
                text="""
                <form method="post" action="/account/two-factor/">
                  <input name="csrf_token" value="totp-csrf">
                </form>
                """,
            ),
            FakeResponse(url="https://pypi.org/manage/projects/", text="<html></html>"),
            FakeResponse(
                url="https://pypi.org/manage/account/publishing/",
                text=(
                    "Registered a new pending publisher to create "
                    "the project 'agi-page-scenario-cockpit'."
                ),
            ),
        ],
    )

    result = module.register_pending_github_publisher(
        publisher=publisher,
        repo="pypi",
        username="maintainer",
        password="secret",
        auth_code="123456",
        session_factory=lambda: session,
    )

    assert result.registered is True
    assert session.post_calls[1][1]["data"] == {
        "csrf_token": "totp-csrf",
        "method": "totp",
        "totp_value": "123456",
    }


def test_register_consumes_same_runner_confirmation_url_before_retrying() -> None:
    module = _load_module()
    publisher = module.PendingGitHubPublisher(
        project_name="agi-page-scenario-cockpit",
        owner="ThalesGroup",
        repository="agilab",
        workflow_filename="pypi-publish.yaml",
        environment="pypi-agi-page-scenario-cockpit",
    )
    confirm_url = "https://pypi.org/account/confirm-login/?token=token"
    session = FakeSession(
        gets=[
            FakeResponse(url="https://pypi.org/account/login/", text=_login_form()),
            FakeResponse(
                url="https://pypi.org/account/login/",
                text="<html>login required</html>",
                preserve_url=True,
            ),
            FakeResponse(url=confirm_url, text="<html>confirmed</html>"),
            FakeResponse(
                url="https://pypi.org/manage/account/publishing/",
                text=_publisher_form(),
            ),
        ],
        posts=[
            FakeResponse(url="https://pypi.org/manage/projects/", text="<html></html>"),
            FakeResponse(
                url="https://pypi.org/manage/account/publishing/",
                text=(
                    "Registered a new pending publisher to create "
                    "the project 'agi-page-scenario-cockpit'."
                ),
            ),
        ],
    )

    result = module.register_pending_github_publisher(
        publisher=publisher,
        repo="pypi",
        username="maintainer",
        password="secret",
        confirm_login_url_provider=lambda: confirm_url,
        session_factory=lambda: session,
    )

    assert result.registered is True
    assert confirm_url in session.get_calls


def test_register_treats_existing_same_pending_publisher_as_success() -> None:
    module = _load_module()
    publisher = module.PendingGitHubPublisher(
        project_name="agi-page-scenario-cockpit",
        owner="ThalesGroup",
        repository="agilab",
        workflow_filename="pypi-publish.yaml",
        environment="pypi-agi-page-scenario-cockpit",
    )

    result = module._interpret_registration_response(
        "This trusted publisher has already been registered.",
        publisher,
    )

    assert result.registered is False
    assert result.already_registered is True


def test_register_rejects_pending_publisher_for_different_project() -> None:
    module = _load_module()
    publisher = module.PendingGitHubPublisher(
        project_name="agi-page-scenario-cockpit",
        owner="ThalesGroup",
        repository="agilab",
        workflow_filename="pypi-publish.yaml",
        environment="pypi-agi-page-scenario-cockpit",
    )

    with pytest.raises(RuntimeError, match="already pending for another project"):
        module._interpret_registration_response(
            "A pending trusted publisher matching this configuration has already "
            "been registered for a different project name.",
            publisher,
        )


def test_pending_trusted_publisher_workflow_uses_release_web_credentials() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "tools/pypi_pending_trusted_publisher.py" in text
    assert "PYPI_RELEASE_PRUNE_USERNAME: ${{ secrets.PYPI_RELEASE_PRUNE_USERNAME }}" in text
    assert "PYPI_RELEASE_PRUNE_PASSWORD: ${{ secrets.PYPI_RELEASE_PRUNE_PASSWORD }}" in text
    assert "PYPI_RELEASE_PRUNE_TOTP_SECRET: ${{ secrets.PYPI_RELEASE_PRUNE_TOTP_SECRET }}" in text
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in text
    assert "PYPI_CONFIRM_READER_TOKEN: ${{ secrets.PYPI_CONFIRM_READER_TOKEN }}" in text
    assert "--project-name \"${{ inputs.project_name }}\"" in text
    assert "--environment \"${{ inputs.pypi_environment }}\"" in text
    assert "--github-confirm-login-variable \"PYPI_CONFIRM_LOGIN_URL\"" in text
    assert "--github-token \"${PYPI_CONFIRM_READER_TOKEN:-$GITHUB_TOKEN}\"" in text
